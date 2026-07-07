from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.agents.learning import reflect_unlearned_scores
from app.brain import journal
from app.brain.memory import MemoryUpdate, PolicyEdit, ReflectionResult
from app.db.models import Agent, DecisionRecord, DecisionScore, MemoryEntry


def _agent(session):
    agent = Agent(
        name="L",
        duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc) + timedelta(days=1),
        cash_usd=Decimal("100"),
        model_name="m",
    )
    session.add(agent)
    session.commit()
    return agent


def _scored_decision(session, agent_id, *, parsed_output=None):
    record = DecisionRecord(
        agent_id=agent_id,
        cycle_id="c",
        kind="decision",
        trigger="schedule",
        system_prompt="s",
        user_prompt="u",
        raw_response="r",
        parsed_output=parsed_output
        or (
            '{"actions":[{"type":"BUY","symbol":"BTCUSDT","policy_refs":["P1"],'
            '"policy_alignment":"violates","override_reason":"fresh catalyst",'
            '"rationale":"news"}]}'
        ),
        parse_status="ok",
        model_provider="openrouter",
        model_name="m",
        latency_ms=1,
    )
    record.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    session.add(record)
    session.commit()

    score = DecisionScore(
        decision_record_id=record.id,
        window="24h",
        n_actions=1,
        n_hits=0,
        avg_return_pct=Decimal("-2.5"),
    )
    session.add(score)
    session.commit()
    return record, score


async def test_reflect_unlearned_scores_applies_memory_and_marks_scores(db_session):
    agent = _agent(db_session)
    _record, score = _scored_decision(db_session, agent.id)
    calls = []

    def fake_run(evidence, memory, policy, instructions, adapter):
        calls.append(evidence)
        return ReflectionResult(
            MemoryUpdate(
                trade_lessons=["Outcome review: override failed."],
                policy_edits=[
                    PolicyEdit(
                        op="add",
                        text="Require fresh evidence before overrides.",
                        reason="A violating BUY scored poorly.",
                    )
                ],
            ),
            system="SYS",
            user="USR",
            raw='{"trade_lessons":["Outcome review: override failed."],"policy_edits":[]}',
            parse_status="ok",
            latency_ms=3,
        )

    reflected = await reflect_unlearned_scores(
        db_session,
        run=fake_run,
        adapter_factory=lambda provider, model: object(),
    )

    assert reflected == 1
    assert calls[0].scores[0].score_id == score.id
    assert (
        db_session.query(DecisionScore).filter_by(id=score.id).one().reflected_at
        is not None
    )
    assert [row.content for row in journal.active_entries(db_session, agent.id, "trade_lessons")] == [
        "Outcome review: override failed."
    ]
    assert [row.content for row in journal.active_entries(db_session, agent.id, "self_policy")] == [
        "Require fresh evidence before overrides."
    ]
    reflection = (
        db_session.query(DecisionRecord)
        .filter_by(agent_id=agent.id, kind="reflection", trigger="scoring")
        .one()
    )
    assert reflection.system_prompt == "SYS"
    assert reflection.user_prompt == "USR"
    assert reflection.latency_ms == 3


async def test_reflect_unlearned_scores_accepts_older_action_payloads(db_session):
    agent = _agent(db_session)
    _record, score = _scored_decision(
        db_session,
        agent.id,
        parsed_output='{"actions":[{"type":"BUY","symbol":"BTCUSDT","rationale":"news"}]}',
    )
    calls = []

    def fake_run(evidence, memory, policy, instructions, adapter):
        calls.append(evidence)
        return ReflectionResult(MemoryUpdate(), system="SYS", user="USR", raw="{}", parse_status="ok")

    reflected = await reflect_unlearned_scores(
        db_session,
        run=fake_run,
        adapter_factory=lambda provider, model: object(),
    )

    assert reflected == 1
    assert calls[0].scores[0].actions == [{"type": "BUY", "symbol": "BTCUSDT", "rationale": "news"}]
    assert (
        db_session.query(DecisionScore).filter_by(id=score.id).one().reflected_at
        is not None
    )


async def test_reflect_unlearned_scores_does_not_repeat_reflected_scores(db_session):
    agent = _agent(db_session)
    _record, score = _scored_decision(db_session, agent.id)
    score.reflected_at = datetime.now(timezone.utc)
    db_session.commit()

    calls = []

    reflected = await reflect_unlearned_scores(
        db_session,
        run=lambda *args, **kwargs: calls.append(1) or ReflectionResult(MemoryUpdate()),
        adapter_factory=lambda provider, model: object(),
    )

    assert reflected == 0
    assert calls == []


async def test_reflect_unlearned_scores_failure_leaves_score_unreflected(db_session):
    agent = _agent(db_session)
    _record, score = _scored_decision(db_session, agent.id)

    def failed(*args, **kwargs):
        return ReflectionResult(
            MemoryUpdate(),
            system="SYS",
            user="USR",
            raw="bad",
            parse_status="failed",
            latency_ms=2,
        )

    reflected = await reflect_unlearned_scores(
        db_session,
        run=failed,
        adapter_factory=lambda provider, model: object(),
    )

    assert reflected == 0
    assert db_session.query(DecisionScore).filter_by(id=score.id).one().reflected_at is None
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id).count() == 0
    reflection = (
        db_session.query(DecisionRecord)
        .filter_by(agent_id=agent.id, kind="reflection", trigger="scoring")
        .one()
    )
    assert reflection.parse_status == "failed"

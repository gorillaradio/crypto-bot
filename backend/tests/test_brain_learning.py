from datetime import datetime, timezone
from decimal import Decimal

from app.brain.context import MemoryView, PolicyLine, PolicyMemoryView
from app.brain.learning import (
    OutcomeReflectionEvidence,
    ScoredActionEvidence,
    build_outcome_reflection_prompt,
    run_outcome_reflection_result,
)
from app.brain.memory import MemoryUpdate


def test_outcome_reflection_prompt_contains_raw_facts_not_judgment():
    evidence = OutcomeReflectionEvidence(
        agent_id=1,
        scores=[
            ScoredActionEvidence(
                decision_record_id=10,
                score_id=20,
                window="24h",
                created_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                n_actions=2,
                n_hits=1,
                avg_return_pct=Decimal("1.25"),
                actions=[
                    {
                        "type": "BUY",
                        "symbol": "BTCUSDT",
                        "policy_refs": ["P3"],
                        "policy_alignment": "violates",
                        "override_reason": "fresh catalyst",
                        "rationale": "news",
                    }
                ],
            )
        ],
    )
    policy = PolicyMemoryView(
        active=[PolicyLine("P3", "Avoid re-entry without fresh evidence.")]
    )

    system, user = build_outcome_reflection_prompt(
        evidence, MemoryView(), policy, "be careful"
    )

    assert "raw factual evidence" in system.lower()
    assert "do not blacklist" in system.lower()
    assert "BTCUSDT" in user
    assert "policy_alignment=violates" in user
    assert "avg_return_pct=1.25" in user
    assert "P3: Avoid re-entry without fresh evidence." in user


def test_run_outcome_reflection_result_parses_memory_update():
    evidence = OutcomeReflectionEvidence(agent_id=1, scores=[])

    class FakeAdapter:
        def complete_json(self, system, user):
            return (
                '{"coin_theses":[],"trade_lessons":["Outcome review: wait."],'
                '"strategy_notes":[],"policy_edits":[]}'
            )

    result = run_outcome_reflection_result(
        evidence, MemoryView(), PolicyMemoryView(), "x", FakeAdapter()
    )

    assert result.parse_status == "ok"
    assert result.entries.trade_lessons == ["Outcome review: wait."]
    assert result.raw is not None


def test_run_outcome_reflection_result_parse_failure_yields_empty_entries():
    evidence = OutcomeReflectionEvidence(agent_id=1, scores=[])

    class FakeAdapter:
        def complete_json(self, system, user):
            return "not json"

    result = run_outcome_reflection_result(
        evidence, MemoryView(), PolicyMemoryView(), "x", FakeAdapter()
    )

    assert result.parse_status == "failed"
    assert result.entries == MemoryUpdate()
    assert result.raw == "not json"

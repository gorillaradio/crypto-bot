import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.brain import journal
from app.brain.learning import (
    ClosedTradeEvidence,
    OutcomeReflectionEvidence,
    ScoredActionEvidence,
    run_outcome_reflection_result,
)
from app.brain.providers import make_adapter
from app.db.models import Agent, DecisionRecord, DecisionScore, Trade

_ACTION_EVIDENCE_FIELDS = (
    "type",
    "symbol",
    "usd_amount",
    "fraction",
    "rationale",
    "policy_refs",
    "policy_alignment",
    "override_reason",
)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _action_evidence(action: dict) -> dict:
    return {key: action[key] for key in _ACTION_EVIDENCE_FIELDS if key in action}


def _actions(parsed_output: str | None) -> list[dict]:
    try:
        actions = json.loads(parsed_output or "{}").get("actions", [])
    except Exception:
        return []
    if not isinstance(actions, list):
        return []
    return [_action_evidence(action) for action in actions if isinstance(action, dict)]


def _unreflected_scores(session) -> list[tuple[Agent, DecisionRecord, DecisionScore]]:
    return (
        session.query(Agent, DecisionRecord, DecisionScore)
        .join(DecisionRecord, DecisionRecord.agent_id == Agent.id)
        .join(DecisionScore, DecisionScore.decision_record_id == DecisionRecord.id)
        .filter(
            DecisionRecord.kind == "decision",
            DecisionRecord.parse_status.in_(("ok", "repaired")),
            DecisionScore.reflected_at.is_(None),
        )
        .order_by(Agent.id.asc(), DecisionScore.scored_at.asc(), DecisionScore.id.asc())
        .all()
    )


def _closed_trade_evidence(session, agent_id: int, *, limit: int = 10) -> list[ClosedTradeEvidence]:
    trades = (
        session.query(Trade)
        .filter_by(agent_id=agent_id)
        .order_by(Trade.timestamp.asc(), Trade.id.asc())
        .all()
    )
    qty_by_symbol: dict[str, Decimal] = {}
    avg_by_symbol: dict[str, Decimal] = {}
    closed: list[ClosedTradeEvidence] = []
    for trade in trades:
        qty = Decimal(trade.quantity)
        price = Decimal(trade.price)
        current_qty = qty_by_symbol.get(trade.symbol, Decimal("0"))
        current_avg = avg_by_symbol.get(trade.symbol)
        if trade.side == "BUY":
            new_qty = current_qty + qty
            avg_by_symbol[trade.symbol] = (
                (current_avg or Decimal("0")) * current_qty + price * qty
            ) / new_qty
            qty_by_symbol[trade.symbol] = new_qty
        elif trade.side == "SELL":
            realized = None
            if current_avg is not None and current_avg > 0:
                realized = (price - current_avg) / current_avg * Decimal("100")
            closed.append(
                ClosedTradeEvidence(
                    symbol=trade.symbol,
                    quantity=qty,
                    sell_price=price,
                    avg_cost=current_avg,
                    realized_pnl_pct=realized,
                    closed_at=_as_utc(trade.timestamp),
                )
            )
            remaining = current_qty - qty
            if remaining > 0:
                qty_by_symbol[trade.symbol] = remaining
            else:
                qty_by_symbol.pop(trade.symbol, None)
                avg_by_symbol.pop(trade.symbol, None)
    return closed[-limit:]


async def reflect_unlearned_scores(
    session,
    *,
    run=run_outcome_reflection_result,
    adapter_factory=make_adapter,
    now: datetime | None = None,
) -> int:
    current_time = _as_utc(now or datetime.now(timezone.utc))
    rows = _unreflected_scores(session)
    by_agent: dict[int, list[tuple[Agent, DecisionRecord, DecisionScore]]] = {}
    for agent, record, score in rows:
        by_agent.setdefault(agent.id, []).append((agent, record, score))

    reflected = 0
    for agent_id, grouped in by_agent.items():
        agent = grouped[0][0]
        evidence = OutcomeReflectionEvidence(
            agent_id=agent_id,
            scores=[
                ScoredActionEvidence(
                    decision_record_id=record.id,
                    score_id=score.id,
                    window=score.window,
                    created_at=_as_utc(record.created_at),
                    n_actions=score.n_actions,
                    n_hits=score.n_hits,
                    avg_return_pct=score.avg_return_pct,
                    actions=_actions(record.parsed_output),
                )
                for _agent, record, score in grouped
            ],
            closed_trades=_closed_trade_evidence(session, agent_id),
        )
        adapter = adapter_factory(agent.model_provider, agent.model_name)
        result = run(
            evidence,
            journal.compact_view(session, agent_id),
            journal.policy_view(session, agent_id),
            agent.instructions,
            adapter,
        )
        cycle_id = uuid4().hex
        reflection = DecisionRecord(
            agent_id=agent_id,
            cycle_id=cycle_id,
            kind="reflection",
            trigger="scoring",
            system_prompt=result.system,
            user_prompt=result.user,
            raw_response=result.raw,
            parsed_output=(
                result.entries.model_dump_json() if result.parse_status == "ok" else None
            ),
            parse_status=result.parse_status,
            model_provider=agent.model_provider,
            model_name=agent.model_name,
            latency_ms=result.latency_ms,
        )
        session.add(reflection)
        if result.parse_status != "ok":
            session.commit()
            continue
        try:
            journal.apply_memory_update(session, agent_id, result.entries, cycle_id=cycle_id)
        except Exception:
            session.rollback()
            session.add(
                DecisionRecord(
                    agent_id=agent_id,
                    cycle_id=cycle_id,
                    kind="reflection",
                    trigger="scoring",
                    system_prompt=result.system,
                    user_prompt=result.user,
                    raw_response=result.raw,
                    parsed_output=None,
                    parse_status="failed",
                    model_provider=agent.model_provider,
                    model_name=agent.model_name,
                    latency_ms=result.latency_ms,
                )
            )
            session.commit()
            continue
        for _agent, _record, score in grouped:
            score.reflected_at = current_time
            reflected += 1
        session.commit()
    return reflected

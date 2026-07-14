import base64
import binascii
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.core.config import settings
from app.api.auth import session_dep, require_admin, require_viewer_or_admin
from app.db.models import Agent, BenchmarkBasis, BenchmarkSnapshot, DecisionRecord, DecisionScore, EquitySnapshot, Event, MemoryEntry, Observation, Position, PositionEvaluation, PositionLifecycle, Trade
from app.api.schemas import AgentCreate, AgentMetricsOut, AgentOut, AgentUpdate, BenchmarkMetric, BenchmarkPoint, ClosedPositionOut, DecisionRecordOut, EquityPoint, EventOut, HighlightOut, LifecycleCollectionOut, LifecycleEvaluationOut, LifecycleSummary, MarketBriefOut, MemoryEntryOut, MemoryOut, ModelMetricsOut, ObservationOut, OpenLifecycleOut, PolicyLineOut, PositionOut, PromptPreviewOut, TradeOut, WindowHitRate
from app.market.binance import BinanceClient
from app.agents.preview import render_agent_prompts_preview
from app.brain.brief_store import latest_valid_brief, filter_brief_for
from app.agents.runtime import universe_size
from app.eval.metrics import total_return_pct, max_drawdown_pct, sharpe, hit_rate

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _latest_equity(session, agent: Agent) -> Decimal:
    snap = (
        session.query(EquitySnapshot)
        .filter_by(agent_id=agent.id)
        .order_by(EquitySnapshot.timestamp.desc())
        .first()
    )
    return snap.equity_usd if snap else agent.cash_usd


def market_dep() -> BinanceClient:
    return BinanceClient()


def _encode_lifecycle_cursor(
    agent_id: int, state: str, closed_since: datetime, key: tuple,
    remaining_ids: list[str] | None = None,
) -> str:
    payload = json.dumps({
        "v": 1,
        "agent_id": agent_id,
        "state": state,
        "closed_since": _utc(closed_since).isoformat(),
        "key": list(key),
        "remaining_ids": remaining_ids,
    }, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_lifecycle_cursor(cursor: str | None) -> dict | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True).decode())
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or type(payload.get("agent_id")) is not int
            or payload.get("state") not in ("open", "closed", "all")
            or not isinstance(payload.get("closed_since"), str)
            or not isinstance(payload.get("key"), list)
            or len(payload["key"]) != 3
            or (
                payload.get("remaining_ids") is not None
                and (
                    not isinstance(payload["remaining_ids"], list)
                    or any(not isinstance(value, str) for value in payload["remaining_ids"])
                    or len(payload["remaining_ids"]) != len(set(payload["remaining_ids"]))
                )
            )
        ):
            raise ValueError
        datetime.fromisoformat(payload["closed_since"])
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(422, "invalid cursor") from exc


def _lifecycle_sort_key(state: str, row: LifecycleSummary) -> tuple:
    if state == "open":
        return (row.exposure_usd is not None, row.exposure_usd or Decimal("0"), row.lifecycle_id)
    if state == "closed":
        return (_utc(row.closed_at), row.lifecycle_id, "")
    timestamp = row.last_changed_at if row.status == "open" else row.closed_at
    return (row.status == "open", _utc(timestamp), row.lifecycle_id)


def _lifecycle_cursor_key(state: str, values: list) -> tuple:
    try:
        if state == "open":
            if type(values[0]) is not bool or not isinstance(values[2], str):
                raise ValueError
            exposure = Decimal(values[1])
            if not exposure.is_finite():
                raise ValueError
            return (values[0], exposure, values[2])
        if state == "closed":
            if not isinstance(values[1], str):
                raise ValueError
            return (_utc(datetime.fromisoformat(values[0])), values[1], "")
        if type(values[0]) is not bool or not isinstance(values[2], str):
            raise ValueError
        return (values[0], _utc(datetime.fromisoformat(values[1])), values[2])
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise HTTPException(422, "invalid cursor") from exc


def _trade_totals(trades: list[Trade]) -> tuple[Decimal, Decimal, Decimal]:
    invested = sum(
        (trade.price * trade.quantity for trade in trades if trade.side == "BUY"),
        Decimal("0"),
    )
    fees = sum((trade.fee for trade in trades), Decimal("0"))
    cash_flow = sum(
        ((trade.price * trade.quantity) * (Decimal("1") if trade.side == "SELL" else Decimal("-1"))
         for trade in trades),
        Decimal("0"),
    )
    return invested, fees, cash_flow - fees


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _agent_out(session, agent: Agent) -> AgentOut:
    equity = _latest_equity(session, agent)
    initial = agent.initial_capital_usd
    ret = ((equity - initial) / initial * Decimal("100")) if initial else Decimal("0")
    return AgentOut(
        id=agent.id,
        name=agent.name,
        instructions=agent.instructions,
        status=agent.status,
        cash_usd=agent.cash_usd,
        equity=equity,
        return_pct=ret,
        duration_start=agent.duration_start,
        duration_end=agent.duration_end,
        decision_seconds=settings.decision_seconds,
    )


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreate, session=Depends(session_dep), _: str = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    agent = Agent(
        name=payload.name,
        instructions=payload.instructions,
        duration_start=now,
        duration_end=now + timedelta(days=payload.duration_days),
        cash_usd=settings.initial_capital_usd,
        initial_capital_usd=settings.initial_capital_usd,
        universe=payload.universe,
        model_name=payload.model_name,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return _agent_out(session, agent)


@router.get("/agents", response_model=list[AgentOut])
def list_agents(session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return [_agent_out(session, a) for a in session.query(Agent).all()]


@router.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    return _agent_out(session, agent)


@router.patch("/agents/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, payload: AgentUpdate, session=Depends(session_dep), _: str = Depends(require_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    agent.name = payload.name
    session.commit()
    session.refresh(agent)
    return _agent_out(session, agent)


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: int, session=Depends(session_dep), _: str = Depends(require_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    rec_ids = [rid for (rid,) in
               session.query(DecisionRecord.id).filter_by(agent_id=agent_id).all()]
    if rec_ids:
        (session.query(DecisionScore)
         .filter(DecisionScore.decision_record_id.in_(rec_ids))
         .delete(synchronize_session=False))
    for model in (PositionEvaluation, Position, Trade, PositionLifecycle, EquitySnapshot,
                  Event, MemoryEntry, DecisionRecord, BenchmarkBasis, BenchmarkSnapshot):
        session.query(model).filter_by(agent_id=agent_id).delete(synchronize_session=False)
    session.delete(agent)
    session.commit()


@router.get("/agents/{agent_id}/positions", response_model=list[PositionOut])
async def get_positions(agent_id: int, session=Depends(session_dep),
                        market=Depends(market_dep), _: str = Depends(require_viewer_or_admin)):
    rows = session.query(Position).filter_by(agent_id=agent_id).all()
    prices: dict[str, Decimal] = {}
    if rows:
        try:
            snap = await market.get_universe_snapshot([p.symbol for p in rows])
            prices = {c.symbol: c.price for c in snap}
        except Exception as exc:
            logger.warning("positions P&L: market snapshot failed for agent %s: %s", agent_id, exc)
            prices = {}                    # market down → degrada a cost-only, mai 502
    out = []
    for p in rows:
        last = prices.get(p.symbol)
        pnl = (((last - p.avg_price) / p.avg_price) * Decimal("100")
               if last is not None and p.avg_price else None)
        out.append(PositionOut(
            symbol=p.symbol, quantity=p.quantity, avg_price=p.avg_price,
            cost_basis=p.quantity * p.avg_price,
            last_price=last,
            unrealized_pnl_pct=pnl,
            market_value=(p.quantity * last) if last is not None else None,
            opened_at=p.opened_at,
            realized_usd=p.realized_usd or Decimal("0"),
        ))
    return out


@router.get("/agents/{agent_id}/positions/closed", response_model=list[ClosedPositionOut])
def get_closed_positions(agent_id: int, session=Depends(session_dep),
                         _: str = Depends(require_viewer_or_admin)):
    # Lo storico vive negli eventi di chiusura totale (payload.position_summary);
    # il filtro JSON si fa in python: volumi piccoli (<=100 righe utili).
    rows = (session.query(Event)
            .filter_by(agent_id=agent_id, kind="trade")
            .order_by(Event.timestamp.desc(), Event.id.desc())
            .limit(500).all())
    out = []
    for e in rows:
        s = (e.payload or {}).get("position_summary")
        if not s:
            continue
        out.append(ClosedPositionOut(
            symbol=(e.payload or {}).get("symbol", ""),
            opened_at=datetime.fromisoformat(s["opened_at"]) if s.get("opened_at") else None,
            closed_at=datetime.fromisoformat(s["closed_at"]) if s.get("closed_at") else e.timestamp,
            held_minutes=s.get("held_minutes"),
            invested_usd=Decimal(s["invested_usd"]) if s.get("invested_usd") else None,
            realized_total_usd=Decimal(s.get("realized_total_usd") or "0"),
            realized_total_pct=Decimal(s["realized_total_pct"]) if s.get("realized_total_pct") else None,
            close_cycle_id=e.cycle_id,
        ))
        if len(out) >= 50:
            break
    return out


@router.get("/agents/{agent_id}/lifecycles/open", response_model=list[OpenLifecycleOut])
async def get_open_lifecycles(agent_id: int, session=Depends(session_dep),
                              market=Depends(market_dep),
                              _: str = Depends(require_viewer_or_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    rows = (
        session.query(Position, PositionLifecycle)
        .join(PositionLifecycle, Position.lifecycle_id == PositionLifecycle.id)
        .filter(Position.agent_id == agent_id, PositionLifecycle.closed_at.is_(None))
        .all()
    )
    prices: dict[str, Decimal] = {}
    if rows:
        try:
            snapshot = await market.get_universe_snapshot([position.symbol for position, _ in rows])
            prices = {coin.symbol: coin.price for coin in snapshot}
        except Exception as exc:
            logger.warning("open lifecycles: market snapshot failed for agent %s: %s", agent_id, exc)
    output = []
    for position, lifecycle in rows:
        trades = (
            session.query(Trade)
            .filter_by(agent_id=agent_id, lifecycle_id=lifecycle.id)
            .order_by(Trade.timestamp.asc(), Trade.id.asc())
            .all()
        )
        if not trades:
            continue
        evaluation = (
            session.query(PositionEvaluation)
            .filter_by(agent_id=agent_id, lifecycle_id=lifecycle.id)
            .order_by(PositionEvaluation.timestamp.desc(), PositionEvaluation.id.desc())
            .first()
        )
        fees = sum((trade.fee for trade in trades), Decimal("0"))
        last_price = prices.get(position.symbol)
        unrealized = ((last_price - position.avg_price) * position.quantity
                      if last_price is not None else None)
        gross_result = ((position.realized_usd or Decimal("0")) + unrealized
                        if unrealized is not None else None)
        net_result = gross_result - fees if gross_result is not None else None
        invested = position.invested_usd or Decimal("0")
        output.append(OpenLifecycleOut(
            lifecycle_id=lifecycle.id,
            cycle_id=lifecycle.last_cycle_id,
            symbol=position.symbol,
            opened_at=lifecycle.opened_at,
            last_changed_at=trades[-1].timestamp,
            quantity=position.quantity,
            avg_price=position.avg_price,
            cost_basis=position.quantity * position.avg_price,
            last_price=last_price,
            exposure_usd=(position.quantity * last_price) if last_price is not None else None,
            fees_usd=fees,
            realized_usd=position.realized_usd or Decimal("0"),
            unrealized_usd=unrealized,
            net_result_usd=net_result,
            net_result_pct=(net_result / invested * Decimal("100")) if net_result is not None and invested else None,
            evaluation=(LifecycleEvaluationOut(
                action=evaluation.action, rationale=evaluation.rationale,
                cycle_id=evaluation.cycle_id, timestamp=evaluation.timestamp,
            ) if evaluation else None),
        ))
    return output


@router.get("/agents/{agent_id}/lifecycles", response_model=LifecycleCollectionOut)
async def get_lifecycles(
    agent_id: int,
    state: Literal["open", "closed", "all"] = "open",
    closed_since: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    session=Depends(session_dep),
    market=Depends(market_dep),
    _: str = Depends(require_viewer_or_admin),
):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    cursor_payload = _decode_lifecycle_cursor(cursor)
    if cursor_payload is not None and (
        cursor_payload["agent_id"] != agent_id or cursor_payload["state"] != state
    ):
        raise HTTPException(422, "cursor does not match lifecycle filters")
    if cursor_payload is not None:
        _lifecycle_cursor_key(state, cursor_payload["key"])
    if cursor_payload is not None and state in ("open", "all") and not isinstance(
        cursor_payload["remaining_ids"], list
    ):
        raise HTTPException(422, "invalid cursor")
    cursor_threshold = (
        _utc(datetime.fromisoformat(cursor_payload["closed_since"]))
        if cursor_payload is not None else None
    )
    if cursor_threshold is not None and closed_since is not None and _utc(closed_since) != cursor_threshold:
        raise HTTPException(422, "cursor does not match lifecycle filters")
    threshold = cursor_threshold or closed_since or (datetime.now(timezone.utc) - timedelta(days=7))
    lifecycles = session.query(PositionLifecycle).filter_by(agent_id=agent_id).all()
    positions = {
        position.lifecycle_id: position
        for position in session.query(Position).filter_by(agent_id=agent_id).all()
        if position.lifecycle_id is not None
    }
    open_lifecycles = [row for row in lifecycles if row.closed_at is None]
    prices: dict[str, Decimal] = {}
    if state in ("open", "all") and open_lifecycles:
        try:
            snapshot = await market.get_universe_snapshot([row.symbol for row in open_lifecycles])
            prices = {coin.symbol: coin.price for coin in snapshot}
        except Exception as exc:
            logger.warning("lifecycle collection: market snapshot failed for agent %s: %s", agent_id, exc)

    items: list[LifecycleSummary] = []
    for lifecycle in lifecycles:
        is_open = lifecycle.closed_at is None
        if is_open and state == "closed":
            continue
        if not is_open and state == "open":
            continue
        if not is_open and _utc(lifecycle.closed_at) < _utc(threshold):
            continue
        trades = (
            session.query(Trade)
            .filter_by(agent_id=agent_id, lifecycle_id=lifecycle.id)
            .order_by(Trade.timestamp.asc(), Trade.id.asc())
            .all()
        )
        if not trades:
            continue
        invested, fees, closed_net = _trade_totals(trades)
        if is_open:
            position = positions.get(lifecycle.id)
            if position is None:
                continue
            last_price = prices.get(lifecycle.symbol)
            exposure = position.quantity * last_price if last_price is not None else None
            unrealized = ((last_price - position.avg_price) * position.quantity
                          if last_price is not None else None)
            net_result = ((position.realized_usd or Decimal("0")) + unrealized - fees
                          if unrealized is not None else None)
            items.append(LifecycleSummary(
                lifecycle_id=lifecycle.id, symbol=lifecycle.symbol, status="open",
                opened_at=lifecycle.opened_at, last_changed_at=trades[-1].timestamp,
                quantity=position.quantity, exposure_usd=exposure, invested_usd=invested,
                fees_usd=fees, net_result_usd=net_result,
                net_result_pct=(net_result / invested * Decimal("100")
                                if net_result is not None and invested else None),
            ))
        else:
            items.append(LifecycleSummary(
                lifecycle_id=lifecycle.id, symbol=lifecycle.symbol, status="closed",
                opened_at=lifecycle.opened_at, closed_at=lifecycle.closed_at,
                last_changed_at=trades[-1].timestamp,
                held_minutes=max(0, int((_utc(lifecycle.closed_at) - _utc(lifecycle.opened_at)).total_seconds() // 60)),
                invested_usd=invested, fees_usd=fees, net_result_usd=closed_net,
                net_result_pct=(closed_net / invested * Decimal("100") if invested else None),
            ))

    items.sort(key=lambda row: _lifecycle_sort_key(state, row), reverse=True)

    current_equity = agent.cash_usd + sum(
        (row.exposure_usd for row in items if row.status == "open" and row.exposure_usd is not None),
        Decimal("0"),
    )
    if current_equity:
        items = [
            row.model_copy(update={
                "portfolio_weight_pct": row.exposure_usd / current_equity * Decimal("100")
            }) if row.status == "open" and row.exposure_usd is not None else row
            for row in items
        ]
    if cursor_payload is not None and state == "closed":
        cursor_key = _lifecycle_cursor_key(state, cursor_payload["key"])
        items = [row for row in items if _lifecycle_sort_key(state, row) < cursor_key]
    if cursor_payload is not None and state in ("open", "all"):
        by_id = {row.lifecycle_id: row for row in items}
        items = [by_id[lifecycle_id] for lifecycle_id in cursor_payload["remaining_ids"]
                 if lifecycle_id in by_id]
    page = items[:limit]
    remaining_ids = [row.lifecycle_id for row in items[limit:]] if state in ("open", "all") else None
    next_cursor = (
        _encode_lifecycle_cursor(
            agent_id, state, threshold, _lifecycle_sort_key(state, page[-1]), remaining_ids,
        )
        if len(items) > limit else None
    )
    return LifecycleCollectionOut(items=page, next_cursor=next_cursor)


@router.get("/agents/{agent_id}/equity", response_model=list[EquityPoint])
def get_equity(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = (
        session.query(EquitySnapshot)
        .filter_by(agent_id=agent_id)
        .order_by(EquitySnapshot.timestamp.asc())
        .all()
    )
    return rows


@router.get("/agents/{agent_id}/benchmarks", response_model=list[BenchmarkPoint])
def get_benchmarks(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return (
        session.query(BenchmarkSnapshot)
        .filter_by(agent_id=agent_id)
        .order_by(BenchmarkSnapshot.timestamp.asc(), BenchmarkSnapshot.id.asc())
        .all()
    )


@router.get("/agents/{agent_id}/metrics", response_model=AgentMetricsOut)
def get_agent_metrics(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    eq = [r.equity_usd for r in
          session.query(EquitySnapshot).filter_by(agent_id=agent_id)
          .order_by(EquitySnapshot.timestamp.asc(), EquitySnapshot.id.asc()).all()]
    benchmarks: dict[str, BenchmarkMetric] = {}
    for kind in ("hodl_btc", "equal_weight", "random_p50"):
        series = [r.equity_usd for r in
                  session.query(BenchmarkSnapshot).filter_by(agent_id=agent_id, kind=kind)
                  .order_by(BenchmarkSnapshot.timestamp.asc(), BenchmarkSnapshot.id.asc()).all()]
        if series:
            benchmarks[kind] = BenchmarkMetric(
                return_pct=total_return_pct(series),
                max_drawdown_pct=max_drawdown_pct(series),
                sharpe=sharpe(series))

    def _hit_rate(window: str):
        rows = (session.query(DecisionScore)
                .join(DecisionRecord, DecisionScore.decision_record_id == DecisionRecord.id)
                .filter(DecisionRecord.agent_id == agent_id, DecisionScore.window == window).all())
        return hit_rate(sum(r.n_hits for r in rows), sum(r.n_actions for r in rows))

    return AgentMetricsOut(
        return_pct=total_return_pct(eq),
        max_drawdown_pct=max_drawdown_pct(eq),
        sharpe=sharpe(eq),
        hit_rates=[WindowHitRate(window=w, hit_rate=_hit_rate(w))
                   for w in settings.scoring_windows],
        benchmarks=benchmarks)


@router.get("/metrics/by-model", response_model=list[ModelMetricsOut])
def get_model_metrics(session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = (session.query(DecisionRecord.model_name, DecisionScore.window,
                          DecisionScore.n_hits, DecisionScore.n_actions)
            .join(DecisionScore, DecisionScore.decision_record_id == DecisionRecord.id)
            .filter(DecisionRecord.kind == "decision").all())
    labels = list(settings.scoring_windows)
    agg: dict = {}
    for model_name, window, nh, na in rows:
        d = agg.setdefault(model_name, {w: [0, 0] for w in labels})
        if window in d:                    # righe con label di config precedenti: ignorate
            d[window][0] += nh
            d[window][1] += na
    return [
        ModelMetricsOut(
            model_name=model_name,
            n_scored_actions=sum(v[1] for v in d.values()),
            hit_rates=[WindowHitRate(window=w, hit_rate=hit_rate(*d[w])) for w in labels])
        for model_name, d in agg.items()
    ]


@router.get("/agents/{agent_id}/trades", response_model=list[TradeOut])
def get_trades(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return (
        session.query(Trade)
        .filter_by(agent_id=agent_id)
        .order_by(Trade.timestamp.desc(), Trade.id.desc())
        .limit(100)
        .all()
    )


@router.get("/agents/{agent_id}/memory", response_model=MemoryOut)
def get_memory(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    from app.brain.journal import SECTION_CAPS, compact_view, policy_view
    view = compact_view(session, agent_id)
    policy = policy_view(session, agent_id)
    return MemoryOut(coin_theses=view.coin_theses, trade_lessons=view.trade_lessons,
                     strategy_notes=view.strategy_notes,
                     self_policy=[PolicyLineOut(ref=line.ref, content=line.content)
                                  for line in policy.active],
                     caps=dict(SECTION_CAPS))


@router.get("/agents/{agent_id}/memory/journal", response_model=list[MemoryEntryOut])
def get_memory_journal(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return (
        session.query(MemoryEntry)
        .filter_by(agent_id=agent_id)
        .order_by(MemoryEntry.created_at.desc(), MemoryEntry.id.desc())
        .limit(100)
        .all()
    )


@router.get("/agents/{agent_id}/events", response_model=list[EventOut])
def get_events(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return (
        session.query(Event)
        .filter_by(agent_id=agent_id)
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(100)
        .all()
    )


@router.get("/observations", response_model=list[ObservationOut])
def get_observations(session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = (session.query(Observation)
            .order_by(Observation.published_at.desc(), Observation.id.desc())
            .limit(100).all())
    return [ObservationOut(source=o.source, title=o.title, url=o.url,
                           published_at=o.published_at, symbols=json.loads(o.symbols_json))
            for o in rows]


@router.get("/agents/{agent_id}/decisions", response_model=list[DecisionRecordOut])
def get_decisions(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return (
        session.query(DecisionRecord)
        .filter_by(agent_id=agent_id)
        .order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
        .limit(100)
        .all()
    )


@router.get("/agents/{agent_id}/brief", response_model=MarketBriefOut | None)
async def get_brief(agent_id: int, session=Depends(session_dep),
                    market=Depends(market_dep), _: str = Depends(require_viewer_or_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    row = latest_valid_brief(session)
    if row is None:
        return None
    try:
        symbols = await market.get_top_symbols("USDT", universe_size(agent))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"brief unavailable: {exc}")
    view = filter_brief_for(row, symbols)
    return MarketBriefOut(
        regime=view.regime,
        highlights=[HighlightOut(symbol=h.symbol, snapshot=h.snapshot, signal=h.signal, note=h.note)
                    for h in view.highlights],
        key_news=view.key_news,
        as_of=view.as_of)


@router.get("/agents/{agent_id}/prompt", response_model=PromptPreviewOut)
async def get_prompt(agent_id: int, session=Depends(session_dep),
                     market=Depends(market_dep), _: str = Depends(require_viewer_or_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    try:
        return await render_agent_prompts_preview(session, agent, market)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"prompt preview unavailable: {exc}")

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.config import settings
from app.api.auth import session_dep, require_admin, require_viewer_or_admin
from app.db.models import Agent, BenchmarkBasis, BenchmarkSnapshot, DecisionRecord, DecisionScore, EquitySnapshot, Event, MemoryEntry, Position, Trade
from app.api.schemas import AgentCreate, AgentMetricsOut, AgentOut, AgentUpdate, BenchmarkMetric, BenchmarkPoint, DecisionRecordOut, EquityPoint, EventOut, MemoryEntryOut, MemoryOut, ModelMetricsOut, PositionOut, PromptPreviewOut
from app.market.binance import BinanceClient
from app.agents.preview import render_agent_prompts_preview
from app.eval.metrics import total_return_pct, max_drawdown_pct, sharpe, hit_rate

router = APIRouter(prefix="/api")


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


def _agent_out(session, agent: Agent) -> AgentOut:
    equity = _latest_equity(session, agent)
    initial = settings.initial_capital_usd
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
        brain_version=agent.brain_version,
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
        universe=payload.universe,
        brain_version=payload.brain_version,
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
    for model in (Position, Trade, EquitySnapshot, Event, MemoryEntry, DecisionRecord,
                  BenchmarkBasis, BenchmarkSnapshot):
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
        except Exception:
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
        ))
    return out


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
        hit_rate_24h=_hit_rate("24h"),
        hit_rate_7d=_hit_rate("7d"),
        benchmarks=benchmarks)


@router.get("/metrics/by-model", response_model=list[ModelMetricsOut])
def get_model_metrics(session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = (session.query(DecisionRecord.model_name, DecisionScore.window,
                          DecisionScore.n_hits, DecisionScore.n_actions)
            .join(DecisionScore, DecisionScore.decision_record_id == DecisionRecord.id)
            .filter(DecisionRecord.kind == "decision").all())
    agg: dict = {}
    for model_name, window, nh, na in rows:
        d = agg.setdefault(model_name, {"24h": [0, 0], "7d": [0, 0]})
        d[window][0] += nh
        d[window][1] += na
    return [
        ModelMetricsOut(
            model_name=model_name,
            n_scored_actions=d["24h"][1] + d["7d"][1],
            hit_rate_24h=hit_rate(*d["24h"]),
            hit_rate_7d=hit_rate(*d["7d"]))
        for model_name, d in agg.items()
    ]


@router.get("/agents/{agent_id}/memory", response_model=MemoryOut)
def get_memory(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    from app.brain.journal import compact_view
    view = compact_view(session, agent_id)
    return MemoryOut(coin_theses=view.coin_theses, trade_lessons=view.trade_lessons,
                     strategy_notes=view.strategy_notes)


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


@router.get("/agents/{agent_id}/decisions", response_model=list[DecisionRecordOut])
def get_decisions(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return (
        session.query(DecisionRecord)
        .filter_by(agent_id=agent_id)
        .order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
        .limit(100)
        .all()
    )


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

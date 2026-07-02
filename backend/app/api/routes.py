from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.config import settings
from app.api.auth import session_dep, require_admin, require_viewer_or_admin
from app.db.models import Agent, AgentMemory, EquitySnapshot, Event, Position, Trade
from app.api.schemas import AgentCreate, AgentOut, AgentUpdate, EquityPoint, EventOut, MemoryOut, PositionOut, PromptPreviewOut
from app.market.binance import BinanceClient
from app.agents.preview import render_agent_prompts_preview

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
    for model in (Position, Trade, EquitySnapshot, Event, AgentMemory):
        session.query(model).filter_by(agent_id=agent_id).delete(synchronize_session=False)
    session.delete(agent)
    session.commit()


@router.get("/agents/{agent_id}/positions", response_model=list[PositionOut])
def get_positions(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = session.query(Position).filter_by(agent_id=agent_id).all()
    return [
        PositionOut(
            symbol=p.symbol,
            quantity=p.quantity,
            avg_price=p.avg_price,
            cost_basis=p.quantity * p.avg_price,
        )
        for p in rows
    ]


@router.get("/agents/{agent_id}/equity", response_model=list[EquityPoint])
def get_equity(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = (
        session.query(EquitySnapshot)
        .filter_by(agent_id=agent_id)
        .order_by(EquitySnapshot.timestamp.asc())
        .all()
    )
    return rows


@router.get("/agents/{agent_id}/memory", response_model=MemoryOut)
def get_memory(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = {r.section: r.content for r in
            session.query(AgentMemory).filter_by(agent_id=agent_id).all()}
    return MemoryOut(
        coin_theses=rows.get("coin_theses", ""),
        trade_lessons=rows.get("trade_lessons", ""),
        strategy_notes=rows.get("strategy_notes", ""),
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

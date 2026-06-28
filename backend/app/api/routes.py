from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import Agent, AgentMemory, EquitySnapshot, Event, Position
from app.api.schemas import AgentCreate, AgentOut, EquityPoint, EventOut, MemoryOut, PositionOut

router = APIRouter(prefix="/api")


def session_dep():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _latest_equity(session, agent: Agent) -> Decimal:
    snap = (
        session.query(EquitySnapshot)
        .filter_by(agent_id=agent.id)
        .order_by(EquitySnapshot.timestamp.desc())
        .first()
    )
    return snap.equity_usd if snap else agent.cash_usd


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
def create_agent(payload: AgentCreate, session=Depends(session_dep)):
    now = datetime.now(timezone.utc)
    agent = Agent(
        name=payload.name,
        instructions=payload.instructions,
        duration_start=now,
        duration_end=now + timedelta(days=payload.duration_days),
        cash_usd=settings.initial_capital_usd,
        universe=settings.universe_default,
        strategy=payload.strategy,
        model_provider=payload.model_provider,
        model_name=payload.model_name,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return _agent_out(session, agent)


@router.get("/agents", response_model=list[AgentOut])
def list_agents(session=Depends(session_dep)):
    return [_agent_out(session, a) for a in session.query(Agent).all()]


@router.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, session=Depends(session_dep)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    return _agent_out(session, agent)


@router.get("/agents/{agent_id}/positions", response_model=list[PositionOut])
def get_positions(agent_id: int, session=Depends(session_dep)):
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
def get_equity(agent_id: int, session=Depends(session_dep)):
    rows = (
        session.query(EquitySnapshot)
        .filter_by(agent_id=agent_id)
        .order_by(EquitySnapshot.timestamp.asc())
        .all()
    )
    return rows


@router.get("/agents/{agent_id}/memory", response_model=MemoryOut)
def get_memory(agent_id: int, session=Depends(session_dep)):
    rows = {r.section: r.content for r in
            session.query(AgentMemory).filter_by(agent_id=agent_id).all()}
    return MemoryOut(
        coin_theses=rows.get("coin_theses", ""),
        trade_lessons=rows.get("trade_lessons", ""),
        strategy_notes=rows.get("strategy_notes", ""),
    )


@router.get("/agents/{agent_id}/events", response_model=list[EventOut])
def get_events(agent_id: int, session=Depends(session_dep)):
    return (
        session.query(Event)
        .filter_by(agent_id=agent_id)
        .order_by(Event.timestamp.desc())
        .limit(100)
        .all()
    )

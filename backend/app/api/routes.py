from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import Agent, EquitySnapshot, Event
from app.api.schemas import AgentCreate, AgentOut, EquityPoint, EventOut

router = APIRouter(prefix="/api")


def session_dep():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


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
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


@router.get("/agents", response_model=list[AgentOut])
def list_agents(session=Depends(session_dep)):
    return session.query(Agent).all()


@router.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, session=Depends(session_dep)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    return agent


@router.get("/agents/{agent_id}/equity", response_model=list[EquityPoint])
def get_equity(agent_id: int, session=Depends(session_dep)):
    rows = (
        session.query(EquitySnapshot)
        .filter_by(agent_id=agent_id)
        .order_by(EquitySnapshot.timestamp.asc())
        .all()
    )
    return rows


@router.get("/agents/{agent_id}/events", response_model=list[EventOut])
def get_events(agent_id: int, session=Depends(session_dep)):
    return (
        session.query(Event)
        .filter_by(agent_id=agent_id)
        .order_by(Event.timestamp.desc())
        .limit(100)
        .all()
    )

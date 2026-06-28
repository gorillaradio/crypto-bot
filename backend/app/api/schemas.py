from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class AgentCreate(BaseModel):
    name: str
    instructions: str = ""
    duration_days: int = 7
    strategy: str = "llm"
    model_provider: str | None = None
    model_name: str | None = None


class AgentOut(BaseModel):
    id: int
    name: str
    instructions: str
    status: str
    cash_usd: Decimal
    equity: Decimal
    return_pct: Decimal
    duration_start: datetime
    duration_end: datetime


class PositionOut(BaseModel):
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal


class EquityPoint(BaseModel):
    timestamp: datetime
    equity_usd: Decimal


class EventOut(BaseModel):
    timestamp: datetime
    kind: str
    message: str

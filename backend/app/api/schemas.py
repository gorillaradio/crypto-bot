from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str
    instructions: str = ""
    duration_days: int = 7
    model_provider: Literal["anthropic", "deepseek", "glm", "openrouter"]
    model_name: str = Field(min_length=1)
    universe: Literal["TOP_50", "TOP_100"] = "TOP_100"


class AgentUpdate(BaseModel):
    name: str


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
    cycle_id: str | None = None


class MemoryOut(BaseModel):
    coin_theses: str
    trade_lessons: str
    strategy_notes: str

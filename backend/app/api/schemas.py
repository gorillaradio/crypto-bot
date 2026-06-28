from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict


class AgentCreate(BaseModel):
    name: str
    instructions: str = ""
    duration_days: int = 7


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    instructions: str
    status: str
    cash_usd: Decimal


class EquityPoint(BaseModel):
    timestamp: datetime
    equity_usd: Decimal


class EventOut(BaseModel):
    timestamp: datetime
    kind: str
    message: str

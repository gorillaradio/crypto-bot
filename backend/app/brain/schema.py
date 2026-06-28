from decimal import Decimal
from typing import Literal
from pydantic import BaseModel


class Action(BaseModel):
    type: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = None
    usd_amount: Decimal | None = None
    fraction: Decimal | None = None
    rationale: str = ""


class Decision(BaseModel):
    actions: list[Action] = []
    note: str = ""

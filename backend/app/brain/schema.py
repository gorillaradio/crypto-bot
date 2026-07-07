from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class Action(BaseModel):
    type: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = None
    usd_amount: Decimal | None = None
    fraction: Decimal | None = None
    rationale: str = ""
    policy_refs: list[str] = Field(default_factory=list)
    policy_alignment: Literal["follows", "violates", "unrelated"] = "unrelated"
    override_reason: str = ""


class Decision(BaseModel):
    actions: list[Action] = []
    note: str = ""


@dataclass
class DecisionResult:
    decision: Decision
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "repaired" | "failed"
    latency_ms: int = 0

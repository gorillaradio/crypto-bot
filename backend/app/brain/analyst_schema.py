from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel


class Highlight(BaseModel):
    symbol: str
    snapshot: str = ""
    signal: Literal["bullish", "bearish", "neutral"] = "neutral"
    note: str = ""


class MarketBriefSchema(BaseModel):
    regime: str = ""
    highlights: list[Highlight] = []
    key_news: list[str] = []


@dataclass
class AnalystResult:
    brief: MarketBriefSchema
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "repaired" | "failed"
    latency_ms: int = 0

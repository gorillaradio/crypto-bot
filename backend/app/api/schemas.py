from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str
    instructions: str = ""
    duration_days: int = 7
    model_name: str = Field(min_length=1)
    universe: Literal["TOP_50", "TOP_100"] = "TOP_100"
    brain_version: Literal["v1", "v2"] = "v1"
    stop_loss: Decimal | None = Field(default=None, gt=0, lt=1)
    take_profit: Decimal | None = Field(default=None, gt=0, le=5)


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
    brain_version: str


class PositionOut(BaseModel):
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    last_price: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
    market_value: Decimal | None = None


class EquityPoint(BaseModel):
    timestamp: datetime
    equity_usd: Decimal


class BenchmarkPoint(BaseModel):
    kind: str
    timestamp: datetime
    equity_usd: Decimal


class BenchmarkMetric(BaseModel):
    return_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe: Decimal


class AgentMetricsOut(BaseModel):
    return_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe: Decimal
    hit_rate_24h: Decimal | None = None
    hit_rate_7d: Decimal | None = None
    benchmarks: dict[str, BenchmarkMetric]


class ModelMetricsOut(BaseModel):
    model_name: str | None = None
    n_scored_actions: int
    hit_rate_24h: Decimal | None = None
    hit_rate_7d: Decimal | None = None


class EventOut(BaseModel):
    timestamp: datetime
    kind: str
    message: str
    cycle_id: str | None = None


class ObservationOut(BaseModel):
    source: str
    title: str
    url: str | None = None
    published_at: datetime
    symbols: list[str]


class DecisionRecordOut(BaseModel):
    id: int
    cycle_id: str
    kind: str
    trigger: str
    system_prompt: str
    user_prompt: str
    raw_response: str | None = None
    parsed_output: str | None = None
    parse_status: str
    model_provider: str
    model_name: str | None = None
    latency_ms: int
    created_at: datetime


class MemoryOut(BaseModel):
    coin_theses: str
    trade_lessons: str
    strategy_notes: str


class MemoryEntryOut(BaseModel):
    section: str
    content: str
    cycle_id: str | None = None
    active: bool
    created_at: datetime


class PromptPair(BaseModel):
    system: str
    user: str
    note: str | None = None


class PromptPreviewOut(BaseModel):
    decision: PromptPair
    reflection: PromptPair
    retry: PromptPair


class LoginIn(BaseModel):
    password: str


class ViewerIn(BaseModel):
    token: str


class MeOut(BaseModel):
    role: str | None = None


class ShareLinkIn(BaseModel):
    label: str | None = None


class ShareLinkOut(BaseModel):
    id: int
    label: str | None
    token: str
    url: str
    created_at: datetime


class HighlightOut(BaseModel):
    symbol: str
    snapshot: str
    signal: str
    note: str


class MarketBriefOut(BaseModel):
    regime: str
    highlights: list[HighlightOut]
    key_news: list[str]
    as_of: datetime | None = None

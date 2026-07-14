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
    decision_seconds: int


class PositionOut(BaseModel):
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    last_price: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
    market_value: Decimal | None = None
    opened_at: datetime | None = None
    realized_usd: Decimal = Decimal("0")


class LifecycleEvaluationOut(BaseModel):
    action: str
    rationale: str | None = None
    cycle_id: str | None = None
    timestamp: datetime


class OpenLifecycleOut(BaseModel):
    lifecycle_id: str
    cycle_id: str | None = None
    symbol: str
    status: Literal["open"] = "open"
    opened_at: datetime
    last_changed_at: datetime
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    last_price: Decimal | None = None
    exposure_usd: Decimal | None = None
    fees_usd: Decimal
    realized_usd: Decimal
    unrealized_usd: Decimal | None = None
    net_result_usd: Decimal | None = None
    net_result_pct: Decimal | None = None
    evaluation: LifecycleEvaluationOut | None = None


class LifecycleMarketOut(BaseModel):
    status: Literal["fresh", "stale", "unavailable"]
    as_of: datetime | None = None


class LifecycleSummary(BaseModel):
    lifecycle_id: str
    symbol: str
    status: Literal["open", "closed"]
    opened_at: datetime
    closed_at: datetime | None = None
    last_changed_at: datetime
    quantity: Decimal | None = None
    exposure_usd: Decimal | None = None
    portfolio_weight_pct: Decimal | None = None
    held_minutes: int | None = None
    invested_usd: Decimal
    fees_usd: Decimal
    net_result_usd: Decimal | None = None
    net_result_pct: Decimal | None = None
    market_series_24h: list[Decimal] | None = None


class LifecycleCollectionOut(BaseModel):
    items: list[LifecycleSummary]
    next_cursor: str | None = None
    market: LifecycleMarketOut


class ClosedPositionOut(BaseModel):
    symbol: str
    opened_at: datetime | None = None
    closed_at: datetime
    held_minutes: int | None = None
    invested_usd: Decimal | None = None
    realized_total_usd: Decimal
    realized_total_pct: Decimal | None = None
    close_cycle_id: str | None = None


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


class WindowHitRate(BaseModel):
    window: str                          # label della finestra (settings.scoring_windows, es. "24h")
    hit_rate: Decimal | None = None


class AgentMetricsOut(BaseModel):
    return_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe: Decimal
    hit_rates: list[WindowHitRate]       # in ordine short→long
    benchmarks: dict[str, BenchmarkMetric]


class ModelMetricsOut(BaseModel):
    model_name: str | None = None
    n_scored_actions: int
    hit_rates: list[WindowHitRate]       # in ordine short→long


class EventOut(BaseModel):
    timestamp: datetime
    kind: str
    message: str
    payload: dict | None = None
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


class TradeOut(BaseModel):
    id: int
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    timestamp: datetime


class PolicyLineOut(BaseModel):
    ref: str
    content: str


class MemoryOut(BaseModel):
    coin_theses: str
    trade_lessons: str
    strategy_notes: str
    self_policy: list[PolicyLineOut] = []
    caps: dict[str, int] = {}


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

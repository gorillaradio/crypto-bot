from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class PositionView:
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    last_price: Decimal
    unrealized_pnl_pct: Decimal


@dataclass
class CoinSnapshot:
    symbol: str
    price: Decimal
    pct_24h: Decimal


@dataclass
class MemoryView:
    coin_theses: str = ""
    trade_lessons: str = ""
    strategy_notes: str = ""


@dataclass
class PolicyLine:
    ref: str
    content: str


@dataclass
class PolicyMemoryView:
    active: list[PolicyLine] = field(default_factory=list)


@dataclass
class ObservationView:
    source: str
    title: str
    published_at: datetime
    symbols: list[str]


@dataclass
class HighlightView:
    symbol: str
    snapshot: str = ""
    signal: str = "neutral"
    note: str = ""


@dataclass
class MarketBriefView:
    regime: str = ""
    highlights: list[HighlightView] = field(default_factory=list)
    key_news: list[str] = field(default_factory=list)
    as_of: datetime | None = None


@dataclass
class DecisionContext:
    instructions: str
    cash_usd: Decimal
    equity_usd: Decimal
    positions: list[PositionView]
    recent_events: list[str]
    memory: MemoryView
    wake_reason: str | None = None
    brief: "MarketBriefView | None" = None


def build_context(*, instructions, cash_usd, holdings, recent_events, memory=None, brief=None, wake_reason=None) -> DecisionContext:
    positions: list[PositionView] = []
    equity = cash_usd
    for symbol, quantity, avg_price, last_price in holdings:
        pnl = ((last_price - avg_price) / avg_price * Decimal("100")) if avg_price else Decimal("0")
        positions.append(PositionView(symbol, quantity, avg_price, last_price, pnl))
        equity += quantity * last_price
    return DecisionContext(
        instructions=instructions, cash_usd=cash_usd, equity_usd=equity,
        positions=positions, recent_events=recent_events,
        memory=memory or MemoryView(), brief=brief, wake_reason=wake_reason,
    )

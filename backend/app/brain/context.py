from dataclasses import dataclass
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
class DecisionContext:
    instructions: str
    cash_usd: Decimal
    equity_usd: Decimal
    positions: list[PositionView]
    universe: list[CoinSnapshot]
    recent_events: list[str]
    memory: MemoryView
    wake_reason: str | None = None


def build_context(*, instructions, cash_usd, holdings, universe, recent_events, memory=None, wake_reason=None) -> DecisionContext:
    positions: list[PositionView] = []
    equity = cash_usd
    for symbol, quantity, avg_price, last_price in holdings:
        pnl = ((last_price - avg_price) / avg_price * Decimal("100")) if avg_price else Decimal("0")
        positions.append(PositionView(symbol, quantity, avg_price, last_price, pnl))
        equity += quantity * last_price
    return DecisionContext(
        instructions=instructions, cash_usd=cash_usd, equity_usd=equity,
        positions=positions, universe=universe, recent_events=recent_events,
        memory=memory or MemoryView(), wake_reason=wake_reason,
    )

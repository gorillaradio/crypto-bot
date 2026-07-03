from decimal import Decimal
from app.brain.context import build_context, CoinSnapshot


def test_build_context_carries_memory():
    from app.brain.context import MemoryView
    mem = MemoryView(coin_theses="BTC: bull", trade_lessons="sold too early")
    ctx = build_context(
        instructions="x", cash_usd=Decimal("10"), holdings=[],
        universe=[], recent_events=[], memory=mem,
    )
    assert ctx.memory.coin_theses == "BTC: bull"
    assert ctx.memory.strategy_notes == ""        # default empty section

def test_build_context_defaults_memory_empty():
    ctx = build_context(instructions="x", cash_usd=Decimal("10"),
                        holdings=[], universe=[], recent_events=[])
    assert ctx.memory.coin_theses == ""


def test_build_context_computes_equity_and_pnl():
    ctx = build_context(
        instructions="be bold",
        cash_usd=Decimal("50"),
        holdings=[("BTCUSDT", Decimal("0.5"), Decimal("100"), Decimal("120"))],
        universe=[CoinSnapshot(symbol="BTCUSDT", price=Decimal("120"), pct_24h=Decimal("3.5"))],
        recent_events=["BUY 0.5 BTCUSDT"],
    )
    assert ctx.instructions == "be bold"
    assert ctx.equity_usd == Decimal("110")          # 50 + 0.5*120
    assert ctx.positions[0].unrealized_pnl_pct == Decimal("20")  # (120-100)/100*100
    assert ctx.universe[0].symbol == "BTCUSDT"
    assert ctx.recent_events == ["BUY 0.5 BTCUSDT"]


def test_build_context_carries_wake_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[], wake_reason="SOLUSDT -12%")
    assert ctx.wake_reason == "SOLUSDT -12%"


def test_build_context_wake_reason_defaults_none():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[])
    assert ctx.wake_reason is None


def test_build_context_carries_observations():
    from datetime import datetime, timezone
    from app.brain.context import ObservationView
    obs = [ObservationView(source="CoinDesk", title="Bitcoin ETF inflows",
                           published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
                           symbols=["BTC"])]
    ctx = build_context(instructions="x", cash_usd=Decimal("10"), holdings=[],
                        universe=[], recent_events=[], observations=obs)
    assert ctx.observations[0].title == "Bitcoin ETF inflows"
    assert ctx.observations[0].symbols == ["BTC"]


def test_build_context_defaults_observations_empty():
    ctx = build_context(instructions="x", cash_usd=Decimal("10"),
                        holdings=[], universe=[], recent_events=[])
    assert ctx.observations == []

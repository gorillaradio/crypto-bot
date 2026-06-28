from decimal import Decimal
from app.brain.context import build_context, CoinSnapshot


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

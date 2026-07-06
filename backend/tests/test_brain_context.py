from decimal import Decimal
from app.brain.context import build_context


def test_build_context_carries_memory():
    from app.brain.context import MemoryView
    mem = MemoryView(coin_theses="BTC: bull", trade_lessons="sold too early")
    ctx = build_context(
        instructions="x", cash_usd=Decimal("10"), holdings=[],
        recent_events=[], memory=mem,
    )
    assert ctx.memory.coin_theses == "BTC: bull"
    assert ctx.memory.strategy_notes == ""        # default empty section

def test_build_context_defaults_memory_empty():
    ctx = build_context(instructions="x", cash_usd=Decimal("10"),
                        holdings=[], recent_events=[])
    assert ctx.memory.coin_theses == ""


def test_build_context_carries_policy_view():
    from app.brain.context import PolicyLine, PolicyMemoryView

    policy = PolicyMemoryView(active=[PolicyLine("P10", "Wait for fresh evidence.")])
    ctx = build_context(instructions="", cash_usd=Decimal("100"),
                        holdings=[], recent_events=[], policy=policy)

    assert ctx.policy.active[0].ref == "P10"
    assert ctx.policy.active[0].content == "Wait for fresh evidence."


def test_build_context_computes_equity_and_pnl():
    ctx = build_context(
        instructions="be bold",
        cash_usd=Decimal("50"),
        holdings=[("BTCUSDT", Decimal("0.5"), Decimal("100"), Decimal("120"))],
        recent_events=["BUY 0.5 BTCUSDT"],
    )
    assert ctx.instructions == "be bold"
    assert ctx.equity_usd == Decimal("110")          # 50 + 0.5*120
    assert ctx.positions[0].unrealized_pnl_pct == Decimal("20")  # (120-100)/100*100
    assert ctx.recent_events == ["BUY 0.5 BTCUSDT"]


def test_build_context_carries_wake_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        recent_events=[], wake_reason="SOLUSDT -12%")
    assert ctx.wake_reason == "SOLUSDT -12%"


def test_build_context_wake_reason_defaults_none():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        recent_events=[])
    assert ctx.wake_reason is None


def test_build_context_accepts_brief():
    from app.brain.context import build_context, MarketBriefView, HighlightView
    brief = MarketBriefView(regime="risk-on",
                            highlights=[HighlightView("BTCUSDT", "$60000", "bullish", "etf")])
    ctx = build_context(instructions="x", cash_usd=Decimal("100"), holdings=[],
                        recent_events=[], brief=brief)
    assert ctx.brief.regime == "risk-on" and ctx.brief.highlights[0].symbol == "BTCUSDT"


def test_build_context_brief_defaults_none():
    ctx = build_context(instructions="x", cash_usd=Decimal("100"), holdings=[],
                        recent_events=[])
    assert ctx.brief is None

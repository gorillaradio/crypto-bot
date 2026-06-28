from decimal import Decimal
from app.brain.context import build_context, CoinSnapshot
from app.brain.prompt import render_prompt


def _ctx():
    return build_context(
        instructions="favor blue chips",
        cash_usd=Decimal("100"),
        holdings=[],
        universe=[CoinSnapshot("ETHUSDT", Decimal("3000"), Decimal("-1")),
                  CoinSnapshot("BTCUSDT", Decimal("60000"), Decimal("2"))],
        recent_events=["decision: 0 ops"],
    )


def test_prompt_includes_instructions_rules_and_format():
    system, user = render_prompt(_ctx())
    assert "favor blue chips" in system
    assert "JSON" in system and '"actions"' in system   # output format described
    assert "cash" in user.lower()


def test_universe_rendered_sorted_and_deterministic():
    system1, user1 = render_prompt(_ctx())
    system2, user2 = render_prompt(_ctx())
    assert user1 == user2                                # deterministic
    assert user1.index("BTCUSDT") < user1.index("ETHUSDT")  # sorted by symbol

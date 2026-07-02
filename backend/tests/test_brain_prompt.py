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


def test_prompt_includes_memory_when_present():
    from app.brain.context import MemoryView
    ctx = build_context(
        instructions="x", cash_usd=Decimal("100"), holdings=[], universe=[],
        recent_events=[], memory=MemoryView(coin_theses="BTC: accumulate", strategy_notes="I FOMO on pumps"),
    )
    system, user = render_prompt(ctx)
    assert "BTC: accumulate" in user
    assert "I FOMO on pumps" in user
    assert "Trade lessons:" not in user        # empty section omitted
    assert "prior reflection" in system        # memory hint present when memory is non-empty

def test_prompt_omits_memory_block_when_empty():
    system, user = render_prompt(_ctx())       # _ctx() has no memory
    assert "Your memory" not in user
    assert "prior reflection" not in system    # memory hint absent when memory is empty


def test_render_prompt_surfaces_wake_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[],
                        wake_reason="SOLUSDT a -12.30%, oltre la tua soglia di stop")
    _system, user = render_prompt(ctx)
    assert "SOLUSDT a -12.30%, oltre la tua soglia di stop" in user


def test_render_prompt_no_wake_marker_when_none():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[])
    _system, user = render_prompt(ctx)
    assert "⚠" not in user


def test_retry_user_suffix_contains_schema_and_correction_ask():
    from app.brain.prompt import retry_user_suffix
    s = retry_user_suffix("boom")
    assert "boom" in s
    assert "not valid JSON" in s
    assert "corrected JSON" in s

from decimal import Decimal
from app.brain.context import MemoryView
from app.brain.memory import (
    ClosedTrade, MemoryUpdate, build_reflection_prompt, parse_reflection,
    enforce_caps, run_reflection, run_reflection_result, ReflectionResult,
    CAP_COIN_THESES, CAP_TRADE_LESSONS, CAP_STRATEGY_NOTES,
)


def test_enforce_caps_truncates_and_joins():
    update = MemoryUpdate(
        coin_theses=[f"C{i}" for i in range(9)],     # 9 -> 8
        trade_lessons=[f"L{i}" for i in range(11)],  # 11 -> 10
        strategy_notes=[f"N{i}" for i in range(6)],  # 6 -> 5
    )
    mem = enforce_caps(update)
    assert len(mem.coin_theses.splitlines()) == CAP_COIN_THESES
    assert len(mem.trade_lessons.splitlines()) == CAP_TRADE_LESSONS
    assert len(mem.strategy_notes.splitlines()) == CAP_STRATEGY_NOTES
    assert mem.coin_theses.splitlines()[0] == "C0"   # keeps the first N


def test_parse_reflection_reads_json():
    raw = '{"coin_theses": ["BTC: bull"], "trade_lessons": [], "strategy_notes": ["patient"]}'
    update = parse_reflection(raw)
    assert update.coin_theses == ["BTC: bull"]
    assert update.strategy_notes == ["patient"]


def test_build_reflection_prompt_mentions_outcome_and_memory():
    mem = MemoryView(coin_theses="BTC: old view")
    closed = [ClosedTrade("BTCUSDT", Decimal("1"), Decimal("120"), Decimal("100"), Decimal("20"))]
    system, user = build_reflection_prompt(mem, closed, ["ETHUSDT"], "be bold")
    assert "JSON" in system and "be bold" in system
    assert "BTCUSDT" in user and "+20.00%" in user
    assert "BTC: old view" in user            # current memory shown for rewrite


def test_run_reflection_uses_adapter_and_caps():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"coin_theses": ["BTC: bull", "ETH: flat"], "trade_lessons": ["sold too early"], "strategy_notes": []}'
    mem = run_reflection(MemoryView(), [], [], "x", FakeAdapter())
    assert mem.coin_theses == "BTC: bull\nETH: flat"
    assert mem.trade_lessons == "sold too early"
    assert mem.strategy_notes == ""


def test_run_reflection_result_ok_captures_trace():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"coin_theses": ["BTC: bull"], "trade_lessons": [], "strategy_notes": []}'
    r = run_reflection_result(MemoryView(), [], [], "x", FakeAdapter())
    assert r.parse_status == "ok"
    assert r.memory.coin_theses == "BTC: bull"
    assert r.raw and r.system and r.user
    assert r.latency_ms >= 0


def test_run_reflection_result_parse_failure_keeps_memory():
    class FakeAdapter:
        def complete_json(self, system, user): return "not json"
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.memory.coin_theses == "keep me"      # unchanged on failure
    assert r.raw == "not json"


def test_run_reflection_result_provider_error_is_failed():
    class FakeAdapter:
        def complete_json(self, system, user): raise RuntimeError("down")
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.raw is None
    assert r.memory.coin_theses == "keep me"

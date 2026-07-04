from decimal import Decimal
from app.brain.context import MemoryView
from app.brain.memory import (
    ClosedTrade, MemoryUpdate, build_reflection_prompt, parse_reflection,
    run_reflection_result, ReflectionResult,
)


def test_parse_reflection_reads_json():
    raw = '{"coin_theses": ["BTC: bull"], "trade_lessons": [], "strategy_notes": ["patient"]}'
    update = parse_reflection(raw)
    assert update.coin_theses == ["BTC: bull"]
    assert update.strategy_notes == ["patient"]


def test_build_reflection_prompt_asks_for_new_entries_and_shows_memory():
    mem = MemoryView(coin_theses="BTC: old view")
    closed = [ClosedTrade("BTCUSDT", Decimal("1"), Decimal("120"), Decimal("100"), Decimal("20"))]
    system, user = build_reflection_prompt(mem, closed, ["ETHUSDT"], "be bold")
    assert "JSON" in system and "be bold" in system
    assert "new" in system.lower() and "do not repeat" in system.lower()   # append semantics
    assert "BTCUSDT" in user and "+20.00%" in user
    assert "BTC: old view" in user                    # current memory shown so the LLM won't repeat it


def test_run_reflection_result_ok_returns_new_entries():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"coin_theses": ["BTC: bull", "ETH: flat"], "trade_lessons": ["sold early"], "strategy_notes": []}'
    r = run_reflection_result(MemoryView(), [], [], "x", FakeAdapter())
    assert r.parse_status == "ok"
    assert r.entries.coin_theses == ["BTC: bull", "ETH: flat"]
    assert r.entries.trade_lessons == ["sold early"]
    assert r.raw and r.system and r.user and r.latency_ms >= 0


def test_run_reflection_result_parse_failure_yields_empty_entries():
    class FakeAdapter:
        def complete_json(self, system, user): return "not json"
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.entries == MemoryUpdate()                # nothing to append on failure
    assert r.raw == "not json"


def test_run_reflection_result_provider_error_is_failed():
    class FakeAdapter:
        def complete_json(self, system, user): raise RuntimeError("down")
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.raw is None
    assert r.entries == MemoryUpdate()


from app.brain.memory import (
    build_distillation_prompt, parse_distillation, run_distillation_result, DistillationResult,
)


def test_build_distillation_prompt_mentions_section_cap_and_entries():
    system, user = build_distillation_prompt("coin_theses", ["BTC: a", "BTC: b"], 8, "be terse")
    assert "coin_theses" in system and "8" in system and "be terse" in system
    assert "BTC: a" in user and "BTC: b" in user


def test_parse_distillation_reads_entries_list():
    assert parse_distillation('{"entries": ["one", "two"]}') == ["one", "two"]


def test_run_distillation_ok_truncates_to_cap():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"entries": ["merged 1", "merged 2", "merged 3"]}'
    r = run_distillation_result("strategy_notes", ["a", "b", "c", "d"], 2, "x", FakeAdapter())
    assert r.parse_status == "ok"
    assert r.entries == ["merged 1", "merged 2"]       # truncated to cap=2
    assert r.raw and r.latency_ms >= 0


def test_run_distillation_provider_error_keeps_originals():
    class FakeAdapter:
        def complete_json(self, system, user): raise RuntimeError("down")
    orig = ["a", "b", "c"]
    r = run_distillation_result("coin_theses", orig, 8, "x", FakeAdapter())
    assert r.parse_status == "failed" and r.entries == orig and r.raw is None


def test_run_distillation_empty_output_is_failure():
    class FakeAdapter:
        def complete_json(self, system, user): return '{"entries": []}'
    orig = ["a", "b"]
    r = run_distillation_result("coin_theses", orig, 8, "x", FakeAdapter())
    assert r.parse_status == "failed" and r.entries == orig     # never wipe a section to nothing

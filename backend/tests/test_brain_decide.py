from decimal import Decimal
from app.brain import decide, evaluate
from app.brain.context import build_context


def _ctx():
    return build_context(instructions="x", cash_usd=Decimal("100"),
                         holdings=[], universe=[], recent_events=[])


class _Adapter:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_decide_parses_valid_json():
    d = decide(_ctx(), _Adapter(['{"actions":[{"type":"HOLD","rationale":"wait"}],"note":"n"}']))
    assert d.actions[0].type == "HOLD" and d.note == "n"


def test_decide_repairs_then_succeeds():
    a = _Adapter(["not json", '{"actions":[],"note":"recovered"}'])
    d = decide(_ctx(), a)
    assert d.note == "recovered" and a.calls == 2


def test_decide_gives_up_to_empty_decision():
    d = decide(_ctx(), _Adapter(["bad", "still bad"]))
    assert d.actions == [] and "fail" in d.note.lower()


def test_decide_handles_adapter_exception():
    d = decide(_ctx(), _Adapter([RuntimeError("boom")]))
    assert d.actions == [] and "error" in d.note.lower()


def test_evaluate_ok_captures_raw_status_latency():
    raw = '{"actions":[{"type":"HOLD","rationale":"wait"}],"note":"n"}'
    r = evaluate(_ctx(), _Adapter([raw]))
    assert r.decision.note == "n"
    assert r.parse_status == "ok"
    assert r.raw == raw
    assert r.system and r.user            # prompts captured for replay
    assert r.latency_ms >= 0


def test_evaluate_repaired_keeps_corrected_raw():
    r = evaluate(_ctx(), _Adapter(["not json", '{"actions":[],"note":"recovered"}']))
    assert r.parse_status == "repaired"
    assert r.raw == '{"actions":[],"note":"recovered"}'   # the second, corrected response
    assert r.decision.note == "recovered"


def test_evaluate_failed_keeps_last_raw():
    r = evaluate(_ctx(), _Adapter(["bad", "still bad"]))
    assert r.parse_status == "failed"
    assert r.raw == "still bad"           # last response retained for debugging
    assert r.decision.actions == []


def test_evaluate_provider_error_is_failed_with_null_raw():
    r = evaluate(_ctx(), _Adapter([RuntimeError("boom")]))
    assert r.parse_status == "failed"
    assert r.raw is None                  # no response ever received
    assert "error" in r.decision.note.lower()

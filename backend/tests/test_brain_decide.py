from decimal import Decimal
from app.brain import decide
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

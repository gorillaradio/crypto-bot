from decimal import Decimal
from app.brain.schema import Action, Decision


def test_decision_parses_from_json():
    raw = '{"actions":[{"type":"BUY","symbol":"BTCUSDT","usd_amount":"10","rationale":"dip"}],"note":"cautious"}'
    d = Decision.model_validate_json(raw)
    assert d.note == "cautious"
    assert d.actions[0].type == "BUY"
    assert d.actions[0].usd_amount == Decimal("10")
    assert d.actions[0].fraction is None


def test_action_defaults():
    a = Action(type="HOLD")
    assert a.symbol is None and a.usd_amount is None and a.fraction is None and a.rationale == ""


def test_empty_decision():
    d = Decision()
    assert d.actions == [] and d.note == ""

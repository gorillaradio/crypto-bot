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


def test_action_policy_fields_are_optional_for_old_json():
    raw = '{"actions":[{"type":"BUY","symbol":"BTCUSDT","usd_amount":"10","rationale":"dip"}],"note":"n"}'
    d = Decision.model_validate_json(raw)

    assert d.actions[0].policy_refs == []
    assert d.actions[0].policy_alignment == "unrelated"
    assert d.actions[0].override_reason == ""


def test_action_parses_policy_accountability_fields():
    raw = ('{"actions":[{"type":"BUY","symbol":"BTCUSDT","usd_amount":"10",'
           '"policy_refs":["P1"],"policy_alignment":"violates",'
           '"override_reason":"fresh catalyst","rationale":"override"}],"note":"n"}')
    d = Decision.model_validate_json(raw)

    assert d.actions[0].policy_refs == ["P1"]
    assert d.actions[0].policy_alignment == "violates"
    assert d.actions[0].override_reason == "fresh catalyst"


def test_action_rejects_invalid_policy_alignment():
    from pydantic import ValidationError

    import pytest

    with pytest.raises(ValidationError):
        Action(type="HOLD", policy_alignment="maybe")


def test_empty_decision():
    d = Decision()
    assert d.actions == [] and d.note == ""

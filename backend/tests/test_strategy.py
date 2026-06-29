from decimal import Decimal
from app.agents.strategy import guardrail_action


def test_guardrail_sells_on_stop_loss():
    assert guardrail_action(Decimal("100"), Decimal("85")) == "SELL"


def test_guardrail_sells_on_take_profit():
    assert guardrail_action(Decimal("100"), Decimal("125")) == "SELL"


def test_guardrail_holds_within_band():
    assert guardrail_action(Decimal("100"), Decimal("105")) == "HOLD"

from decimal import Decimal
from app.agents.strategy import sma, decide_signal, guardrail_action


def test_sma_none_if_insufficient():
    assert sma([Decimal("1"), Decimal("2")], 3) is None


def test_sma_average_of_last_window():
    assert sma([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")], 2) == Decimal("3.5")


def test_decide_bullish_crossover_returns_buy():
    # short sale sopra long sull'ultima barra dopo essere stata sotto
    closes = [Decimal("10")] * 19 + [Decimal("5"), Decimal("100")]
    assert decide_signal(closes, short=2, long=5) == "BUY"


def test_decide_bearish_crossover_returns_sell():
    closes = [Decimal("100")] * 20 + [Decimal("1")]
    assert decide_signal(closes, short=2, long=5) == "SELL"


def test_decide_hold_when_no_cross():
    closes = [Decimal("10")] * 25
    assert decide_signal(closes, short=2, long=5) == "HOLD"


def test_guardrail_sells_on_stop_loss():
    assert guardrail_action(Decimal("100"), Decimal("85")) == "SELL"


def test_guardrail_sells_on_take_profit():
    assert guardrail_action(Decimal("100"), Decimal("125")) == "SELL"


def test_guardrail_holds_within_band():
    assert guardrail_action(Decimal("100"), Decimal("105")) == "HOLD"

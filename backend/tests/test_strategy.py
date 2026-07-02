from decimal import Decimal
from app.agents.strategy import breached


def test_breached_stop_side():
    assert breached(Decimal("100"), Decimal("85"), Decimal("0.10"), Decimal("0.20")) == "stop"


def test_breached_take_side():
    assert breached(Decimal("100"), Decimal("125"), Decimal("0.10"), Decimal("0.20")) == "take"


def test_breached_within_band():
    assert breached(Decimal("100"), Decimal("105"), Decimal("0.10"), Decimal("0.20")) is None


def test_breached_disabled_thresholds():
    assert breached(Decimal("100"), Decimal("50"), None, None) is None


def test_breached_stop_only_take_none():
    assert breached(Decimal("100"), Decimal("130"), Decimal("0.10"), None) is None


def test_breached_zero_avg_price():
    assert breached(Decimal("0"), Decimal("50"), Decimal("0.10"), Decimal("0.20")) is None

from decimal import Decimal
from app.eval.metrics import total_return_pct, max_drawdown_pct, sharpe, hit_rate


def test_total_return_pct():
    assert total_return_pct([Decimal("100"), Decimal("150")]) == Decimal("50")
    assert total_return_pct([Decimal("100")]) == Decimal("0")     # need ≥2 points


def test_max_drawdown_pct():
    # 100 → 120 → 60 → 90: peak 120, trough 60 → 50% drawdown
    assert max_drawdown_pct([Decimal("100"), Decimal("120"), Decimal("60"), Decimal("90")]) == Decimal("50")
    assert max_drawdown_pct([Decimal("100"), Decimal("110")]) == Decimal("0")   # monotonic up


def test_sharpe_zero_when_flat():
    assert sharpe([Decimal("100"), Decimal("100"), Decimal("100")]) == Decimal("0")


def test_sharpe_positive_for_steady_growth():
    # NOTE: brief's original series [100, 110, 121] is exact 10% compounding growth,
    # so both per-step returns are identical (0.1, 0.1) -> population stdev == 0 ->
    # sharpe() correctly short-circuits to 0 per its own spec ("0 if stdev is 0").
    # Swapped in a series with genuinely varying per-step returns so this test
    # exercises the intended "positive, non-degenerate sharpe" path.
    assert sharpe([Decimal("100"), Decimal("110"), Decimal("125")]) > Decimal("0")


def test_hit_rate():
    assert hit_rate(3, 4) == Decimal("75")
    assert hit_rate(0, 0) is None

from decimal import Decimal
from app.eval.benchmarks import (
    compute_benchmark_equities, random_weights, hodl_btc_equity,
    equal_weight_equity, percentile, BTC_SYMBOL,
)


def test_hodl_btc_doubles_when_btc_doubles():
    eq = hodl_btc_equity(Decimal("100"), {BTC_SYMBOL: Decimal("100")}, {BTC_SYMBOL: Decimal("200")})
    assert eq == Decimal("200")


def test_hodl_btc_falls_back_to_initial_without_btc():
    assert hodl_btc_equity(Decimal("100"), {}, {}) == Decimal("100")


def test_equal_weight_averages_symbol_returns():
    # AAA +100%, BBB flat → equal dollar split ends at 1.5x
    eq = equal_weight_equity(Decimal("100"), ["AAA", "BBB"],
                             {"AAA": Decimal("10"), "BBB": Decimal("10")},
                             {"AAA": Decimal("20"), "BBB": Decimal("10")})
    assert eq == Decimal("150")


def test_random_weights_are_deterministic_and_normalized():
    w1 = random_weights(7, 3, ["AAA", "BBB", "CCC"])
    w2 = random_weights(7, 3, ["AAA", "BBB", "CCC"])
    assert w1 == w2                                   # reproducible
    assert abs(sum(w1.values()) - 1.0) < 1e-9         # weights sum to 1
    assert random_weights(8, 3, ["AAA", "BBB", "CCC"]) != w1   # different agent → different draw


def test_percentile_interpolates():
    vals = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]
    assert percentile(vals, 0.0) == Decimal("1")
    assert percentile(vals, 0.5) == Decimal("3")
    assert percentile(vals, 1.0) == Decimal("5")


def test_compute_returns_five_named_series_with_ordered_band():
    universe = ["AAA", "BBB", "CCC", "DDD"]
    start = {s: Decimal("10") for s in universe} | {BTC_SYMBOL: Decimal("100")}
    now = {"AAA": Decimal("20"), "BBB": Decimal("5"), "CCC": Decimal("10"),
           "DDD": Decimal("15"), BTC_SYMBOL: Decimal("150")}
    out = compute_benchmark_equities(initial=Decimal("100"), universe=universe,
                                     start_prices=start, now_prices=now, seed=42, n_random=100)
    assert set(out) == {"hodl_btc", "equal_weight", "random_p10", "random_p50", "random_p90"}
    assert out["hodl_btc"] == Decimal("150")          # BTC +50%
    assert out["random_p10"] <= out["random_p50"] <= out["random_p90"]


def test_compute_is_reproducible_for_same_seed():
    universe = ["AAA", "BBB"]
    start = {"AAA": Decimal("10"), "BBB": Decimal("10")}
    now = {"AAA": Decimal("11"), "BBB": Decimal("9")}
    a = compute_benchmark_equities(initial=Decimal("100"), universe=universe,
                                   start_prices=start, now_prices=now, seed=1)
    b = compute_benchmark_equities(initial=Decimal("100"), universe=universe,
                                   start_prices=start, now_prices=now, seed=1)
    assert a == b

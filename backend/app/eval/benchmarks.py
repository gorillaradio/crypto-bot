import random
from decimal import Decimal

BTC_SYMBOL = "BTCUSDT"


def random_weights(seed: int, trader_index: int, symbols: list[str]) -> dict[str, float]:
    # Integer seed only — never hash() a str/tuple (PYTHONHASHSEED randomizes those).
    rng = random.Random(seed * 1_000_003 + trader_index)
    raw = [rng.random() for _ in symbols]
    total = sum(raw) or 1.0
    return {s: r / total for s, r in zip(symbols, raw)}


def hodl_btc_equity(initial: Decimal, start_prices: dict[str, Decimal],
                    now_prices: dict[str, Decimal]) -> Decimal:
    s = start_prices.get(BTC_SYMBOL)
    n = now_prices.get(BTC_SYMBOL)
    if not s or not n:
        return initial
    return initial * (n / s)


def equal_weight_equity(initial: Decimal, universe: list[str],
                        start_prices: dict[str, Decimal], now_prices: dict[str, Decimal]) -> Decimal:
    valid = [s for s in universe if start_prices.get(s) and now_prices.get(s)]
    if not valid:
        return initial
    per = initial / Decimal(len(valid))
    return sum((per * (now_prices[s] / start_prices[s]) for s in valid), Decimal("0"))


def random_basket_equity(initial: Decimal, weights: dict[str, float],
                         start_prices: dict[str, Decimal], now_prices: dict[str, Decimal]) -> Decimal:
    total = Decimal("0")
    for s, w in weights.items():
        s0 = start_prices.get(s)
        s1 = now_prices.get(s)
        if not s0 or not s1:
            continue
        total += initial * Decimal(str(w)) * (s1 / s0)
    return total


def percentile(sorted_values: list[Decimal], p: float) -> Decimal:
    if not sorted_values:
        return Decimal("0")
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = p * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = Decimal(str(idx - lo))
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def compute_benchmark_equities(*, initial: Decimal, universe: list[str],
                               start_prices: dict[str, Decimal], now_prices: dict[str, Decimal],
                               seed: int, n_random: int = 100) -> dict[str, Decimal]:
    eqs = []
    for i in range(n_random):
        w = random_weights(seed, i, universe)
        eqs.append(random_basket_equity(initial, w, start_prices, now_prices))
    eqs.sort()
    return {
        "hodl_btc": hodl_btc_equity(initial, start_prices, now_prices),
        "equal_weight": equal_weight_equity(initial, universe, start_prices, now_prices),
        "random_p10": percentile(eqs, 0.10),
        "random_p50": percentile(eqs, 0.50),
        "random_p90": percentile(eqs, 0.90),
    }

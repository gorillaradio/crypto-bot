from decimal import Decimal
from statistics import mean, pstdev


def total_return_pct(series: list[Decimal]) -> Decimal:
    if len(series) < 2 or series[0] == 0:
        return Decimal("0")
    return (series[-1] - series[0]) / series[0] * Decimal("100")


def max_drawdown_pct(series: list[Decimal]) -> Decimal:
    if not series:
        return Decimal("0")
    peak = series[0]
    mdd = Decimal("0")
    for v in series:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * Decimal("100")
            if dd > mdd:
                mdd = dd
    return mdd


def sharpe(series: list[Decimal]) -> Decimal:
    rets = [(series[i] - series[i - 1]) / series[i - 1]
            for i in range(1, len(series)) if series[i - 1] != 0]
    if len(rets) < 2:
        return Decimal("0")
    sd = pstdev(rets)
    if sd == 0:
        return Decimal("0")
    return mean(rets) / sd


def hit_rate(n_hits: int, n_actions: int) -> Decimal | None:
    if n_actions <= 0:
        return None
    return Decimal(n_hits) / Decimal(n_actions) * Decimal("100")

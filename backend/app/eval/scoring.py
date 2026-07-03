from decimal import Decimal


def aligned_return_pct(action_type: str, p0: Decimal, p1: Decimal) -> Decimal:
    if p0 <= 0:
        return Decimal("0")
    ret = (p1 - p0) / p0 * Decimal("100")
    return ret if action_type == "BUY" else -ret


def score_decision(actions: list[dict], p0: dict[str, Decimal],
                   p1: dict[str, Decimal]) -> tuple[int, int, Decimal | None]:
    n = hits = 0
    total = Decimal("0")
    for a in actions:
        t = a.get("type")
        sym = a.get("symbol")
        if t not in ("BUY", "SELL") or not sym:
            continue
        if sym not in p0 or sym not in p1 or p0[sym] <= 0:
            continue
        r = aligned_return_pct(t, p0[sym], p1[sym])
        n += 1
        if r > 0:
            hits += 1
        total += r
    avg = (total / Decimal(n)) if n else None
    return n, hits, avg

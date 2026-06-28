from decimal import Decimal


def sma(values: list[Decimal], window: int) -> Decimal | None:
    if len(values) < window:
        return None
    window_vals = values[-window:]
    return sum(window_vals) / Decimal(window)


def decide_signal(closes: list[Decimal], short: int = 5, long: int = 20) -> str:
    if len(closes) < long + 1:
        return "HOLD"
    short_now = sma(closes, short)
    long_now = sma(closes, long)
    short_prev = sma(closes[:-1], short)
    long_prev = sma(closes[:-1], long)
    if None in (short_now, long_now, short_prev, long_prev):
        return "HOLD"
    crossed_up = short_prev <= long_prev and short_now > long_now
    crossed_down = short_prev >= long_prev and short_now < long_now
    if crossed_up:
        return "BUY"
    if crossed_down:
        return "SELL"
    return "HOLD"


def guardrail_action(avg_price: Decimal, last_price: Decimal,
                     stop_loss: Decimal = Decimal("0.10"),
                     take_profit: Decimal = Decimal("0.20")) -> str:
    change = (last_price - avg_price) / avg_price
    if change <= -stop_loss or change >= take_profit:
        return "SELL"
    return "HOLD"

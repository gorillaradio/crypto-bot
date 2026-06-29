from decimal import Decimal


def guardrail_action(avg_price: Decimal, last_price: Decimal,
                     stop_loss: Decimal = Decimal("0.10"),
                     take_profit: Decimal = Decimal("0.20")) -> str:
    change = (last_price - avg_price) / avg_price
    if change <= -stop_loss or change >= take_profit:
        return "SELL"
    return "HOLD"

from decimal import Decimal


def breached(avg_price: Decimal, last_price: Decimal,
             stop_loss: Decimal | None, take_profit: Decimal | None) -> str | None:
    """Ritorna "stop" | "take" | None. Soglie come frazioni (0.10 = 10%); None disattiva quel
    lato. Usata dal battito per decidere se svegliare l'LLM."""
    if avg_price <= 0:
        return None
    change = (last_price - avg_price) / avg_price
    if stop_loss is not None and change <= -stop_loss:
        return "stop"
    if take_profit is not None and change >= take_profit:
        return "take"
    return None


def guardrail_action(avg_price: Decimal, last_price: Decimal,
                     stop_loss: Decimal = Decimal("0.10"),
                     take_profit: Decimal = Decimal("0.20")) -> str:
    change = (last_price - avg_price) / avg_price
    if change <= -stop_loss or change >= take_profit:
        return "SELL"
    return "HOLD"

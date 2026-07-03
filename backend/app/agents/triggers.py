from decimal import Decimal


def movement_change(first: Decimal, last: Decimal) -> Decimal:
    """Signed price move over a window: (last - first) / first. 0 when first <= 0."""
    if first <= 0:
        return Decimal("0")
    return (last - first) / first

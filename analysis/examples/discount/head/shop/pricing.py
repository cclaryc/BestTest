"""Pricing rules for the demo shop."""

MAX_DISCOUNT = 0.6


def clamp(value: float, low: float, high: float) -> float:
    # Keep value inside [low, high].
    return max(low, min(high, value))


def calculate_discount(price: float, rate: float, digits: int = 2) -> float:
    """Return the price after applying a discount rate."""
    rate = clamp(rate, 0.0, MAX_DISCOUNT)
    return round(price * (1 - rate), digits)


class Cart:
    def __init__(self) -> None:
        self.items: list[float] = []

    def add(self, price: float) -> None:
        self.items.append(price)

    def clear(self) -> None:
        self.items.clear()

    def total(self, rate: float = 0.0) -> float:
        return sum(calculate_discount(price, rate) for price in self.items)

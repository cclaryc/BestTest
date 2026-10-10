"""Pricing rules for the demo shop."""

MAX_DISCOUNT = 0.5


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def calculate_discount(price: float, rate: float) -> float:
    """Return the price after applying a discount rate."""
    if price < 0:
        raise ValueError("price must not be negative")
    rate = clamp(rate, 0.0, MAX_DISCOUNT)
    return price * (1 - rate)


class Cart:
    def __init__(self) -> None:
        self.items: list[float] = []

    def add(self, price: float) -> None:
        self.items.append(price)

    def total(self, rate: float = 0.0) -> float:
        return sum(calculate_discount(price, rate) for price in self.items)

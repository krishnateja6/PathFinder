"""Utility helpers for the simple_pkg fixture."""


def add(a: int, b: int) -> int:
    """Return the sum of a and b."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Return the product of a and b."""
    return a * b


class Calculator:
    """A tiny stateful calculator used to test method-chunk extraction."""

    def __init__(self, start: int = 0) -> None:
        self.value = start

    def add(self, amount: int) -> int:
        """Add amount to the running value."""
        self.value = add(self.value, amount)
        return self.value

    def multiply(self, factor: int) -> int:
        """Multiply the running value by factor."""
        self.value = multiply(self.value, factor)
        return self.value

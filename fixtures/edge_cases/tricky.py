"""Edge cases the parser needs to handle: no docstring, decorators,
nested functions, empty classes, and multi-line signatures.
"""

import functools


def undocumented(x, y):
    return x + y


@functools.lru_cache(maxsize=None)
def cached_fib(n: int) -> int:
    """Compute the nth Fibonacci number, memoized."""
    if n < 2:
        return n
    return cached_fib(n - 1) + cached_fib(n - 2)


def outer():
    """Outer function containing a nested function definition."""

    def inner():
        return 1

    return inner()


class Empty:
    pass


def multiline_signature(
    a: int,
    b: int,
    *,
    c: int = 0,
) -> int:
    """Sum three numbers, using a multi-line signature."""
    return a + b + c

"""Entry point that ties utils and models together for fixture tests."""

from .models import Dog
from .utils import Calculator, add


def run() -> str:
    """Run a tiny scripted scenario used to test CALLS/IMPORTS edges."""
    calc = Calculator()
    calc.add(5)
    total = add(calc.value, 2)
    dog = Dog("Rex")
    return f"{dog.speak()} total={total}"


if __name__ == "__main__":
    print(run())

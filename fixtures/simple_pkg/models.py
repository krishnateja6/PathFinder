"""Small class hierarchy used to test INHERITS edges in later phases."""


class Animal:
    """Base class for animals."""

    def __init__(self, name: str) -> None:
        self.name = name

    def speak(self) -> str:
        """Return a generic animal sound."""
        return "..."


class Dog(Animal):
    """A dog, which barks instead of making a generic sound."""

    def speak(self) -> str:
        """Return the dog's bark."""
        return "Woof!"

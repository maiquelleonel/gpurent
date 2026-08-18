from typing import Protocol, TypeVar

T = TypeVar("T", covariant=True)


class Orchestrator(Protocol[T]):
    """
    Protocol defining the core interface for all application service orchestrators.
    Enforces that any conforming orchestrator must implement an `execute` method
    returning the specified domain type T.
    """

    def execute(self) -> T:
        """
        Executes the business process and returns the resulting domain object.
        """
        ...

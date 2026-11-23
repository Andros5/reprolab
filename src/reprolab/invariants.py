"""Properties checked on a recorded trace.

An invariant is a function ``events -> list[Violation]``. Because it reads only the
trace, it gives the same verdict on the original run and on any offline replay.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from reprolab.events import Event

Invariant = Callable[[list[Event]], list["Violation"]]


@dataclass(frozen=True)
class Violation:
    invariant: str
    seq: int
    message: str

    def __str__(self) -> str:
        return f"[{self.invariant}] at event #{self.seq}: {self.message}"


def check(events: list[Event], invariants: list[Invariant]) -> list[Violation]:
    return [v for inv in invariants for v in inv(events)]

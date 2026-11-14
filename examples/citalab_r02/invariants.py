"""The business property behind the N-R02 failures, checked on the trace alone.

A reschedule replaces its target: while the person is moving appointment T, the only
write that may complete is the move of T. A completed booking is an extra appointment
attributable to the operation, even if every step was confirmed.
"""

from __future__ import annotations

from reprolab.events import Event
from reprolab.invariants import Invariant, Violation

NAME = "reschedule-replaces-target"


def reschedule_replaces(target: str) -> Invariant:
    def check(events: list[Event]) -> list[Violation]:
        moved = any(e.name == "core.write" and e.ok and e.outcome["ok"].get("status") == "completed"
                    and e.outcome["ok"].get("operation") == "reschedule"
                    and e.outcome["ok"].get("result_id") == target for e in events)
        violations = []
        for e in events:
            if e.name != "core.write" or not e.ok:
                continue
            receipt = e.outcome["ok"]
            if receipt.get("status") != "completed":
                continue
            operation, result = receipt.get("operation"), receipt.get("result_id")
            if operation == "reschedule" and result == target:
                continue
            if operation == "book":
                message = (f"books a new appointment {result} while rescheduling {target}; "
                           + ("no write in the trace moves it" if not moved else "the trace also moves it"))
            else:
                message = f"completes {operation} of {result} while rescheduling {target}"
            violations.append(Violation(NAME, e.seq, message))
        return violations

    check.__name__ = f"reschedule_replaces[{target}]"
    return check

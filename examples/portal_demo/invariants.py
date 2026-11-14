"""Business property of the application flow, checked on the trace alone.

No blind resubmission: after a submission with an uncertain outcome, the client must not
submit the same application again until a lookup has shown it does not exist. A
submission that is known to have succeeded must never be repeated.
"""

from __future__ import annotations

from examples.portal_demo.applier import FIND, SUBMIT
from reprolab.events import CALL, EFFECT_UNKNOWN, Event
from reprolab.invariants import Violation

NAME = "no-blind-resubmit"


def no_blind_resubmit(events: list[Event]) -> list[Violation]:
    uncertain: dict[tuple, int] = {}  # application -> seq of the uncertain submission
    submitted: dict[tuple, int] = {}  # application -> seq where it became known to exist
    violations = []
    for e in events:
        if e.type != CALL or e.name not in (SUBMIT, FIND):
            continue
        key = (e.request["candidate"], e.request["job"])
        if e.name == SUBMIT:
            if key in submitted:
                violations.append(Violation(NAME, e.seq, f"resubmits {key}, already known to exist at #{submitted[key]}"))
            elif key in uncertain:
                violations.append(Violation(
                    NAME, e.seq, f"resubmits {key} after the uncertain outcome at #{uncertain[key]} "
                                 "without reconciling first"))
            if e.ok:
                submitted[key] = e.seq
                uncertain.pop(key, None)
            elif (e.error or {}).get("effect") == EFFECT_UNKNOWN:
                uncertain.setdefault(key, e.seq)
        elif e.ok:  # a well-formed lookup settles the uncertainty either way
            found = e.outcome["ok"].get("applications") if isinstance(e.outcome["ok"], dict) else None
            if not isinstance(found, list):
                continue  # a malformed answer settles nothing (found by the H4 explorer)
            uncertain.pop(key, None)
            if found:
                submitted[key] = e.seq
    return violations

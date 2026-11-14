"""The radar's business property, checked on the trace alone.

No re-send after an uncertain outcome: once the final click of an application was made,
the radar must not click it again unless that submission has been reconciled. The trace
has no reconciliation step: in the radar it is a human act (``/reconcile`` with
"not_received", then a new approval). So within one run, a second click on the same form
is always a violation; the message says whether the first one was confirmed or uncertain.
Same idea as ``examples/portal_demo/invariants.py``, on the radar's boundaries.
"""

from __future__ import annotations

from examples.radar_submit.adapter import CLICK, CONFIRMATION
from reprolab.events import CALL, Event
from reprolab.invariants import Violation

NAME = "no-resend-after-uncertain-outcome"


def no_resend_after_uncertain(events: list[Event]) -> list[Violation]:
    clicked: dict[str, int] = {}  # form url -> seq of its first click
    confirmed: dict[str, int] = {}  # form url -> seq of a confirmation that showed text
    violations = []
    for e in events:
        if e.type != CALL:
            continue
        if e.name == CONFIRMATION and e.ok and (e.outcome["ok"] or {}).get("body"):
            confirmed[e.request["url"]] = e.seq
        if e.name != CLICK:
            continue
        url = e.request["url"]
        if url in confirmed:
            violations.append(Violation(NAME, e.seq, f"clicks submit again after the confirmation at #{confirmed[url]}"))
        elif url in clicked:
            violations.append(Violation(NAME, e.seq, f"clicks submit again after the unconfirmed click at "
                                                     f"#{clicked[url]}, without reconciling"))
        clicked.setdefault(url, e.seq)
    return violations

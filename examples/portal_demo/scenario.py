"""Record and replay one application run: the building blocks of the demo and tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from examples.portal_demo.applier import IMPLEMENTATIONS, OfflineClient, PortalClient
from examples.portal_demo.invariants import no_blind_resubmit
from examples.portal_demo.portal import Portal
from reprolab import BoundaryError, Event, Fault, Session, no_network
from reprolab.invariants import Violation, check

CANDIDATE, JOB = "synthetic-candidate-1", "job-42"
INVARIANTS = [no_blind_resubmit]


@dataclass
class Run:
    implementation: str
    result: dict[str, Any]
    events: list[Event]
    violations: list[Violation]
    portal_applications: int | None = None  # oracle, only known when recording
    faults: list[Fault] = field(default_factory=list)


def record(implementation: str, faults: list[Fault]) -> Run:
    with Portal() as portal:
        session = Session.record(faults=faults)
        result = _run(implementation, session, PortalClient(portal.url))
        events = session.finish()
        oracle = portal.count(CANDIDATE, JOB)
    return Run(implementation, result, events, check(events, INVARIANTS), oracle, faults)


def replay(implementation: str, events: list[Event]) -> Run:
    """Re-run the code against a recording with the network disabled."""
    session = Session.replay(events)
    with no_network():
        result = _run(implementation, session, OfflineClient())
    replayed = session.finish()
    return Run(implementation, result, replayed, check(replayed, INVARIANTS))


def _run(implementation: str, session: Session, client) -> dict[str, Any]:
    try:
        return IMPLEMENTATIONS[implementation](session, client, CANDIDATE, JOB)
    except BoundaryError as error:
        return {"state": "error", "error": error.type}

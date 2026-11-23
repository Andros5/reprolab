"""A scenario: the code under test, its environments and its business properties.

The CLI finds a scenario by its target, ``module:attribute``, and stores that target in
every recording so a replay knows which code to run again.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any

from reprolab.events import Event
from reprolab.invariants import Invariant, Violation, check
from reprolab.netguard import NetworkBlocked, no_network
from reprolab.session import BoundaryError, Fault, Session, WorkerCrash

MAX_RESTARTS = 5


@dataclass(frozen=True)
class Scenario:
    """``run(session, env)`` is the code under test.

    - ``live()`` is a context manager that provides the real environment for recording
      (for example, it starts a local service and yields a client for it).
    - ``offline()`` returns the environment for replay. Nothing in it may be reached:
      every external interaction comes from the recording.
    - ``oracle(env)`` optionally reads the real state of the live environment after a
      recording. It is evidence separate from the trace and is never replayed.
    """

    name: str
    invariants: tuple[Invariant, ...]
    run: Callable[[Session, Any], Any] | None = None  # None: the scenario only checks traces
    live: Callable[[], AbstractContextManager[Any]] | None = None
    offline: Callable[[], Any] | None = None
    oracle: Callable[[Any], dict[str, Any]] | None = None
    # Judges the oracle's reading: a message when the real state is wrong, else None.
    oracle_check: Callable[[dict[str, Any]], str | None] | None = None
    description: str = ""


@dataclass
class Outcome:
    result: Any
    events: list[Event]
    violations: list[Violation]
    oracle: dict[str, Any] | None = None  # only known when recording
    faults: list[Fault] = field(default_factory=list)


def _run(scenario: Scenario, session: Session, env: Any) -> Any:
    """Run the code. After a simulated crash, run it again with the same durable
    environment: a restarted worker has lost its memory, not its storage."""
    for _ in range(MAX_RESTARTS + 1):
        try:
            return scenario.run(session, env)
        except BoundaryError as error:  # the code let a boundary error escape: that is its result
            return {"state": "error", "error": error.type}
        except WorkerCrash:
            session.restart()
        except (AssertionError, NetworkBlocked):  # replay divergence or a broken test double: never a result
            raise
        except Exception as exc:  # noqa: BLE001 - an unhandled exception is a finding, kept as the result
            return {"state": "unhandled", "error": type(exc).__name__, "message": str(exc)[:200]}
    return {"state": "crashed", "restarts": MAX_RESTARTS}


def record(scenario: Scenario, faults: list[Fault] | None = None) -> Outcome:
    if scenario.run is None or scenario.live is None:
        raise ValueError(f"scenario {scenario.name!r} has no code to record; it only checks traces")
    faults = list(faults or [])
    with scenario.live() as env:
        session = Session.record(faults=faults)
        result = _run(scenario, session, env)
        events = session.finish()
        oracle = scenario.oracle(env) if scenario.oracle else None
    return Outcome(result, events, check(events, list(scenario.invariants)), oracle, faults)


def replay(scenario: Scenario, events: list[Event]) -> Outcome:
    """Re-run the code against a recording with the network disabled."""
    if scenario.run is None or scenario.offline is None:
        raise ValueError(f"scenario {scenario.name!r} has no code to replay; it only checks traces")
    session = Session.replay(events)
    with no_network():
        result = _run(scenario, session, scenario.offline())
    replayed = session.finish()
    return Outcome(result, replayed, check(replayed, list(scenario.invariants)))


def load_target(target: str) -> Scenario:
    """Import ``module:attribute``. The current directory is importable, as with pytest."""
    module_name, sep, attr = target.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError(f"Target must be 'module:attribute', got {target!r}")
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    obj = getattr(importlib.import_module(module_name), attr, None)
    if not isinstance(obj, Scenario):
        raise ValueError(f"{target} is not a reprolab Scenario")
    return obj

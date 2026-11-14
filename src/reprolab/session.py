"""Record and replay a run through its instrumented boundaries.

Code under test routes every external interaction through a Session:

    result = session.call("portal.submit", payload, client.submit)
    now = session.now()

In record mode the real function runs (optionally with an injected fault) and the
observed outcome is appended as an event. In replay mode nothing external runs: the
next recorded event is checked against the request and its outcome is returned or
raised again. Any mismatch is a ReplayDivergence, never a silent difference.

Replay reproduces recorded outcomes; it does not claim an LLM or service would answer
the same way again.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from reprolab.events import CALL, CLOCK, EFFECT_NONE, EFFECT_UNKNOWN, RANDOM, Event, normalize

RECORD = "record"
REPLAY = "replay"


class BoundaryError(Exception):
    """An error as the caller observed it at a boundary.

    ``effect`` says what the caller can know about side effects: EFFECT_NONE when the
    request certainly did nothing, EFFECT_UNKNOWN when it may have taken effect.
    """

    def __init__(self, type_: str, message: str, effect: str = EFFECT_UNKNOWN):
        super().__init__(f"{type_}: {message} (effect: {effect})")
        self.type = type_
        self.message = message
        self.effect = effect

    def as_outcome(self) -> dict[str, Any]:
        return {"error": {"type": self.type, "message": self.message, "effect": self.effect}}


class ReplayDivergence(AssertionError):
    """The code under replay did something the recording does not contain."""


# Faults. Each simulates what a caller would observe; the simulation is explicit in
# the recording (Event.fault), so a reader never mistakes it for a real incident.
LOST_RESPONSE = "lost_response"  # the call runs and takes effect, the response is lost
RATE_LIMITED = "rate_limited"  # the call is rejected before acting (HTTP 429)
FAULTS = {LOST_RESPONSE, RATE_LIMITED}


@dataclass(frozen=True)
class Fault:
    """Inject ``kind`` on the ``occurrence``-th call (1-based) named ``name``."""

    name: str
    occurrence: int
    kind: str

    def __post_init__(self):
        if self.kind not in FAULTS:
            raise ValueError(f"Unknown fault {self.kind!r}; known: {sorted(FAULTS)}")
        if self.occurrence < 1:
            raise ValueError("occurrence is 1-based")


def _classify(exc: Exception) -> BoundaryError:
    """Default view of an unexpected exception: the caller cannot know what happened."""
    if isinstance(exc, BoundaryError):
        return exc
    return BoundaryError(type(exc).__name__, str(exc), EFFECT_UNKNOWN)


class Session:
    def __init__(self, mode: str, events: list[Event] | None = None, faults: list[Fault] | None = None,
                 classify: Callable[[Exception], BoundaryError] = _classify):
        if mode not in (RECORD, REPLAY):
            raise ValueError(mode)
        if mode == REPLAY and faults:
            raise ValueError("Faults are part of the recording; a replay reproduces them, it does not add new ones")
        self.mode = mode
        self.events: list[Event] = [] if mode == RECORD else list(events or [])
        self.faults = list(faults or [])
        self.classify = classify
        self._cursor = 0
        self._calls_by_name: dict[str, int] = {}

    @classmethod
    def record(cls, faults: list[Fault] | None = None, **kwargs) -> "Session":
        return cls(RECORD, faults=faults, **kwargs)

    @classmethod
    def replay(cls, events: list[Event]) -> "Session":
        return cls(REPLAY, events=events)

    # -- boundaries -------------------------------------------------------------------

    def call(self, name: str, request: Any, fn: Callable[[Any], Any], *, kind: str = "http") -> Any:
        request = normalize(request)
        if self.mode == REPLAY:
            event = self._next(CALL, name, request)
            if event.ok:
                return event.outcome["ok"]
            e = event.error or {}
            raise BoundaryError(e.get("type", "Error"), e.get("message", ""), e.get("effect", EFFECT_UNKNOWN))

        count = self._calls_by_name[name] = self._calls_by_name.get(name, 0) + 1
        fault = next((f.kind for f in self.faults if f.name == name and f.occurrence == count), None)
        try:
            if fault == RATE_LIMITED:
                raise BoundaryError("RateLimited", "HTTP 429 injected by ReproLab", EFFECT_NONE)
            result = normalize(fn(request))
            if fault == LOST_RESPONSE:
                raise BoundaryError("LostResponse", "response lost after the request was processed (injected)",
                                    EFFECT_UNKNOWN)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a recorded outcome
            error = self.classify(exc)
            self._append(CALL, name, kind=kind, request=request, outcome=error.as_outcome(), fault=fault)
            raise error from (None if exc is error else exc)
        self._append(CALL, name, kind=kind, request=request, outcome={"ok": result}, fault=fault)
        return result

    def now(self) -> float:
        if self.mode == REPLAY:
            return self._next(CLOCK, "now").outcome["ok"]
        value = time.time()
        self._append(CLOCK, "now", outcome={"ok": value})
        return value

    def token(self) -> str:
        """A random identifier (for example an idempotency or request id)."""
        if self.mode == REPLAY:
            return self._next(RANDOM, "token").outcome["ok"]
        value = uuid.uuid4().hex
        self._append(RANDOM, "token", outcome={"ok": value})
        return value

    def finish(self) -> list[Event]:
        """End the run. In replay, every recorded event must have been consumed."""
        if self.mode == REPLAY and self._cursor != len(self.events):
            rest = self.events[self._cursor]
            raise ReplayDivergence(
                f"The run ended but the recording continues at {rest.describe()} "
                f"({len(self.events) - self._cursor} events not reproduced)")
        return list(self.events)

    # -- internals ----------------------------------------------------------------

    def _append(self, type_: str, name: str, **fields: Any) -> None:
        self.events.append(Event(seq=len(self.events) + 1, type=type_, name=name, **fields))

    def _next(self, type_: str, name: str, request: Any = None) -> Event:
        if self._cursor >= len(self.events):
            raise ReplayDivergence(f"The code made an extra {type_} {name!r} that the recording does not contain")
        event = self.events[self._cursor]
        if (event.type, event.name) != (type_, name):
            raise ReplayDivergence(f"Expected {event.describe()}, but the code made {type_} {name!r}")
        if type_ == CALL and event.request != request:
            raise ReplayDivergence(f"Request differs at #{event.seq} {name}: recorded {event.request!r}, now {request!r}")
        self._cursor += 1
        return event

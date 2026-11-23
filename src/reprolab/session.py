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
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from reprolab.events import (
    CALL,
    CLOCK,
    CRASH_AFTER,
    DUPLICATE,
    EFFECT_NONE,
    EFFECT_UNKNOWN,
    FAULT_KINDS,
    INVALID_OUTPUT,
    LOST_RESPONSE,
    RANDOM,
    RATE_LIMITED,
    RESTART,
    TIMEOUT,
    DependencyTracker,
    Event,
    normalize,
)

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
    """The code under replay did something the recording does not contain.

    ``seq`` is the recorded event where replay stopped matching (None when the code went
    past the end of the recording); ``reproduced`` is how many events matched before."""

    def __init__(self, message: str, seq: int | None = None, reproduced: int = 0):
        super().__init__(message)
        self.seq = seq
        self.reproduced = reproduced


class WorkerCrash(BaseException):
    """The worker process died (simulated). Not an Exception, so the code under test
    cannot catch it by accident: only the scenario runner handles it, by restarting the
    code with its durable state and an empty memory."""


def _malformed(value: Any) -> Any:
    """What ``invalid_output`` returns instead of the real output: the same shape, emptied."""
    if isinstance(value, dict):
        return {}
    if isinstance(value, list):
        return []
    return None


FAULTS = set(FAULT_KINDS)


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

    @classmethod
    def parse(cls, text: str) -> Fault:
        """Parse ``name:occurrence:kind``, for example ``portal.submit:1:lost_response``."""
        try:
            name, occurrence, kind = text.rsplit(":", 2)
            return cls(name, int(occurrence), kind)
        except ValueError as exc:
            raise ValueError(f"Bad fault {text!r}: expected name:occurrence:kind ({exc})") from None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "occurrence": self.occurrence, "kind": self.kind}


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
        self._deps = DependencyTracker()
        self._op: str | None = None

    @classmethod
    def record(cls, faults: list[Fault] | None = None, **kwargs) -> Session:
        return cls(RECORD, faults=faults, **kwargs)

    @classmethod
    def replay(cls, events: list[Event]) -> Session:
        return cls(REPLAY, events=events)

    @property
    def last_seq(self) -> int:
        """Seq of the latest event, to declare an explicit dependency on it."""
        return len(self.events) if self.mode == RECORD else self._cursor

    @contextmanager
    def operation(self, op_id: str) -> Iterator[None]:
        """Group the events inside the block under one business operation id."""
        previous, self._op = self._op, op_id
        try:
            yield
        finally:
            self._op = previous

    # -- boundaries -------------------------------------------------------------------

    def call(self, name: str, request: Any, fn: Callable[[Any], Any], *, kind: str = "http",
             deps: Iterable[int] = ()) -> Any:
        """Cross a boundary. ``deps`` adds explicit dependencies (seqs of earlier events)
        to the ones inferred from the values in ``request``."""
        request = normalize(request)
        if self.mode == REPLAY:
            event = self._next(CALL, name, request)
            if event.fault_kind == CRASH_AFTER:
                raise WorkerCrash(f"#{event.seq} {name}")
            if event.ok:
                return event.outcome["ok"]
            e = event.error or {}
            raise BoundaryError(e.get("type", "Error"), e.get("message", ""), e.get("effect", EFFECT_UNKNOWN))

        count = self._calls_by_name[name] = self._calls_by_name.get(name, 0) + 1
        fault = next((f.kind for f in self.faults if f.name == name and f.occurrence == count), None)
        mark = {"kind": fault, "simulated": True} if fault else None
        all_deps = set(deps) | self._deps.deps_of(request)
        try:
            if fault == RATE_LIMITED:
                raise BoundaryError("RateLimited", "HTTP 429 injected by ReproLab", EFFECT_NONE)
            if fault == TIMEOUT:
                raise BoundaryError("Timeout", "request timed out before reaching the service (injected)",
                                    EFFECT_UNKNOWN)
            result = normalize(fn(request))
            if fault == DUPLICATE:
                try:  # the second delivery takes effect too; its response never reaches the caller
                    fn(request)
                except Exception:  # noqa: BLE001
                    pass
            if fault == LOST_RESPONSE:
                raise BoundaryError("LostResponse", "response lost after the request was processed (injected)",
                                    EFFECT_UNKNOWN)
            if fault == INVALID_OUTPUT:
                result = _malformed(result)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a recorded outcome
            error = self.classify(exc)
            self._append(CALL, name, kind=kind, request=request, outcome=error.as_outcome(), fault=mark,
                         deps=all_deps)
            raise error from (None if exc is error else exc)
        if fault == CRASH_AFTER:
            crash = BoundaryError("WorkerCrash", "the worker died after the request took effect (injected)",
                                  EFFECT_UNKNOWN)
            self._append(CALL, name, kind=kind, request=request, outcome=crash.as_outcome(), fault=mark,
                         deps=all_deps)
            raise WorkerCrash(f"#{self.last_seq} {name}")
        self._append(CALL, name, kind=kind, request=request, outcome={"ok": result}, fault=mark, deps=all_deps)
        return result

    def restart(self) -> None:
        """Mark that the worker restarted after a crash (called by the scenario runner)."""
        if self.mode == REPLAY:
            self._next(CALL, RESTART, None)
            return
        self._append(CALL, RESTART, kind="tool", request=None, outcome={"ok": None}, deps=[self.last_seq])

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
                f"({len(self.events) - self._cursor} events not reproduced)", rest.seq, self._cursor)
        return list(self.events)

    # -- internals ----------------------------------------------------------------

    def _append(self, type_: str, name: str, *, deps: Iterable[int] = (), **fields: Any) -> None:
        seq = len(self.events) + 1
        bad = [d for d in deps if not 1 <= d < seq]
        if bad:
            raise ValueError(f"Dependencies must be earlier events (1..{seq - 1}), got {bad}")
        event = Event(seq=seq, type=type_, name=name, deps=tuple(sorted(set(deps))), op=self._op, **fields)
        self.events.append(event)
        self._deps.produced(seq, event.outcome)

    def _next(self, type_: str, name: str, request: Any = None) -> Event:
        if self._cursor >= len(self.events):
            raise ReplayDivergence(f"The code made an extra {type_} {name!r} that the recording does not contain",
                                   None, self._cursor)
        event = self.events[self._cursor]
        if (event.type, event.name) != (type_, name):
            raise ReplayDivergence(f"Expected {event.describe()}, but the code made {type_} {name!r}",
                                   event.seq, self._cursor)
        if type_ == CALL and event.request != request:
            raise ReplayDivergence(f"Request differs at #{event.seq} {name}: recorded {event.request!r}, now {request!r}",
                                   event.seq, self._cursor)
        if event.op != self._op:
            raise ReplayDivergence(f"Operation differs at #{event.seq} {name}: recorded {event.op!r}, now {self._op!r}",
                                   event.seq, self._cursor)
        self._cursor += 1
        return event

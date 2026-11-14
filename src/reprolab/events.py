"""The event model (schema v3): what a run observed at its instrumented boundaries.

A run is an ordered list of events. Replay feeds the recorded outcomes back to the code
instead of contacting the outside world, so everything that can differ between two
executions (external results, errors, the clock, randomness) must be an event.

The format is specified in docs/schema.md. Parsing is strict: unknown fields, missing
fields and out-of-range values are errors, never silently ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 3
READABLE_VERSIONS = (1, 2, 3)  # older recordings are migrated on read

# Event types
CALL = "call"  # a call across a boundary: HTTP request, LLM call, tool call
CLOCK = "clock"  # a reading of the wall clock
RANDOM = "random"  # a random token
EVENT_TYPES = (CALL, CLOCK, RANDOM)
CALL_KINDS = ("http", "llm", "tool", "user")  # "user": a message or action from a (simulated) person

# What an error tells the caller about side effects on the other side.
EFFECT_NONE = "none"  # the request certainly had no effect (rejected before acting)
EFFECT_UNKNOWN = "unknown"  # the request may or may not have taken effect
EFFECTS = (EFFECT_NONE, EFFECT_UNKNOWN)

# Faults ReproLab can inject. They are simulations, and each event that carries one says
# so explicitly: {"kind": ..., "simulated": true}.
LOST_RESPONSE = "lost_response"  # the call runs and takes effect, the response is lost
RATE_LIMITED = "rate_limited"  # the call is rejected before acting (HTTP 429)
TIMEOUT = "timeout"  # the request never arrives; the caller cannot know that (effect unknown)
DUPLICATE = "duplicate"  # the request is delivered twice; the caller sees one response
INVALID_OUTPUT = "invalid_output"  # the call runs, but its output lacks the expected fields
CRASH_AFTER = "crash_after"  # the call takes effect, then the worker process dies
FAULT_KINDS = (LOST_RESPONSE, RATE_LIMITED, TIMEOUT, DUPLICATE, INVALID_OUTPUT, CRASH_AFTER)
RESTART = "worker.restart"  # the call that marks a restarted worker in a trace

# Automatic dependency detection: a value produced by an earlier event that reappears in
# a later request links the two. Only distinctive values count (see _distinctive).
MIN_DISTINCTIVE_LENGTH = 8

_EVENT_FIELDS = ("seq", "type", "name", "kind", "request", "outcome", "fault", "deps", "op", "evidence")
_SOURCE_FIELDS = ("source", "pointer", "sha256")


class SchemaError(ValueError):
    """A recording does not conform to the event schema."""


def normalize(value: Any) -> Any:
    """JSON round trip, so recorded and replayed values are identical objects."""
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))


@dataclass(frozen=True)
class Event:
    seq: int  # position in the original run; stable, never renumbered by a reduction
    type: str
    name: str
    kind: str = ""  # for calls: "http", "llm" or "tool"; empty otherwise
    request: Any = None
    # {"ok": value} or {"error": {"type": ..., "message": ..., "effect": ...}}
    outcome: dict[str, Any] = field(default_factory=dict)
    fault: dict[str, Any] | None = None  # {"kind": ..., "simulated": True} if injected
    deps: tuple[int, ...] = ()  # seqs of earlier events this one depends on
    op: str | None = None  # business operation this event belongs to, if any
    # Where an imported event comes from (null for events a Session observed itself):
    # {"sources": [{"source", "pointer", "sha256"}], "rule": null} when copied verbatim
    # from one place, or {"sources": [...], "rule": "..."} when derived by that rule.
    evidence: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return "ok" in self.outcome

    @property
    def error(self) -> dict[str, Any] | None:
        return self.outcome.get("error")

    @property
    def reconstructed(self) -> bool:
        return bool(self.evidence and self.evidence["rule"])

    @property
    def fault_kind(self) -> str | None:
        return self.fault["kind"] if self.fault else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq, "type": self.type, "name": self.name, "kind": self.kind,
            "request": self.request, "outcome": self.outcome, "fault": self.fault,
            "deps": list(self.deps), "op": self.op, "evidence": self.evidence,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Any) -> "Event":
        validate_event_dict(data)
        return cls(**{**data, "deps": tuple(data["deps"])})

    @classmethod
    def from_json(cls, text: str) -> "Event":
        return cls.from_dict(json.loads(text))

    def describe(self) -> str:
        """One human-readable line. Long strings are shortened; the event itself is not."""
        if self.type != CALL:
            head = f"#{self.seq} {self.type} {self.name} = {self.outcome.get('ok')!r}"
        else:
            if self.ok:
                result = f"ok {_brief(self.outcome['ok'])}"
            else:
                e = self.error or {}
                result = f"ERROR {e.get('type')} (effect: {e.get('effect')})"
            head = f"#{self.seq} {self.kind} {self.name} {_brief(self.request)} -> {result}"
        if self.fault:
            head += f"  [simulated fault: {self.fault['kind']}]"
        if self.deps:
            head += "  <- " + " ".join(f"#{d}" for d in self.deps)
        if self.reconstructed:
            head += "  [reconstructed]"
        return head


def _shorten(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 3] + "..."
    if isinstance(value, dict):
        return {k: _shorten(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten(v, limit) for v in value]
    return value


def _brief(value: Any, limit: int = 40) -> str:
    return json.dumps(_shorten(value, limit), sort_keys=True, ensure_ascii=False)


# -- validation --------------------------------------------------------------------

def _fail(where: str, message: str) -> None:
    raise SchemaError(f"{where}: {message}")


def validate_event_dict(data: Any) -> None:
    """Check one serialized event against schema v2. Raises SchemaError."""
    if not isinstance(data, dict):
        _fail("event", f"expected an object, got {type(data).__name__}")
    seq = data.get("seq")
    where = f"event #{seq}" if isinstance(seq, int) else "event"
    keys = set(data)
    if keys != set(_EVENT_FIELDS):
        missing, unknown = set(_EVENT_FIELDS) - keys, keys - set(_EVENT_FIELDS)
        _fail(where, f"fields differ from schema v{SCHEMA_VERSION}"
                     + (f"; missing {sorted(missing)}" if missing else "")
                     + (f"; unknown {sorted(unknown)}" if unknown else ""))
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        _fail(where, "seq must be an integer >= 1")
    type_ = data["type"]
    if type_ not in EVENT_TYPES:
        _fail(where, f"type must be one of {list(EVENT_TYPES)}, got {type_!r}")
    if not isinstance(data["name"], str) or not data["name"]:
        _fail(where, "name must be a non-empty string")
    if type_ == CALL:
        if data["kind"] not in CALL_KINDS:
            _fail(where, f"kind of a call must be one of {list(CALL_KINDS)}, got {data['kind']!r}")
    else:
        if data["kind"] != "" or data["request"] is not None or data["fault"] is not None:
            _fail(where, f"a {type_} event has no kind, request or fault")
    _validate_outcome(where, type_, data["outcome"])
    fault = data["fault"]
    if fault is not None:
        if not isinstance(fault, dict) or set(fault) != {"kind", "simulated"}:
            _fail(where, "fault must be null or {kind, simulated}")
        if fault["kind"] not in FAULT_KINDS:
            _fail(where, f"unknown fault kind {fault['kind']!r}")
        if fault["simulated"] is not True:
            _fail(where, "an injected fault must be marked simulated: true")
    deps = data["deps"]
    if not isinstance(deps, list) or not all(isinstance(d, int) and not isinstance(d, bool) for d in deps):
        _fail(where, "deps must be a list of integers")
    if deps != sorted(set(deps)) or any(d < 1 or d >= seq for d in deps):
        _fail(where, "deps must be sorted, unique, and refer to earlier events")
    if data["op"] is not None and (not isinstance(data["op"], str) or not data["op"]):
        _fail(where, "op must be null or a non-empty string")
    _validate_evidence(where, data["evidence"])


def _validate_evidence(where: str, evidence: Any) -> None:
    if evidence is None:
        return
    if not isinstance(evidence, dict) or set(evidence) != {"sources", "rule"}:
        _fail(where, "evidence must be null or {sources, rule}")
    sources, rule = evidence["sources"], evidence["rule"]
    if not isinstance(sources, list):
        _fail(where, "evidence sources must be a list")
    for src in sources:
        if not isinstance(src, dict) or set(src) != set(_SOURCE_FIELDS) or not all(
                isinstance(src[k], str) and src[k] for k in ("source", "sha256")) or not isinstance(src["pointer"], str):
            _fail(where, "each evidence source is {source, pointer, sha256}")
    if rule is None:
        if len(sources) != 1:
            _fail(where, "verbatim evidence (rule: null) has exactly one source")
    elif not isinstance(rule, str) or not rule:
        _fail(where, "evidence rule must be null or a non-empty string")


def _validate_outcome(where: str, type_: str, outcome: Any) -> None:
    if not isinstance(outcome, dict) or len(outcome) != 1 or next(iter(outcome)) not in ("ok", "error"):
        _fail(where, 'outcome must be {"ok": value} or {"error": {...}}')
    if "error" in outcome:
        if type_ != CALL:
            _fail(where, f"a {type_} event cannot fail")
        error = outcome["error"]
        if not isinstance(error, dict) or set(error) != {"type", "message", "effect"}:
            _fail(where, "error must be {type, message, effect}")
        if not isinstance(error["type"], str) or not isinstance(error["message"], str):
            _fail(where, "error type and message must be strings")
        if error["effect"] not in EFFECTS:
            _fail(where, f"error effect must be one of {list(EFFECTS)}")


def validate_trace(events: list[Event], *, contiguous: bool) -> None:
    """Check a whole trace: increasing seqs and dependencies present in the trace.

    A recorded run is contiguous (1..n). A reduced run keeps the original seqs of the
    events it kept, so it may have gaps, but every dependency must still be present.
    """
    present: set[int] = set()
    previous = 0
    for e in events:
        validate_event_dict(e.to_dict())
        if e.seq <= previous:
            _fail(f"event #{e.seq}", f"seq must increase (previous was #{previous})")
        if contiguous and e.seq != previous + 1:
            _fail(f"event #{e.seq}", f"a recorded run has contiguous seqs; expected #{previous + 1}")
        missing = [d for d in e.deps if d not in present]
        if missing:
            _fail(f"event #{e.seq}", f"depends on events not in the trace: {missing}")
        present.add(e.seq)
        previous = e.seq


# -- dependencies ------------------------------------------------------------------

def _distinctive(value: Any) -> Iterator[Any]:
    """Leaves distinctive enough to trace data flow: strings of 8+ characters and
    non-integral floats (clock readings). Small ints and short strings such as an id
    of 1 or "yes" would create false links, so they are never used."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _distinctive(v)
    elif isinstance(value, list):
        for v in value:
            yield from _distinctive(v)
    elif isinstance(value, str) and len(value) >= MIN_DISTINCTIVE_LENGTH:
        yield value
    elif isinstance(value, float) and not value.is_integer():
        yield value


class DependencyTracker:
    """Infers data dependencies by value: if a request contains a distinctive value an
    earlier event produced (a token, a returned id, a drafted text), it depends on that
    event. It captures data flow only; control flow (doing B because A failed) is not
    visible in values and must be passed explicitly if it matters."""

    def __init__(self) -> None:
        self._producer: dict[tuple[str, Any], int] = {}

    def deps_of(self, request: Any) -> set[int]:
        return {self._producer[k] for v in _distinctive(request)
                if (k := (type(v).__name__, v)) in self._producer}

    def produced(self, seq: int, outcome: dict[str, Any]) -> None:
        if "ok" in outcome:
            for v in _distinctive(outcome["ok"]):
                self._producer.setdefault((type(v).__name__, v), seq)  # the first producer is the origin


def infer_deps(events: Iterable[Event]) -> list[Event]:
    """Recompute value-based dependencies over a trace (used to migrate v1 recordings)."""
    tracker, out = DependencyTracker(), []
    for e in events:
        deps = tuple(sorted(set(e.deps) | tracker.deps_of(e.request)))
        out.append(Event(**{**e.to_dict(), "deps": deps}))
        tracker.produced(e.seq, e.outcome)
    return out


def migrate_v2(body: dict[str, Any]) -> dict[str, Any]:
    """Turn a v2 event body into v3: events a Session observed have no external evidence."""
    if not isinstance(body, dict) or "evidence" in body:
        raise SchemaError(f"not a v2 event: {body!r}")
    return {**body, "evidence": None}


def migrate_v1(body: dict[str, Any]) -> dict[str, Any]:
    """Turn a v1 event body into v3. Dependencies are inferred afterwards by the caller."""
    known = {"seq", "type", "name", "kind", "request", "outcome", "fault"}
    if not isinstance(body, dict) or not set(body) <= known:
        raise SchemaError(f"not a v1 event: {body!r}")
    fault = body.get("fault")
    return {
        "seq": body["seq"], "type": body["type"], "name": body.get("name", ""), "kind": body.get("kind", ""),
        "request": body.get("request"), "outcome": body.get("outcome", {}),
        "fault": {"kind": fault, "simulated": True} if fault else None, "deps": [], "op": None, "evidence": None,
    }

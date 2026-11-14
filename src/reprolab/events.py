"""The event model: what a run observed at its instrumented boundaries.

A run is an ordered list of events. Replay feeds the recorded outcomes back to the code
instead of contacting the outside world, so everything that can differ between two
executions (external results, errors, the clock, randomness) must be an event.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

# Event types
CALL = "call"  # a call across a boundary: HTTP request, LLM call, tool call
CLOCK = "clock"  # a reading of the wall clock
RANDOM = "random"  # a random token

# What an error tells the caller about side effects on the other side.
EFFECT_NONE = "none"  # the request certainly had no effect (rejected before acting)
EFFECT_UNKNOWN = "unknown"  # the request may or may not have taken effect


def normalize(value: Any) -> Any:
    """JSON round trip, so recorded and replayed values are identical objects."""
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))


@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    name: str = ""
    kind: str = ""  # for calls: "http", "llm" or "tool"
    request: Any = None
    # {"ok": value} or {"error": {"type": ..., "message": ..., "effect": ...}}
    outcome: dict[str, Any] = field(default_factory=dict)
    fault: str | None = None  # fault injected on this call, if any

    @property
    def ok(self) -> bool:
        return "ok" in self.outcome

    @property
    def error(self) -> dict[str, Any] | None:
        return self.outcome.get("error")

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "Event":
        return cls(**json.loads(text))

    def describe(self) -> str:
        if self.type != CALL:
            return f"#{self.seq} {self.type} {self.name} = {self.outcome.get('ok')!r}"
        if self.ok:
            result = f"ok {json.dumps(self.outcome['ok'], ensure_ascii=False)}"
        else:
            e = self.error or {}
            result = f"ERROR {e.get('type')} (effect: {e.get('effect')})"
        fault = f"  [fault injected: {self.fault}]" if self.fault else ""
        return f"#{self.seq} {self.kind} {self.name} {json.dumps(self.request, ensure_ascii=False)} -> {result}{fault}"

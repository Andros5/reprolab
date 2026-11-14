"""First divergence between two traces.

Two runs of the same workflow are compared event by event, in order. The first
difference is classified:

- ``different-call``: a different boundary was crossed (the code took another path);
- ``different-request``: the same boundary, called with different input;
- ``same-request-different-outcome``: identical input, different answer. For an LLM call
  this is the signature of non-determinism on the other side of the boundary: the code
  asked the same question and got a different answer;
- ``length``: one trace is a prefix of the other.

Everything before the divergence is identical, so it cannot explain the difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reprolab.events import Event, _brief

DIFFERENT_CALL = "different-call"
DIFFERENT_REQUEST = "different-request"
SAME_REQUEST_DIFFERENT_OUTCOME = "same-request-different-outcome"
LENGTH = "length"


@dataclass(frozen=True)
class Divergence:
    position: int  # 0-based index in both traces
    kind: str
    a: Event | None
    b: Event | None
    paths: tuple[str, ...] = ()  # JSON paths that differ (request or outcome), at most a few
    values: tuple[tuple[Any, Any], ...] = ()  # (A, B) value at each path

    def describe(self) -> str:
        where = f"at position {self.position + 1}"
        if self.kind == LENGTH:
            longer = self.a or self.b
            return f"{where}: one trace ends; the other continues with {longer.describe()}"
        head = {DIFFERENT_CALL: "different call", DIFFERENT_REQUEST: "same call, different request",
                SAME_REQUEST_DIFFERENT_OUTCOME: "same call and request, different outcome"}[self.kind]
        lines = [f"{where}: {head}", f"  A: {self.a.describe()}", f"  B: {self.b.describe()}"]
        for path, (x, y) in zip(self.paths, self.values):
            lines.append(f"  {path}: A {_brief(x)}  /  B {_brief(y)}")
        return "\n".join(lines)


def _diff(x: Any, y: Any, prefix: str = "") -> tuple[tuple[str, ...], tuple[tuple[Any, Any], ...]]:
    found = _paths(x, y, prefix)
    return tuple(p for p, _ in found), tuple(v for _, v in found)


def _paths(x: Any, y: Any, prefix: str = "", limit: int = 6) -> list[tuple[str, tuple[Any, Any]]]:
    if x == y:
        return []
    if isinstance(x, dict) and isinstance(y, dict):
        out = []
        for key in sorted(set(x) | set(y)):
            out += _paths(x.get(key), y.get(key), f"{prefix}/{key}", limit)
            if len(out) >= limit:
                break
        return out[:limit]
    if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        out = []
        for i, (u, v) in enumerate(zip(x, y)):
            out += _paths(u, v, f"{prefix}/{i}", limit)
            if len(out) >= limit:
                break
        return out[:limit]
    return [(prefix or "/", (x, y))]


def first_divergence(a: list[Event], b: list[Event]) -> Divergence | None:
    """The first position where two traces differ, or None if they are identical."""
    for i, (x, y) in enumerate(zip(a, b)):
        if (x.type, x.name, x.kind) != (y.type, y.name, y.kind):
            return Divergence(i, DIFFERENT_CALL, x, y)
        if x.request != y.request:
            return Divergence(i, DIFFERENT_REQUEST, x, y, *_diff(x.request, y.request, "request"))
        if x.outcome != y.outcome or x.fault != y.fault:
            return Divergence(i, SAME_REQUEST_DIFFERENT_OUTCOME, x, y,
                              *_diff({"outcome": x.outcome, "fault": x.fault}, {"outcome": y.outcome, "fault": y.fault}))
    if len(a) != len(b):
        n = min(len(a), len(b))
        return Divergence(n, LENGTH, a[n] if n < len(a) else None, b[n] if n < len(b) else None)
    return None

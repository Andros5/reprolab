"""Reduce a failing trace to a smaller one that still violates the same property.

The search is delta debugging (ddmin) over the events of a trace, constrained so that
every candidate is closed under dependencies: an event is kept only together with the
events it depends on. A candidate is accepted when it is a well-formed trace and the
same invariant is still violated at the same anchor event, so the reduction cannot
slide to a different violation.

Guarantees and limits:
- The result is 1-minimal: removing any single remaining event (together with the
  events that depend on it) loses the violation. It is not a global minimum.
- The result is a trace, not an execution. It isolates what the invariant needs to see,
  and serves as a regression fixture for the property, but the original code would not
  necessarily produce it, so it cannot be replayed against that code. Reductions that
  re-execute (fewer injected faults, recorded again) belong to the explorer (H4).
- Dependencies are the recorded ones (data flow, plus any declared explicitly).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from reprolab.events import Event, SchemaError, validate_trace
from reprolab.invariants import Invariant, Violation, check


class NotReproduced(ValueError):
    """The trace does not exhibit the violation that was asked to be preserved."""


@dataclass(frozen=True)
class Reduction:
    events: list[Event]
    invariant: str
    anchor: int
    violation: Violation  # the preserved violation, as seen on the reduced trace
    original_events: int
    tests: int  # distinct candidates evaluated
    seconds: float

    @property
    def kept(self) -> list[int]:
        return [e.seq for e in self.events]


def _closure_up(selected: Iterable[int], by_seq: dict[int, Event]) -> frozenset[int]:
    """``selected`` plus everything it transitively depends on."""
    out, stack = set(), list(selected)
    while stack:
        s = stack.pop()
        if s not in out:
            out.add(s)
            stack.extend(by_seq[s].deps)
    return frozenset(out)


def _without(current: frozenset[int], removed: Iterable[int], dependents: dict[int, set[int]]) -> frozenset[int]:
    """``current`` minus ``removed`` and everything that transitively depends on it."""
    gone, stack = set(), list(removed)
    while stack:
        s = stack.pop()
        if s not in gone:
            gone.add(s)
            stack.extend(dependents.get(s, ()))
    return current - gone


def _chunks(items: list[int], n: int) -> list[list[int]]:
    size, rest = divmod(len(items), n)
    out, start = [], 0
    for i in range(n):
        end = start + size + (1 if i < rest else 0)
        if end > start:
            out.append(items[start:end])
        start = end
    return out


def reduce_trace(events: list[Event], holds: Callable[[list[Event]], bool]) -> tuple[list[Event], int]:
    """Smallest dependency-closed subtrace found for which ``holds`` is true.

    Returns the subtrace and the number of distinct candidates evaluated.
    """
    by_seq = {e.seq: e for e in events}
    dependents: dict[int, set[int]] = {}
    for e in events:
        for d in e.deps:
            dependents.setdefault(d, set()).add(e.seq)
    cache: dict[frozenset[int], bool] = {}

    def test(keep: frozenset[int]) -> bool:
        if keep not in cache:
            candidate = [by_seq[s] for s in sorted(keep)]
            try:
                validate_trace(candidate, contiguous=False)
            except SchemaError:
                cache[keep] = False
            else:
                cache[keep] = holds(candidate)
        return cache[keep]

    current = frozenset(by_seq)
    if not test(current):
        raise NotReproduced("the property does not fail on the full trace")

    n = 2
    while len(current) >= 2:
        items = sorted(current)
        chunks = _chunks(items, min(n, len(items)))
        progressed = False
        for chunk in chunks:  # 1. keep only one chunk (plus its dependencies)
            candidate = _closure_up(chunk, by_seq)
            if len(candidate) < len(current) and test(candidate):
                current, n, progressed = candidate, 2, True
                break
        if not progressed:
            for chunk in chunks:  # 2. remove one chunk (and what depends on it)
                candidate = _without(current, chunk, dependents)
                if len(candidate) < len(current) and test(candidate):
                    current, n, progressed = candidate, max(n - 1, 2), True
                    break
        if not progressed:
            if n >= len(items):
                break
            n = min(2 * n, len(items))

    # 3. Make 1-minimality explicit: no single event (with its dependents) can go.
    changed = True
    while changed:
        changed = False
        for s in sorted(current, reverse=True):
            candidate = _without(current, [s], dependents)
            if candidate != current and test(candidate):
                current, changed = candidate, True
                break

    return [by_seq[s] for s in sorted(current)], len(cache)


def reduce_violation(events: list[Event], invariants: list[Invariant], invariant: str | None = None,
                     anchor: int | None = None) -> Reduction:
    """Reduce ``events`` while ``invariant`` stays violated at event ``anchor``.

    By default the invariant is the only one violated and the anchor is its first
    violation; both must be given explicitly when that is ambiguous.
    """
    violations = check(events, invariants)
    names = sorted({v.invariant for v in violations})
    if not violations:
        raise NotReproduced("no invariant is violated on this trace")
    if invariant is None:
        if len(names) > 1:
            raise ValueError(f"several invariants are violated ({', '.join(names)}); choose one")
        invariant = names[0]
    matching = [v for v in violations if v.invariant == invariant]
    if not matching:
        raise NotReproduced(f"{invariant!r} is not violated on this trace (violated: {', '.join(names) or 'none'})")
    if anchor is None:
        anchor = matching[0].seq
    elif not any(v.seq == anchor for v in matching):
        raise NotReproduced(f"{invariant!r} is not violated at event #{anchor} "
                            f"(it is at {', '.join(f'#{v.seq}' for v in matching)})")

    def same_violation(candidate: list[Event]) -> bool:
        return any(v.invariant == invariant and v.seq == anchor for v in check(candidate, invariants))

    start = time.perf_counter()
    reduced, tests = reduce_trace(events, same_violation)
    seconds = time.perf_counter() - start
    kept_violation = next(v for v in check(reduced, invariants) if v.invariant == invariant and v.seq == anchor)
    return Reduction(reduced, invariant, anchor, kept_violation, len(events), tests, seconds)

"""Bounded, seeded exploration of fault schedules.

Given a scenario that can record against a real (local) environment, the explorer runs
it under many fault schedules and reports which business properties fail.

- **Space.** A fault is (call name, occurrence, kind). Call sites are discovered from the
  runs themselves: a fault-free baseline first, then every run adds the sites it reached
  (retries and lookups only appear under faults), plus ``extra_occurrences`` beyond the
  last one seen. A schedule is a set of at most ``max_faults`` faults on distinct sites.
- **Order.** Single faults first, exhaustively, in discovery order. Then coverage-guided
  extensions: when a schedule reaches call sites the baseline never reached (a retry, a
  lookup, a call after a restart), it is extended with one fault on each of those sites,
  because a second fault matters most on the paths the first one opened. Then the
  remaining schedules of 2, 3, ... faults over the known sites, in an order shuffled by
  ``seed``. Runs stop when the budget is spent or the space is exhausted. The same seed
  gives the same schedules, and on a deterministic environment the same verdicts.
- **Verdicts.** Each run is classified: a property violation on the trace, a failure only
  the oracle sees (real state wrong, trace clean), an unhandled exception, or fine.
  Findings are grouped by signature.
- **Counterexamples.** The first schedule of each signature is reduced by re-execution:
  faults are removed one at a time, recording again each time, while the same signature
  still appears (1-minimal). The trace of a property violation is then reduced as in H2.

What it does not claim: finding nothing means nothing was found within the explored
schedules. It does not show that the system is correct.
"""

from __future__ import annotations

import itertools
import random
import time
from dataclasses import dataclass, field
from math import comb
from pathlib import Path
from typing import Any, Callable, Iterable

from reprolab import scenario as rl
from reprolab.events import CALL, FAULT_KINDS, RESTART, Event
from reprolab.invariants import Violation
from reprolab.reduce import reduce_violation
from reprolab.scenario import Outcome, Scenario
from reprolab.session import Fault
from reprolab.store import REDUCED, Recording, save_run

PROPERTY = "property"
ORACLE_ONLY = "oracle-only"
UNHANDLED = "unhandled"

Schedule = tuple[Fault, ...]


def _schedule(faults: Iterable[Fault]) -> Schedule:
    return tuple(sorted(faults, key=lambda f: (f.name, f.occurrence, f.kind)))


def fmt(schedule: Schedule) -> str:
    return ", ".join(f"{f.name}:{f.occurrence}:{f.kind}" for f in schedule) or "no faults"


@dataclass(frozen=True)
class Finding:
    category: str
    signature: str
    message: str
    anchor: int | None = None  # seq of the violating event, for property findings


def classify(scenario: Scenario, out: Outcome) -> list[Finding]:
    by_seq = {e.seq: e for e in out.events}
    findings = [Finding(PROPERTY, f"{v.invariant} at {by_seq[v.seq].name}", str(v), v.seq) for v in out.violations]
    result = out.result if isinstance(out.result, dict) else {}
    if result.get("state") in ("unhandled", "crashed"):
        last = next((e.name for e in reversed(out.events) if e.type == CALL), "start")
        findings.append(Finding(UNHANDLED, f"{result.get('error', result['state'])} after {last}",
                                f"{result.get('error', result['state'])}: {result.get('message', '')}"))
    if not out.violations and scenario.oracle_check and out.oracle is not None:
        message = scenario.oracle_check(out.oracle)
        if message:
            findings.append(Finding(ORACLE_ONLY, message, f"{message}, but no property is violated on the trace"))
    unique: dict[str, Finding] = {}
    for f in findings:
        unique.setdefault(f.signature, f)
    return list(unique.values())


@dataclass
class Counterexample:
    category: str
    signature: str
    message: str
    first_run: int  # index of the run that found it (0 = baseline)
    first_seconds: float
    schedule: Schedule
    hits: int = 1
    minimal: Schedule = ()
    reexecutions: int = 0
    trace_events: int | None = None
    reduced_events: int | None = None
    run_ids: dict[str, str] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)  # the minimal run, for viewing
    violations: list[Violation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "signature": self.signature, "message": self.message,
                "first_run": self.first_run, "first_seconds": round(self.first_seconds, 3),
                "schedule": fmt(self.schedule), "hits": self.hits, "minimal_schedule": fmt(self.minimal),
                "faults_before": len(self.schedule), "faults_after": len(self.minimal),
                "reexecutions": self.reexecutions, "trace_events": self.trace_events,
                "reduced_events": self.reduced_events, "run_ids": self.run_ids}


@dataclass
class Report:
    target: str
    seed: int
    budget: int
    max_faults: int
    kinds: tuple[str, ...]
    runs: int = 0  # schedules run, not counting the baseline
    seconds: float = 0.0
    reduction_seconds: float = 0.0
    sites: list[tuple[str, int]] = field(default_factory=list)
    explored: dict[int, int] = field(default_factory=dict)  # schedule size -> schedules run
    space: dict[int, int] = field(default_factory=dict)  # schedule size -> schedules over the known sites
    exhausted: bool = False
    schedules: list[str] = field(default_factory=list)  # in run order, for reproducibility checks
    counterexamples: list[Counterexample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "seed": self.seed, "budget": self.budget, "max_faults": self.max_faults,
                "kinds": list(self.kinds), "runs": self.runs, "seconds": round(self.seconds, 3),
                "runs_per_second": round(self.runs / self.seconds, 1) if self.seconds else None,
                "reduction_seconds": round(self.reduction_seconds, 3),
                "sites": [f"{n}#{k}" for n, k in self.sites],
                "explored": {str(k): v for k, v in sorted(self.explored.items())},
                "space": {str(k): v for k, v in sorted(self.space.items())}, "exhausted": self.exhausted,
                "counterexamples": [c.to_dict() for c in self.counterexamples],
                "caveat": CAVEAT}

    def describe(self) -> str:
        lines = [f"Explored {self.target} (seed {self.seed}): baseline + {self.runs} schedules of up to "
                 f"{self.max_faults} faults, budget {self.budget}, {self.seconds:.1f}s "
                 f"({self.runs / self.seconds if self.seconds else 0:.0f} runs/s)",
                 f"Fault kinds (simulated): {', '.join(self.kinds)}",
                 f"Call sites reached: {', '.join(f'{n}#{k}' for n, k in self.sites)}"]
        for size in sorted(self.space):
            lines.append(f"  schedules of {size} fault(s): explored {self.explored.get(size, 0)} of "
                         f"{self.space[size]} over the known sites")
        lines.append("  space exhausted" if self.exhausted else "  space NOT exhausted: the budget ran out first")
        if not self.counterexamples:
            lines.append("No finding within the explored schedules.")
        for c in self.counterexamples:
            lines.append(f"[{c.category}] {c.signature}")
            lines.append(f"   {c.message}")
            lines.append(f"   first at run {c.first_run} ({c.first_seconds:.2f}s), {c.hits} run(s) in total; "
                         f"schedule: {fmt(c.schedule)}")
            lines.append(f"   minimal schedule ({len(c.schedule)} -> {len(c.minimal)} faults, "
                         f"{c.reexecutions} re-executions): {fmt(c.minimal)}")
            if c.reduced_events is not None:
                lines.append(f"   trace of the minimal run reduced {c.trace_events} -> {c.reduced_events} events")
            if c.run_ids:
                lines.append("   runs: " + ", ".join(f"{k} {v}" for k, v in c.run_ids.items()))
        lines.append(CAVEAT)
        return "\n".join(lines)


CAVEAT = ("Only the schedules above were tried: a finding is a reproducible counterexample, "
          "but no finding does not show the system is correct.")


class _Space:
    """Call sites discovered so far and the schedules not yet tried, in a seeded order."""

    def __init__(self, kinds: tuple[str, ...], max_faults: int, extra: int, rng: random.Random):
        self.kinds, self.max_faults, self.extra, self.rng = kinds, max_faults, extra, rng
        self.sites: list[tuple[str, int]] = []
        self.singles: list[Schedule] = []
        self.extensions: list[Schedule] = []
        self.baseline: set[tuple[str, int]] | None = None
        self.queue: list[Schedule] = []
        self.size = 2
        self.tried: set[Schedule] = set()

    def learn(self, events: list[Event], schedule: Schedule = ()) -> None:
        counts: dict[str, int] = {}
        for e in events:
            if e.type == CALL and e.name != RESTART:
                counts[e.name] = counts.get(e.name, 0) + 1
        reached = [(name, k) for name, n in counts.items() for k in range(1, n + 1)]
        if self.baseline is None:
            self.baseline = set(reached)
        elif len(schedule) < self.max_faults:
            used = {(f.name, f.occurrence) for f in schedule}
            for site in reached:
                if site not in self.baseline and site not in used:
                    self.extensions.extend(_schedule([*schedule, Fault(site[0], site[1], kind)])
                                           for kind in self.kinds)
        for name, n in counts.items():
            for k in range(1, n + self.extra + 1):
                if (name, k) not in self.sites:
                    self.sites.append((name, k))
                    self.singles.extend(_schedule([Fault(name, k, kind)]) for kind in self.kinds)

    def faults(self) -> list[Fault]:
        return [Fault(n, k, kind) for n, k in self.sites for kind in self.kinds]

    def next(self) -> Schedule | None:
        for pending in (self.singles, self.extensions):
            while pending:
                s = pending.pop(0)
                if s not in self.tried:
                    return s
        while self.size <= self.max_faults:
            while self.queue:
                s = self.queue.pop()
                if s not in self.tried:
                    return s
            fresh = [s for s in self._combinations(self.size) if s not in self.tried]
            if fresh:
                self.rng.shuffle(fresh)
                self.queue = fresh[::-1]  # pop() from the end keeps the shuffled order
                continue
            self.size += 1
        return None

    def _combinations(self, size: int) -> list[Schedule]:
        out = []
        for sites in itertools.combinations(self.sites, size):
            for kinds in itertools.product(self.kinds, repeat=size):
                out.append(_schedule(Fault(n, k, kind) for (n, k), kind in zip(sites, kinds)))
        return out

    def count(self, size: int) -> int:
        return comb(len(self.sites), size) * len(self.kinds) ** size


def _shrink(scenario: Scenario, schedule: Schedule, signature: str, out: Outcome) -> tuple[Schedule, int, Outcome]:
    """Remove faults one at a time, re-executing, while the signature still appears.
    ``out`` is the run of the full schedule; it stands if no fault can be removed."""
    runs = 0
    current = schedule
    changed = True
    while changed and current:
        changed = False
        for f in current:
            candidate = tuple(x for x in current if x != f)
            attempt = rl.record(scenario, list(candidate))
            runs += 1
            if any(c.signature == signature for c in classify(scenario, attempt)):
                current, out, changed = candidate, attempt, True
                break
    return current, runs, out


def explore(scenario: Scenario, *, seed: int = 0, budget: int = 100, max_faults: int = 2,
            kinds: Iterable[str] = FAULT_KINDS, extra_occurrences: int = 1, reduce: bool = True,
            target: str = "", db: str | Path | None = None,
            progress: Callable[[int, Schedule, list[Finding]], None] | None = None) -> Report:
    kinds = tuple(kinds)
    unknown = set(kinds) - set(FAULT_KINDS)
    if unknown:
        raise ValueError(f"unknown fault kinds: {sorted(unknown)}")
    report = Report(target or scenario.name, seed, budget, max_faults, kinds)
    space = _Space(kinds, max_faults, extra_occurrences, random.Random(seed))
    found: dict[str, Counterexample] = {}
    outcomes: dict[str, Outcome] = {}
    start = time.perf_counter()

    def note(index: int, schedule: Schedule, out: Outcome) -> None:
        findings = classify(scenario, out)
        for f in findings:
            if f.signature in found:
                found[f.signature].hits += 1
            else:
                found[f.signature] = Counterexample(f.category, f.signature, f.message, index,
                                                    time.perf_counter() - start, schedule)
                outcomes[f.signature] = out
        if progress:
            progress(index, schedule, findings)

    baseline = rl.record(scenario, [])
    space.learn(baseline.events)
    note(0, (), baseline)
    while report.runs < budget:
        schedule = space.next()
        if schedule is None:
            report.exhausted = True
            break
        space.tried.add(schedule)
        out = rl.record(scenario, list(schedule))
        report.runs += 1
        report.explored[len(schedule)] = report.explored.get(len(schedule), 0) + 1
        report.schedules.append(fmt(schedule))
        space.learn(out.events, schedule)
        note(report.runs, schedule, out)
    report.seconds = time.perf_counter() - start
    report.sites = list(space.sites)
    report.space = {size: space.count(size) for size in range(1, max_faults + 1)}

    reduce_start = time.perf_counter()
    for signature, c in found.items():
        out = outcomes[signature]
        if reduce:
            c.minimal, c.reexecutions, out = _shrink(scenario, c.schedule, signature, out)
        else:
            c.minimal = c.schedule
        finding = next(f for f in classify(scenario, out) if f.signature == signature)
        c.trace_events = len(out.events)
        c.events, c.violations = list(out.events), list(out.violations)
        reduced = None
        if reduce and finding.category == PROPERTY:
            invariant = signature.split(" at ")[0]
            reduced = reduce_violation(out.events, list(scenario.invariants), invariant, finding.anchor)
            c.reduced_events = len(reduced.events)
        if db is not None:
            faults = [f.to_dict() for f in c.minimal]
            minimal_id = save_run(db, Recording(out.events, label=f"explore {signature} (minimal)",
                                                target=target or None, faults=faults,
                                                extra={"explore": {"seed": seed, "signature": signature,
                                                                   "first_schedule": fmt(c.schedule)}}))
            c.run_ids["minimal"] = minimal_id
            if reduced is not None:
                c.run_ids["reduced"] = save_run(db, Recording(
                    reduced.events, label=f"explore {signature} (reduced)", origin=REDUCED, target=target or None,
                    faults=faults, reduced_from={"run": minimal_id, "invariant": reduced.invariant,
                                                 "anchor": reduced.anchor, "kept": reduced.kept,
                                                 "original_events": reduced.original_events,
                                                 "tests": reduced.tests, "seconds": round(reduced.seconds, 6)}))
    report.reduction_seconds = time.perf_counter() - reduce_start
    order = {PROPERTY: 0, UNHANDLED: 1, ORACLE_ONLY: 2}
    report.counterexamples = sorted(found.values(), key=lambda c: (order[c.category], c.first_run))
    return report

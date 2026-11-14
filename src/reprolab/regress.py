"""Differential replay: run old recordings against a new version of the code.

Every recording is a regression test waiting to happen. For each one, the new code is
first replayed offline against it:

- **compatible**: the new code makes exactly the recorded calls with the recorded
  requests. The recording still is a faithful test of the new code, offline.
- **incompatible from event #k**: the new code does something the recording does not
  contain (another call, another request, or it stops earlier). The recording can no
  longer answer for the new code past that point, and the report says so explicitly
  instead of guessing.

An incompatible recording is not thrown away. If the scenario has a local environment,
the new code is recorded again under the same fault plan (each fault re-applied by call
name and occurrence), and the two traces are compared: the property verdict before and
after, the first divergence, and which planned faults actually fired in the new run.

Verdicts: **fixed** (violated before, holds now), **still failing**, **regressed**
(held before, violated now), **still passing**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reprolab import scenario as rl
from reprolab.diff import Divergence, first_divergence
from reprolab.events import Event
from reprolab.invariants import Violation, check
from reprolab.scenario import Scenario, load_target
from reprolab.session import Fault, ReplayDivergence
from reprolab.store import RECORDED, Recording

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
NOT_REPLAYABLE = "not replayable"

FIXED = "fixed"
STILL_FAILING = "still failing"
REGRESSED = "regressed"
STILL_PASSING = "still passing"
UNKNOWN = "unknown"


@dataclass
class RegressionResult:
    run_id: str | None
    label: str
    new_target: str
    compatibility: str
    divergence: str | None = None  # why the recording stopped matching
    divergence_seq: int | None = None  # recorded event where it stopped
    reproduced: int = 0  # events that matched before that
    rerecorded: bool = False
    verdict: str = UNKNOWN
    old_violations: list[str] = field(default_factory=list)
    new_violations: list[str] = field(default_factory=list)
    faults_planned: list[str] = field(default_factory=list)
    faults_fired: list[str] = field(default_factory=list)
    old_events: list[Event] = field(default_factory=list)
    new_events: list[Event] = field(default_factory=list)
    first_difference: Divergence | None = None
    note: str = ""
    old_violation_objects: list[Violation] = field(default_factory=list)
    new_violation_objects: list[Violation] = field(default_factory=list)

    @property
    def gate_fails(self) -> bool:
        return self.verdict in (STILL_FAILING, REGRESSED)

    def describe(self) -> str:
        head = f"{self.run_id or '-':12}  {self.verdict:13}  {self.compatibility}"
        if self.compatibility == INCOMPATIBLE:
            head += (f" from #{self.divergence_seq}" if self.divergence_seq else " at the end") + \
                    f" ({self.reproduced} events matched)"
        lines = [head + f"  {self.label}"]
        if self.divergence:
            lines.append(f"      replay: {self.divergence[:160]}")
        if self.rerecorded:
            missed = sorted(set(self.faults_planned) - set(self.faults_fired))
            lines.append(f"      re-recorded under the same fault plan: {', '.join(self.faults_planned) or 'none'}"
                         + (f"; not reached by the new code: {', '.join(missed)}" if missed else ""))
            if self.first_difference:
                lines.append(f"      first difference at position {self.first_difference.position + 1}: "
                             f"{self.first_difference.kind}")
        for v in self.old_violations:
            lines.append(f"      before: {v}")
        for v in self.new_violations:
            lines.append(f"      now:    {v}")
        if self.note:
            lines.append(f"      {self.note}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in {
            "run_id": self.run_id, "label": self.label, "new_target": self.new_target,
            "compatibility": self.compatibility, "divergence": self.divergence,
            "divergence_seq": self.divergence_seq, "reproduced": self.reproduced, "rerecorded": self.rerecorded,
            "verdict": self.verdict, "old_violations": self.old_violations, "new_violations": self.new_violations,
            "faults_planned": self.faults_planned, "faults_fired": self.faults_fired,
            "first_difference": (self.first_difference.describe() if self.first_difference else None),
            "note": self.note}.items()}


def _verdict(before: bool, now: bool) -> str:
    return {(True, False): FIXED, (True, True): STILL_FAILING, (False, True): REGRESSED,
            (False, False): STILL_PASSING}[(before, now)]


def _fault_label(f: dict) -> str:
    return f"{f['name']}:{f['occurrence']}:{f['kind']}"


def _fired(events: list[Event]) -> list[str]:
    counts: dict[str, int] = {}
    fired = []
    for e in events:
        if e.type != "call":
            continue
        counts[e.name] = counts.get(e.name, 0) + 1
        if e.fault:
            fired.append(f"{e.name}:{counts[e.name]}:{e.fault['kind']}")
    return fired


def regress(recording: Recording, new: Scenario, new_target: str = "", *, rerecord: bool = True) -> RegressionResult:
    result = RegressionResult(recording.id, recording.label, new_target or new.name, NOT_REPLAYABLE,
                              faults_planned=[_fault_label(f) for f in recording.faults],
                              old_events=list(recording.events))
    old_invariants = list(new.invariants)
    if recording.target:
        try:
            old_invariants = list(load_target(recording.target).invariants)
        except (ImportError, ValueError):
            result.note = f"old target {recording.target} not importable; judged with the new scenario's invariants"
    result.old_violation_objects = check(recording.events, old_invariants)
    result.old_violations = [str(v) for v in result.old_violation_objects]
    before = bool(result.old_violations)

    if recording.origin != RECORDED:
        result.note = f"a {recording.origin} run is not an execution of this code; it is not replayed"
        return result
    if new.run is None or new.offline is None:
        result.note = "the new scenario has no code to run"
        return result

    try:
        out = rl.replay(new, recording.events)
    except ReplayDivergence as exc:
        result.compatibility = INCOMPATIBLE
        result.divergence, result.divergence_seq, result.reproduced = str(exc), exc.seq, exc.reproduced
    else:
        result.compatibility = COMPATIBLE
        result.reproduced = len(out.events)
        result.new_events = out.events
        result.new_violations = [str(v) for v in out.violations]
        result.new_violation_objects = list(out.violations)
        result.verdict = _verdict(before, bool(out.violations))
        return result

    if not rerecord or new.live is None:
        result.note = result.note or "no local environment to re-record the new code; verdict unknown"
        return result
    faults = [Fault(f["name"], f["occurrence"], f["kind"]) for f in recording.faults]
    fresh = rl.record(new, faults)
    result.rerecorded = True
    result.new_events = fresh.events
    result.new_violations = [str(v) for v in fresh.violations]
    result.new_violation_objects = list(fresh.violations)
    result.faults_fired = _fired(fresh.events)
    result.first_difference = first_divergence(recording.events, fresh.events, ignore_nondeterminism=True)
    result.verdict = _verdict(before, bool(fresh.violations))
    return result

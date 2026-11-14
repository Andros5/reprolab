"""Command line: reprolab record | replay | show | list | reduce | export.

Runs are stored in one SQLite file: --db, else $REPROLAB_DB, else ./reprolab.db.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from reprolab.events import Event
from reprolab.invariants import Violation, check
from reprolab.reduce import NotReproduced, reduce_violation
from reprolab.scenario import Scenario, load_target, record, replay
from reprolab.session import Fault, ReplayDivergence
from reprolab.store import REDUCED, Recording, list_runs, load_run, save_run

DEFAULT_DB = "reprolab.db"


class CliError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def _print_trace(events: list[Event], violations: list[Violation]) -> None:
    flagged = {v.seq for v in violations}
    for e in events:
        print(("!! " if e.seq in flagged else "   ") + e.describe())


def _print_verdict(violations: list[Violation]) -> None:
    print("property:", "VIOLATED" if violations else "holds")
    for v in violations:
        print("  ", v)


def _scenario_for(rec: Recording, override: str | None) -> Scenario:
    target = override or rec.target
    if not target:
        raise CliError(f"run {rec.id} has no target; pass --target module:attribute")
    return load_target(target)


def cmd_record(args: argparse.Namespace) -> int:
    scenario = load_target(args.target)
    faults = [Fault.parse(f) for f in args.fault]
    out = record(scenario, faults)
    _print_trace(out.events, out.violations)
    print("result:", out.result)
    if out.oracle is not None:
        print("oracle (real state, not part of the trace):", out.oracle)
    _print_verdict(out.violations)
    label = args.label or " ".join([scenario.name] + [f"{f.name}:{f.occurrence}:{f.kind}" for f in faults])
    rec = Recording(out.events, label=label, target=args.target, faults=[f.to_dict() for f in faults])
    print(f"saved run {save_run(args.db, rec)} in {args.db}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    rec = load_run(args.db, args.run)
    if rec.origin == REDUCED:
        raise CliError(f"run {rec.id} is a reduced trace, not an execution: the code is not expected to "
                       "reproduce it. Replay its original run "
                       f"{rec.reduced_from['run']} instead, or check it with 'show'.", code=1)
    scenario = _scenario_for(rec, args.target)
    try:
        out = replay(scenario, rec.events)
    except ReplayDivergence as exc:
        print(f"DIVERGED: {exc}")
        return 1
    _print_trace(out.events, out.violations)
    print("result:", out.result)
    print(f"replayed offline: {len(out.events)} of {len(rec.events)} recorded events reproduced, network disabled")
    print("note: recorded outcomes were reused; this does not show a service or LLM would answer the same again")
    _print_verdict(out.violations)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    rec = load_run(args.db, args.run)
    print(f"run {rec.id}  {rec.label!r}")
    print(f"created {rec.created_at}, schema v{rec.stored_version}"
          + (" (migrated to v2 on read)" if rec.stored_version != 2 else ""))
    print(f"origin: {rec.origin}" + (" (a trace, not an execution)" if rec.origin == REDUCED else ""))
    print(f"target: {rec.target or '-'}")
    plan = ", ".join(f"{f['name']}:{f['occurrence']}:{f['kind']}" for f in rec.faults) or "none"
    print(f"injected faults (simulated): {plan}")
    if rec.reduced_from:
        r = rec.reduced_from
        print(f"reduced from run {r['run']}: {r['original_events']} -> {len(rec.events)} events, keeping "
              f"{r['invariant']} violated at #{r['anchor']} ({r['tests']} candidates, {r['seconds']:.3f}s)")
    violations: list[Violation] = []
    try:
        violations = check(rec.events, list(_scenario_for(rec, args.target).invariants))
    except (CliError, ImportError, ValueError) as exc:
        print(f"(invariants not checked: {exc})")
    _print_trace(rec.events, violations)
    _print_verdict(violations)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    runs = list_runs(args.db) if Path(args.db).exists() else []
    if not runs:
        print(f"no runs in {args.db}")
        return 0
    print(f"{'id':12}  {'created':25}  {'origin':8}  {'events':>6}  label")
    for r in runs:
        print(f"{r['id']:12}  {r['created_at']:25}  {r['origin']:8}  {r['events']:>6}  {r['label']}")
    return 0


def cmd_reduce(args: argparse.Namespace) -> int:
    rec = load_run(args.db, args.run)
    scenario = _scenario_for(rec, args.target)
    try:
        red = reduce_violation(rec.events, list(scenario.invariants), args.invariant, args.anchor)
    except NotReproduced as exc:
        print(f"cannot reduce: {exc}")
        return 1
    print(f"kept {red.invariant} violated at #{red.anchor}: {red.original_events} -> {len(red.events)} events "
          f"({red.tests} candidates tested, {red.seconds:.3f}s)")
    _print_trace(red.events, [red.violation])
    print("  ", red.violation)
    out = Recording(
        red.events, label=f"reduced {rec.id} {red.invariant}@{red.anchor}", origin=REDUCED,
        target=rec.target, faults=rec.faults,
        reduced_from={"run": rec.id, "invariant": red.invariant, "anchor": red.anchor, "kept": red.kept,
                      "original_events": red.original_events, "tests": red.tests,
                      "seconds": round(red.seconds, 6)})
    print(f"saved reduced run {save_run(args.db, out)} (original {rec.id} unchanged)")
    print("note: 1-minimal, not a global minimum; a reduced trace is a regression fixture, not a replayable run")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    doc = load_run(args.db, args.run).to_doc()
    if args.output:
        Path(args.output).write_text(doc, encoding="utf-8", newline="\n")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(doc)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reprolab", description="Record, replay and reduce failures of workflows.")
    p.add_argument("--db", default=os.environ.get("REPROLAB_DB", DEFAULT_DB),
                   help=f"SQLite file with the runs (default: $REPROLAB_DB or {DEFAULT_DB})")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("record", help="run a scenario for real, with optional injected faults, and save it")
    s.add_argument("target", help="scenario as module:attribute")
    s.add_argument("--fault", action="append", default=[], metavar="NAME:N:KIND",
                   help="inject KIND on the N-th call named NAME (repeatable), e.g. portal.submit:1:lost_response")
    s.add_argument("--label", default="")
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("replay", help="re-run the scenario's code against a recording, offline")
    s.add_argument("run", help="run id or unique prefix")
    s.add_argument("--target", help="override the recorded target (e.g. new code)")
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("show", help="print a run's header, trace and violations")
    s.add_argument("run")
    s.add_argument("--target")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("list", help="list stored runs")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("reduce", help="shrink a trace while the same invariant stays violated")
    s.add_argument("run")
    s.add_argument("--invariant", help="invariant to preserve (default: the only one violated)")
    s.add_argument("--anchor", type=int, help="seq of the violation to preserve (default: the first)")
    s.add_argument("--target")
    s.set_defaults(fn=cmd_reduce)

    s = sub.add_parser("export", help="write a run as a portable JSON document")
    s.add_argument("run")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_export)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except (KeyError, ValueError, ImportError) as exc:
        print(f"error: {exc.args[0] if isinstance(exc, KeyError) else exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

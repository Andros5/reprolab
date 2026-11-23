"""Command line: reprolab record | replay | show | list | reduce | diff | explore | regress | html | export.

Runs are stored in one SQLite file: --db, else $REPROLAB_DB, else ./reprolab.db.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from reprolab import __version__
from reprolab.diff import first_divergence
from reprolab.events import FAULT_KINDS, SCHEMA_VERSION, Event
from reprolab.explore import PROPERTY, explore
from reprolab.invariants import Violation, check
from reprolab.reduce import NotReproduced, reduce_violation
from reprolab.regress import regress
from reprolab.scenario import Scenario, load_target, record, replay
from reprolab.session import Fault, ReplayDivergence
from reprolab.store import RECONSTRUCTED, RECORDED, REDUCED, Recording, list_runs, load_run, save_run

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
    if rec.origin == RECONSTRUCTED and not args.target:
        raise CliError(f"run {rec.id} was rebuilt from another system's logs. It is replayed by re-executing "
                       "that system's code through an adapter (for CitaLab: examples.citalab_r02.reexecute); "
                       "check it with 'show', compare it with 'diff' or shrink it with 'reduce'.", code=1)
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
          + (f" (migrated to v{SCHEMA_VERSION} on read)" if rec.stored_version != SCHEMA_VERSION else ""))
    note = {REDUCED: " (a trace, not an execution)",
            RECONSTRUCTED: " (rebuilt from another system's logs; [reconstructed] marks derived events)"}
    print(f"origin: {rec.origin}" + note.get(rec.origin, ""))
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


def cmd_diff(args: argparse.Namespace) -> int:
    a, b = load_run(args.db, args.a), load_run(args.db, args.b)
    print(f"A: run {a.id}  {a.label!r} ({len(a.events)} events)")
    print(f"B: run {b.id}  {b.label!r} ({len(b.events)} events)")
    divergence = first_divergence(a.events, b.events, ignore_nondeterminism=args.ignore_nondeterminism)
    if divergence is None:
        print("identical traces")
        return 0
    print(f"identical for the first {divergence.position} events, then:")
    print(divergence.describe())
    return 0


def cmd_explore(args: argparse.Namespace) -> int:
    scenario = load_target(args.target)
    kinds = tuple(k.strip() for k in args.kinds.split(",")) if args.kinds else FAULT_KINDS
    report = explore(scenario, seed=args.seed, budget=args.budget, max_faults=args.max_faults, kinds=kinds,
                     extra_occurrences=args.extra_occurrences, reduce=not args.no_reduce, target=args.target,
                     db=None if args.no_save else args.db)
    print(report.describe())
    if args.report:
        Path(args.report).write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8", newline="\n")
        print(f"wrote {args.report}")
    # Exit 1 when a business property was violated, so an exploration can gate a build.
    return 1 if any(c.category == PROPERTY for c in report.counterexamples) else 0


def cmd_regress(args: argparse.Namespace) -> int:
    new = load_target(args.target)
    if args.runs:
        ids = [r.strip() for r in args.runs.split(",") if r.strip()]
    else:
        ids = [r["id"] for r in list_runs(args.db) if r["origin"] == RECORDED
               and (args.from_target is None or r["target"] == args.from_target)
               and not r["label"].startswith("regress ")]
    if not ids:
        raise CliError("no recorded runs to replay; record some first or pass --runs", code=1)
    results = []
    for ref in ids:
        rec = load_run(args.db, ref)
        r = regress(rec, new, args.target, rerecord=not args.no_rerecord)
        if r.rerecorded:
            r.note = (r.note + "; " if r.note else "") + "new run " + save_run(args.db, Recording(
                r.new_events, label=f"regress {rec.id} under {args.target}", target=args.target,
                faults=rec.faults, extra={"regress_of": rec.id}))
        results.append(r)
        print(r.describe())
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    compatible = sum(r.compatibility == "compatible" for r in results)
    print(f"{len(results)} recordings against {args.target}: {compatible} still compatible offline; "
          + ", ".join(f"{n} {v}" for v, n in sorted(counts.items())))
    if args.report:
        Path(args.report).write_text(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False)
                                     + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.report}")
    # Exit 1 while any recorded failure still fails, or a passing one now fails.
    return 1 if any(r.gate_fails for r in results) else 0


def _invariants_for(rec: Recording, override: str | None) -> list:
    try:
        return list(_scenario_for(rec, override).invariants)
    except (CliError, ImportError, ValueError):
        return []


def cmd_html(args: argparse.Namespace) -> int:
    from reprolab import html as H

    rec = load_run(args.db, args.run)
    invariants = _invariants_for(rec, args.target)
    if args.compare:
        other = load_run(args.db, args.compare)
        divergence = first_divergence(rec.events, other.events, ignore_nondeterminism=args.ignore_nondeterminism)
        content = H.compare_view(rec.events, other.events, divergence, title_a=f"A · {rec.id} · {rec.label}",
                                 title_b=f"B · {other.id} · {other.label}",
                                 violations_a=check(rec.events, invariants),
                                 violations_b=check(other.events, _invariants_for(other, args.target)))
        sections = [("compare", "first divergence", f"{rec.id} and {other.id}", content)]
    elif rec.origin == REDUCED and rec.reduced_from:
        original = load_run(args.db, rec.reduced_from["run"])
        anchor, name = rec.reduced_from["anchor"], rec.reduced_from["invariant"]
        violation = next((v for v in check(rec.events, invariants) if v.seq == anchor and v.invariant == name), None)
        if violation is None:
            raise CliError(f"cannot re-check {name} at #{anchor} on run {rec.id}; pass --target", code=1)
        content = H.reduction_view(original.events, rec.events, violation, title=f"{original.id} · {original.label}")
        sections = [("reduction", "reduction", f"{rec.id}: {len(original.events)} to {len(rec.events)} events", content)]
    else:
        violations = check(rec.events, invariants)
        content = H.verdict_line(violations) + H.run_view(rec.events, violations, title=rec.label or rec.id,
                                                          meta=f"{rec.origin} · {rec.target or 'no target'}")
        sections = [("run", rec.origin, f"Run {rec.id}", content)]
    out = Path(args.output or f"reprolab-{rec.id}.html")
    out.write_text(H.page(f"Trace {rec.id}", sections), encoding="utf-8", newline="\n")
    print(f"wrote {out}")
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
    p.add_argument("--version", action="version",
                   version=f"reprolab {__version__} (event schema v{SCHEMA_VERSION})")
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

    s = sub.add_parser("diff", help="find the first event where two runs diverge, and how")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--ignore-nondeterminism", action="store_true",
                   help="compare random tokens and clock readings by order of appearance, not value")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("regress", help="replay stored recordings against a new version of the code")
    s.add_argument("--target", required=True, help="the new code, as module:attribute")
    s.add_argument("--from", dest="from_target", help="only recordings of this target (default: all recorded runs)")
    s.add_argument("--runs", help="comma-separated run ids or prefixes (default: all matching recorded runs)")
    s.add_argument("--no-rerecord", action="store_true",
                   help="do not re-record incompatible recordings under their fault plan")
    s.add_argument("--report", help="write the results as JSON to this file")
    s.set_defaults(fn=cmd_regress)

    s = sub.add_parser("explore", help="run a scenario under many fault schedules and reduce what fails")
    s.add_argument("target", help="scenario as module:attribute")
    s.add_argument("--seed", type=int, default=0, help="orders the random part of the search (default 0)")
    s.add_argument("--budget", type=int, default=200, help="schedules to run, not counting the baseline")
    s.add_argument("--max-faults", type=int, default=2, help="faults per schedule (default 2)")
    s.add_argument("--kinds", help=f"comma-separated fault kinds (default: all of {', '.join(FAULT_KINDS)})")
    s.add_argument("--extra-occurrences", type=int, default=1,
                   help="also target this many occurrences beyond the last one seen (default 1)")
    s.add_argument("--report", help="write the report as JSON to this file")
    s.add_argument("--no-reduce", action="store_true", help="keep the first schedule of each finding as is")
    s.add_argument("--no-save", action="store_true", help="do not store counterexample runs")
    s.set_defaults(fn=cmd_explore)

    s = sub.add_parser("html", help="write a visual HTML view of a run, a comparison or a reduction")
    s.add_argument("run")
    s.add_argument("--compare", metavar="RUN", help="show this run side by side, from the first divergence")
    s.add_argument("--ignore-nondeterminism", action="store_true")
    s.add_argument("--target", help="scenario whose invariants to check (default: the recorded target)")
    s.add_argument("-o", "--output", help="output file (default: reprolab-<run>.html)")
    s.set_defaults(fn=cmd_html)

    s = sub.add_parser("export", help="write a run as a portable JSON document")
    s.add_argument("run")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_export)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
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

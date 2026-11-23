"""Measure the explorer and the instrumentation:  python -m examples.portal_demo.metrics

1. Seeded regressions. Five client variants with known labels are explored with the same
   budget, under two fault sets (with and without worker crashes) and several seeds.
   Scored: defects found (a property violation on a defective variant), false alarms (a
   property violation on a correct one), runs and seconds to the first finding, and the
   size of the counterexamples before and after reduction.
2. Determinism. The same seed is run twice; the schedules and findings must be identical.
3. Overhead. Cost per boundary call, per real HTTP call to the local portal, and per
   stored event (disk and memory).

Writes docs/metrics.md and docs/metrics.json. Timings depend on the machine.
`--render-only` rewrites docs/metrics.md from docs/metrics.json without measuring again.
"""

from __future__ import annotations

import json
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc
from contextlib import closing
from pathlib import Path

from examples.portal_demo.applier import LABELS, PortalClient
from examples.portal_demo.portal import Portal
from examples.portal_demo.scenario import SCENARIOS
from reprolab import Recording, Session, save_run
from reprolab.events import CRASH_AFTER, FAULT_KINDS
from reprolab.explore import ORACLE_ONLY, PROPERTY, UNHANDLED, explore

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ("blind_retry", "retry_on_find_error", "reconciles_once", "reconciling", "journaled")
FAULT_SETS = {
    "all six kinds": FAULT_KINDS,
    "without crash_after": tuple(k for k in FAULT_KINDS if k != CRASH_AFTER),
}
SEEDS = (0, 1, 2)
BUDGET = 200


def defective(variant: str, fault_set: str) -> bool:
    if variant == "reconciling":
        return fault_set == "all six kinds"  # only a crash exposes it
    return variant != "journaled"


def seeded_regressions() -> list[dict]:
    rows = []
    for fault_set, kinds in FAULT_SETS.items():
        for variant in VARIANTS:
            runs = []
            for seed in SEEDS:
                r = explore(SCENARIOS[variant], seed=seed, budget=BUDGET, kinds=kinds)
                prop = [c for c in r.counterexamples if c.category == PROPERTY]
                runs.append({
                    "seed": seed, "found": bool(prop), "seconds": r.seconds, "runs": r.runs,
                    "first_run": prop[0].first_run if prop else None,
                    "first_seconds": prop[0].first_seconds if prop else None,
                    "faults_before": len(prop[0].schedule) if prop else None,
                    "faults_after": len(prop[0].minimal) if prop else None,
                    "trace_before": prop[0].trace_events if prop else None,
                    "trace_after": prop[0].reduced_events if prop else None,
                    "unhandled": sum(c.category == UNHANDLED for c in r.counterexamples),
                    "oracle_only": sum(c.category == ORACLE_ONLY for c in r.counterexamples),
                    "explored": r.explored, "space": r.space,
                })
            rows.append({"fault_set": fault_set, "variant": variant, "label": LABELS[variant],
                         "defective": defective(variant, fault_set), "runs": runs})
            print(f"  {fault_set:20} {variant:20} found in {sum(x['found'] for x in runs)}/{len(runs)} seeds")
    return rows


def determinism() -> dict:
    a = explore(SCENARIOS["reconciles_once"], seed=11, budget=120)
    b = explore(SCENARIOS["reconciles_once"], seed=11, budget=120)
    same = a.schedules == b.schedules and [(c.signature, c.first_run, c.hits) for c in a.counterexamples] == \
        [(c.signature, c.first_run, c.hits) for c in b.counterexamples]
    return {"seed": 11, "budget": 120, "identical": same}


def _per_call(fn, n: int) -> float:
    start = time.perf_counter()
    for i in range(n):
        fn(i)
    return (time.perf_counter() - start) / n


def overhead() -> dict:
    n = 20000
    direct = _per_call(lambda i: {"echo": i}, n)
    session = Session.record()
    recorded = _per_call(lambda i: session.call("svc", {"i": i}, lambda r: {"echo": r["i"]}), n)

    with Portal() as portal:
        client = PortalClient(portal.url)
        payload = {"candidate": "synthetic-candidate-1", "job": "job-42"}
        s = Session.record()
        for _ in range(50):  # warm up the server, the sockets and the code paths
            client.find(payload)
            s.call("portal.find", payload, client.find)
        direct_times, recorded_times = [], []
        for _ in range(300):  # alternate, so drift affects both sides equally
            t = time.perf_counter()
            client.find(payload)
            direct_times.append(time.perf_counter() - t)
            t = time.perf_counter()
            s.call("portal.find", payload, client.find)
            recorded_times.append(time.perf_counter() - t)
        http_direct = statistics.median(direct_times)
        http_recorded = statistics.median(recorded_times)

    events = Session.record()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for i in range(1000):
        events.call("portal.submit", {"candidate": "synthetic-candidate-1", "job": "job-42",
                                      "request_id": f"{i:032x}"}, lambda r: {"id": 1})
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    memory = sum(stat.size_diff for stat in after.compare_to(before, "filename")) / 1000

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "size.db"
        save_run(db, Recording([]))
        with closing(sqlite3.connect(db)) as c:
            empty = c.execute("PRAGMA page_count").fetchone()[0] * c.execute("PRAGMA page_size").fetchone()[0]
        save_run(db, Recording(events.finish()))
        with closing(sqlite3.connect(db)) as c:
            c.execute("VACUUM")
            full = c.execute("PRAGMA page_count").fetchone()[0] * c.execute("PRAGMA page_size").fetchone()[0]
    return {
        "boundary_call_direct_us": round(direct * 1e6, 2),
        "boundary_call_recorded_us": round(recorded * 1e6, 2),
        "http_call_direct_ms": round(http_direct * 1e3, 3),
        "http_call_recorded_ms": round(http_recorded * 1e3, 3),
        "http_overhead_percent": round((http_recorded - http_direct) / http_direct * 100, 1),
        "fixed_cost_share_of_http_percent": round((recorded - direct) / http_direct * 100, 2),
        "memory_bytes_per_event": round(memory),
        "disk_bytes_per_event": round((full - empty) / 1000),
    }


def _fmt(values: list, digits: int = 0) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "-"
    lo, hi = min(values), max(values)
    med = statistics.median(values)
    f = (lambda x: f"{x:.{digits}f}")
    return f(med) if lo == hi else f"{f(med)} ({f(lo)}–{f(hi)})"


def render(rows: list[dict], det: dict, cost: dict) -> str:
    out = ["# Measured results", "",
           "Generated by `python -m examples.portal_demo.metrics`. Timings depend on the machine; this run: "
           f"Python {platform.python_version()} on {platform.system()} {platform.release()}.", "",
           "## Seeded regressions", "",
           f"Five client variants with known labels, explored with a budget of {BUDGET} schedules of up to 2 "
           f"faults, seeds {', '.join(map(str, SEEDS))}. A variant counts as found when the explorer reports a "
           "violation of *no blind resubmit*. Values are medians, with the range across seeds in brackets.", ""]
    for fault_set in FAULT_SETS:
        out += [f"### Fault set: {fault_set}", "",
                "| Variant | Label | Found (seeds) | Runs to first | Seconds to first | Faults: first → minimal "
                "| Trace events: minimal run → reduced | Unhandled findings | Oracle-only findings |",
                "|---|---|---|---|---|---|---|---|---|"]
        for row in (r for r in rows if r["fault_set"] == fault_set):
            runs = row["runs"]
            verdict = "defective" if row["defective"] else "correct"
            note = {"reconciles_once": "needs two faults without a crash",
                    "reconciling": "only a crash exposes it"}.get(row["variant"])
            label = f"{verdict} ({note})" if note else verdict
            faults = (f"{_fmt([x['faults_before'] for x in runs])} → {_fmt([x['faults_after'] for x in runs])}"
                      if any(x["found"] for x in runs) else "-")
            trace = (f"{_fmt([x['trace_before'] for x in runs])} → {_fmt([x['trace_after'] for x in runs])}"
                     if any(x["found"] for x in runs) else "-")
            out.append(f"| `{row['variant']}` | {label} | {sum(x['found'] for x in runs)}/{len(runs)} | "
                       f"{_fmt([x['first_run'] for x in runs])} | {_fmt([x['first_seconds'] for x in runs], 2)} | "
                       f"{faults} | {trace} | {_fmt([x['unhandled'] for x in runs])} | "
                       f"{_fmt([x['oracle_only'] for x in runs])} |")
        out.append("")
    found = [(r, x) for r in rows for x in r["runs"]]
    tp = sum(x["found"] for r, x in found if r["defective"])
    pos = sum(1 for r, x in found if r["defective"])
    fp = sum(x["found"] for r, x in found if not r["defective"])
    neg = sum(1 for r, x in found if not r["defective"])
    speed = [x["runs"] / x["seconds"] for _, x in found]
    out += ["### Summary", "",
            f"- Defects found: **{tp}/{pos}** explorations of a defective variant.",
            f"- False alarms: **{fp}/{neg}** explorations of a correct variant.",
            f"- Throughput: {_fmt(speed)} runs per second (each run starts a fresh local portal).",
            "- Unhandled findings are `KeyError`s after an `invalid_output` fault in every client but "
            "`journaled`. Oracle-only findings come from `duplicate`: the portal is not idempotent, so a "
            "duplicated delivery stores two applications that no client can prevent or see in its trace.", "",
            "## Determinism", "",
            f"Two explorations with seed {det['seed']} and budget {det['budget']}: identical schedules and findings: "
            f"**{'yes' if det['identical'] else 'NO'}**.", "",
            "## Instrumentation overhead", "",
            "| Measure | Value |", "|---|---|",
            f"| Trivial in-process call, direct | {cost['boundary_call_direct_us']} µs |",
            f"| Same call recorded through a `Session` | {cost['boundary_call_recorded_us']} µs |",
            f"| HTTP lookup to the local portal, direct (median of 300) | {cost['http_call_direct_ms']} ms |",
            f"| Same lookup recorded (median of 300, alternated) | {cost['http_call_recorded_ms']} ms "
            f"({cost['http_overhead_percent']:+}%) |",
            f"| Fixed recording cost as a share of that HTTP call | {cost['fixed_cost_share_of_http_percent']}% |",
            f"| Memory per recorded event (small request) | {cost['memory_bytes_per_event']} bytes |",
            f"| SQLite disk per stored event (small request) | {cost['disk_bytes_per_event']} bytes |", "",
            "The per-call cost of recording (normalising, dependency inference, the event itself) is fixed, "
            "and small next to even a local HTTP call. The measured direct-versus-recorded difference on the "
            "HTTP call is larger than that fixed cost; the rest is variation between calls, which alternating "
            "300 samples and taking medians reduces but does not remove.",
            ""]
    return "\n".join(out)


def main() -> int:
    if "--render-only" in sys.argv:  # rewrite metrics.md from metrics.json, without measuring again
        data = json.loads((ROOT / "docs" / "metrics.json").read_text(encoding="utf-8"))
        (ROOT / "docs" / "metrics.md").write_text(
            render(data["seeded_regressions"], data["determinism"], data["overhead"]), encoding="utf-8", newline="\n")
        print("rewrote docs/metrics.md from docs/metrics.json")
        return 0
    print("Seeded regressions:")
    rows = seeded_regressions()
    print("Determinism and overhead...")
    det, cost = determinism(), overhead()
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "metrics.md").write_text(render(rows, det, cost), encoding="utf-8", newline="\n")
    (ROOT / "docs" / "metrics.json").write_text(
        json.dumps({"seeded_regressions": rows, "determinism": det, "overhead": cost}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print("wrote docs/metrics.md and docs/metrics.json")
    return 0 if det["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Export real ReproLab results for the demo video:  python -m examples.video_data [out.json]

Every number, event and terminal line in the video comes from this file, which runs the
actual cases. Run it with the CitaLab environment to include the re-execution results.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from examples.citalab_r02.importer import load_episodes, to_recording
from examples.citalab_r02.scenario import r02
from examples.portal_demo.applier import SUBMIT
from examples.portal_demo.scenario import INVARIANTS, SCENARIOS, target
from reprolab import Fault, Recording, check, reduce_violation
from reprolab import scenario as rl
from reprolab.diff import _brief, first_divergence
from reprolab.events import Event
from reprolab.explore import explore
from reprolab.regress import regress

ROOT = Path(__file__).resolve().parents[1]


def ev(e: Event, violations=(), **extra) -> dict:
    flagged = {v.seq for v in violations}
    if e.type != "call":
        summary = _brief(e.outcome.get("ok"), 22)
    elif e.ok:
        summary = f"→ {_brief(e.outcome['ok'], 30)}"
    else:
        summary = f"→ {(e.error or {}).get('type')} (effect {(e.error or {}).get('effect')})"
    return {"seq": e.seq, "type": e.type, "kind": e.kind, "name": e.name, "summary": summary,
            "fault": e.fault["kind"] if e.fault else None, "deps": list(e.deps),
            "violation": e.seq in flagged, "reconstructed": e.reconstructed, **extra}


def cli(*args: str) -> list[str]:
    out = subprocess.run([sys.executable, "-m", "reprolab", *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", cwd=ROOT)
    return [line.rstrip() for line in out.stdout.splitlines()]


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "video" / "public" / "data.json"
    data: dict = {}

    # 1. A lost response, recorded and replayed offline.
    rec = rl.record(SCENARIOS["blind_retry"], [Fault(SUBMIT, 1, "lost_response")])
    again = rl.replay(SCENARIOS["blind_retry"], rec.events)
    data["portal"] = {"events": [ev(e, rec.violations) for e in rec.events],
                      "violation": str(rec.violations[0]), "applications": rec.oracle["applications"],
                      "replay_identical": again.events == rec.events and again.result == rec.result,
                      "result": rec.result}

    # 2. Reduction of the longer flow.
    full = rl.record(SCENARIOS["blind_retry_full"], [Fault(SUBMIT, 1, "lost_response"), Fault(SUBMIT, 2, "rate_limited")])
    red = reduce_violation(full.events, list(INVARIANTS))
    kept = set(red.kept)
    data["reduction"] = {"events": [ev(e, [red.violation], kept=e.seq in kept) for e in full.events],
                         "before": red.original_events, "after": len(red.events), "tests": red.tests,
                         "anchor": red.anchor}

    # 3. The explorer on the reconciling client.
    outcomes: list[str] = []  # per schedule run, in order: the worst category it produced

    def progress(index, schedule, findings):
        if index:
            cats = {f.category for f in findings}
            outcomes.append(next((c for c in ("property", "unhandled", "oracle-only") if c in cats), "clean"))

    report = explore(SCENARIOS["reconciling"], seed=0, budget=200, target=target("reconciling"), progress=progress)
    data["explore"] = {
        "runs": report.runs, "seconds": round(report.seconds, 2), "runs_per_second": round(report.runs / report.seconds),
        "space": {str(k): v for k, v in report.space.items()},
        "explored": {str(k): v for k, v in report.explored.items()},
        "sites": [f"{n}#{k}" for n, k in report.sites],
        "schedules": report.schedules, "outcomes": outcomes,
        "findings": [{"category": c.category, "signature": c.signature, "first_run": c.first_run,
                      "hits": c.hits, "minimal": [f"{f.name}#{f.occurrence} {f.kind}" for f in c.minimal],
                      "trace": c.trace_events, "reduced": c.reduced_events} for c in report.counterexamples],
        "crash_trace": [ev(e, report.counterexamples[0].violations) for e in report.counterexamples[0].events],
    }

    # 4. Old recordings against the journaled client.
    plans = [("blind_retry", [Fault(SUBMIT, 1, "lost_response")]),
             ("reconciling", [Fault(SUBMIT, 1, "crash_after")]),
             ("reconciling", [Fault(SUBMIT, 1, "timeout"), Fault(SUBMIT, 2, "lost_response")]),
             ("blind_retry", [])]
    rows, compare = [], None
    for name, faults in plans:
        out = rl.record(SCENARIOS[name], faults)
        rec_ = Recording(out.events, label=name, target=target(name), faults=[f.to_dict() for f in faults])
        r = regress(rec_, SCENARIOS["journaled"], target("journaled"))
        rows.append({"label": name, "faults": [f"{f.kind} @ {f.name}#{f.occurrence}" for f in faults],
                     "verdict": r.verdict, "compatibility": r.compatibility, "divergence_seq": r.divergence_seq,
                     "matched": r.reproduced, "total": len(r.old_events)})
        if compare is None and r.rerecorded and name == "reconciling":
            d = r.first_difference
            compare = {"old": [ev(e, r.old_violation_objects) for e in r.old_events],
                       "new": [ev(e, r.new_violation_objects) for e in r.new_events],
                       "position": d.position, "kind": d.kind}
    data["regress"] = {"rows": rows, "compare": compare}

    # 5. CitaLab.
    recs = {ep.cell_id: to_recording(ep) for ep in load_episodes()}
    inv = list(r02.invariants)
    m5, h = recs["google:M5:N-R02:primary"], recs["google:H:N-R02:primary"]
    d = first_divergence(m5.events, h.events)
    hred = reduce_violation(h.events, inv)
    firsts = [next(e for e in recs[c].events if e.name == "llm.context") for c in
              ("google:M5:N-R02:primary", "google:H:N-R02:primary", "google:M5:N-CF-R02:counterfactual",
               "google:H:N-CF-R02:counterfactual")]
    hkept = set(hred.kept)
    data["citalab"] = {
        "agreement": sum(bool(check(r.events, inv)) != r.extra["citalab"]["oracle_goal"]["pass"] for r in recs.values()),
        "episodes": len(recs), "failures": sum(bool(check(r.events, inv)) for r in recs.values()),
        "identical_requests": len(firsts) if all(f.request == firsts[0].request for f in firsts) else 0,
        "answers": [f.outcome["ok"]["intent"] for f in firsts],
        "m5": [ev(e, check(m5.events, inv)) for e in m5.events[:10]],
        "h": [ev(e, check(h.events, inv)) for e in h.events[:10]],
        "divergence": {"position": d.position, "kind": d.kind,
                       "values": [[p, x, y] for p, (x, y) in zip(d.paths, d.values)]},
        "reduction": [ev(e, [hred.violation], kept=e.seq in hkept,
                         intent=(e.outcome["ok"].get("intent") if e.name == "llm.context" and e.ok else None),
                         operation=(e.outcome["ok"].get("operation") if e.name in ("core.write", "core.proposal")
                                    and e.ok else None)) for e in h.events],
        "reduced_before": hred.original_events, "reduced_after": len(hred.events),
    }
    try:
        from examples.citalab_r02.reexecute import reexecute
        results = [reexecute(ep) for ep in load_episodes()]
        data["citalab"]["reexecuted"] = sum(r.faithful for r in results)
    except ImportError:
        data["citalab"]["reexecuted"] = None

    # 6. Metrics (from the committed measurement) and real terminal output.
    metrics = json.loads((ROOT / "docs" / "metrics.json").read_text(encoding="utf-8"))
    runs = [(r, x) for r in metrics["seeded_regressions"] for x in r["runs"]]
    data["metrics"] = {
        "found": sum(x["found"] for r, x in runs if r["defective"]), "defective": sum(1 for r, _ in runs if r["defective"]),
        "false_alarms": sum(x["found"] for r, x in runs if not r["defective"]),
        "correct": sum(1 for r, _ in runs if not r["defective"]),
        "record_us": metrics["overhead"]["boundary_call_recorded_us"],
        "share_percent": metrics["overhead"]["fixed_cost_share_of_http_percent"],
        "disk_bytes": metrics["overhead"]["disk_bytes_per_event"],
        "deterministic": metrics["determinism"]["identical"],
    }
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "v.db")
        data["terminal"] = {
            "explore": cli("--db", db, "explore", "examples.portal_demo.scenario:reconciling", "--seed", "0",
                           "--budget", "200", "--kinds", "crash_after,lost_response,timeout", "--no-save"),
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

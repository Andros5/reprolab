"""Measure the Swiss Job Radar's real submission path under injected faults.

    <radar venv>/Scripts/python -m examples.radar_submit [--budget 300] [--out report.json]

Needs the radar importable (its own virtual environment; ReproLab adds nothing to it) and
PYTHONPATH set to ReproLab's ``src`` and the repository root. It prints and saves:

1. what every single fault on the click and on the confirmation leaves in the radar's
   database and on the synthetic portal, and whether the recording replays offline;
2. whether a crash right after the click can be reconciled through the radar's own API,
   with and without a restart of the web server;
3. one bounded exploration per scenario, including the negative control;
4. the size of the adapter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from examples.radar_submit.adapter import CLICK, CONFIRMATION, SyntheticPortal, db_state, inside, radar_env
from examples.radar_submit.scenario import rearm_control, web_restart, worker_restart
from reprolab import Fault, Session, WorkerCrash, no_network
from reprolab import scenario as rl
from reprolab.events import CRASH_AFTER, FAULT_KINDS
from reprolab.explore import explore

HERE = Path(__file__).parent
TOKEN = "t" * 32


def fault_table() -> list[dict]:
    rows = []
    for scenario in (worker_restart, web_restart):
        for site in (CLICK, CONFIRMATION):
            for kind in (None, *FAULT_KINDS):
                faults = [Fault(site, 1, kind)] if kind else []
                out = rl.record(scenario, faults)
                again = rl.replay(scenario, out.events)
                rows.append({"scenario": scenario.name, "fault": f"{site}:1:{kind}" if kind else "none",
                             "state": out.oracle["state"], "began": out.oracle["began"],
                             "portal_received": out.oracle["portal_received"],
                             "refused_resends": len(out.oracle["refusals"]),
                             "refusal": sorted(set(out.oracle["refusals"])),
                             "clicks": sum(e.name == CLICK for e in out.events),
                             "violations": len(out.violations),
                             "replays": [e.to_dict() for e in again.events] == [e.to_dict() for e in out.events]
                                        and again.result == out.result})
                if not kind and site == CONFIRMATION:
                    rows.pop()  # the fault-free run is already in the table
    return rows


def reconcile_after_crash() -> dict:
    """Crash right after the click while the web server keeps running; then try to
    reconcile through the API, before and after a web restart, and to send again."""
    from fastapi.testclient import TestClient
    from radar.portals import send
    from radar.web import create_app
    from radar.workspace import Workspace

    from examples.radar_submit.adapter import FakePage

    auth = {"Authorization": f"Bearer {TOKEN}"}
    body = {"outcome": "not_received", "evidence": "synthetic: portal and mailbox checked"}
    out = {}
    with radar_env(SyntheticPortal()) as env:
        with inside(env.root), TestClient(create_app(env.db, token=TOKEN, scheduler=False)) as web:
            session = Session.record(faults=[Fault(CLICK, 1, CRASH_AFTER)])
            with no_network():
                try:
                    worker_restart.run(session, env)
                except WorkerCrash:
                    session.restart()
                    worker_restart.run(session, env)
            out["after_worker_restart"] = db_state(env)["state"]
            r = web.post(f"/api/applications/{env.aid}/reconcile", json=body, headers=auth)
            out["reconcile_while_web_kept_running"] = {"status": r.status_code, "detail": r.json().get("detail")}
        with inside(env.root), TestClient(create_app(env.db, token=TOKEN, scheduler=False)) as web:
            out["after_web_restart"] = db_state(env)["state"]
            r = web.post(f"/api/applications/{env.aid}/reconcile", json=body, headers=auth)
            out["reconcile_after_web_restart"] = {"status": r.status_code, "state": r.json().get("state")}
        with inside(env.root), Workspace(env.db) as ws:
            try:
                send(ws, env.aid, FakePage(Session.record(), env.portal))
                out["send_after_reconcile"] = "sent"
            except ValueError as refused:
                out["send_after_reconcile"] = f"refused: {refused}"
        out["portal_received"] = len(env.portal.received)
    return out


def adapter_lines() -> dict:
    def code(path: Path) -> int:
        lines, in_doc = 0, False
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith('"""'):
                in_doc = not (in_doc or (len(s) > 3 and s.endswith('"""')))
                continue
            if in_doc or not s or s.startswith("#"):
                continue
            lines += 1
        return lines

    files = ("adapter.py", "invariants.py", "scenario.py")
    return {f: {"total": len((HERE / f).read_text(encoding="utf-8").splitlines()), "code": code(HERE / f)}
            for f in files}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m examples.radar_submit")
    p.add_argument("--budget", type=int, default=300)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None, help="write the measurements as JSON")
    args = p.parse_args(argv)

    report: dict = {"faults": fault_table()}
    print("Single faults (state left in the radar's database / applications on the portal):")
    for r in report["faults"]:
        print(f"  {r['scenario']:21} {r['fault']:34} state={r['state']:18} began={r['began']} "
              f"portal={r['portal_received']} clicks={r['clicks']} refused={r['refused_resends']} "
              f"violations={r['violations']} replays={r['replays']}")

    report["reconcile"] = reconcile_after_crash()
    print("\nCrash right after the click, then reconciliation through the radar's API:")
    for k, v in report["reconcile"].items():
        print(f"  {k}: {v}")

    report["explore"] = {}
    for attr, scenario in (("worker_restart", worker_restart), ("web_restart", web_restart),
                           ("rearm_control", rearm_control)):
        r = explore(scenario, seed=args.seed, budget=args.budget, max_faults=2,
                    target=f"examples.radar_submit.scenario:{attr}")
        report["explore"][scenario.name] = r.to_dict()
        print("\n" + r.describe())

    report["adapter_lines"] = adapter_lines()
    print("\nAdapter size:", report["adapter_lines"])
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    real = [report["explore"][s.name]["counterexamples"] for s in (worker_restart, web_restart)]
    return 1 if any(real) else 0


if __name__ == "__main__":
    sys.exit(main())

"""One-command demo:  python -m examples.portal_demo

1. Record the blind-retry client while the first submission's response is lost.
2. Check the business property on the trace, and the portal's real state as an oracle.
3. Replay the recording with the network disabled: same trace, same violation.
4. Record the reconciling client under the same fault: the property holds.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from examples.portal_demo.applier import SUBMIT
from examples.portal_demo.scenario import record, replay
from reprolab import LOST_RESPONSE, Fault, load_run, save_run

FAULT = [Fault(SUBMIT, 1, LOST_RESPONSE)]


def show(title: str, run, oracle: bool = True) -> None:
    print(f"\n== {title}")
    for e in run.events:
        print("  ", e.describe())
    print("   result:", run.result)
    if oracle:
        print("   portal oracle: applications for this job =", run.portal_applications)
    print("   property:", "VIOLATED" if run.violations else "holds")
    for v in run.violations:
        print("     ", v)


def main(db_path: str | None = None) -> int:
    db = Path(db_path) if db_path else Path(tempfile.gettempdir()) / "reprolab-demo.db"

    blind = record("blind_retry", FAULT)
    show("1. Record: blind retry, first response lost (fault injected)", blind)
    run_id = save_run(db, blind.events, label="blind_retry lost_response",
                      meta={"implementation": "blind_retry", "faults": [vars(f) for f in FAULT]})
    print(f"   saved as run {run_id} in {db}")

    _, events = load_run(db, run_id)
    again = replay("blind_retry", events)
    show("2. Replay offline from the saved run (network disabled)", again, oracle=False)
    same = [e.describe() for e in again.events] == [e.describe() for e in blind.events]
    print("   identical trace:", same)

    safe = record("reconciling", FAULT)
    show("3. Record: reconciling client, same fault", safe)

    ok = bool(blind.violations) and bool(again.violations) and not safe.violations and same
    print("\nDemo", "OK: the property separates both clients and the failure replays offline." if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))

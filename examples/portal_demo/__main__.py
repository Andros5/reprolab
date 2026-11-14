"""One-command demo:  python -m examples.portal_demo

1. Record the blind-retry client while the first submission's response is lost.
2. Replay the saved recording with the network disabled: same trace, same violation.
3. Record the reconciling client under the same fault: the property holds.
4. Record a longer flow (posting, LLM draft, telemetry) under two faults, and reduce
   its trace to the events the violated property actually needs.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from examples.portal_demo.applier import SUBMIT
from examples.portal_demo.scenario import INVARIANTS, record, replay, target
from reprolab import LOST_RESPONSE, RATE_LIMITED, REDUCED, Fault, Recording, load_run, reduce_violation, save_run

FAULT = [Fault(SUBMIT, 1, LOST_RESPONSE)]
TWO_FAULTS = [Fault(SUBMIT, 1, LOST_RESPONSE), Fault(SUBMIT, 2, RATE_LIMITED)]


def show(title: str, events, violations, result=None, oracle=None) -> None:
    print(f"\n== {title}")
    flagged = {v.seq for v in violations}
    for e in events:
        print(("!! " if e.seq in flagged else "   ") + e.describe())
    if result is not None:
        print("   result:", result)
    if oracle is not None:
        print("   portal oracle: applications for this job =", oracle)
    print("   property:", "VIOLATED" if violations else "holds")
    for v in violations:
        print("     ", v)


def main(db_path: str | None = None) -> int:
    db = Path(db_path) if db_path else Path(tempfile.gettempdir()) / "reprolab-demo.db"

    blind = record("blind_retry", FAULT)
    show("1. Record: blind retry, first response lost (simulated fault)", blind.events, blind.violations,
         blind.result, blind.portal_applications)
    run_id = save_run(db, Recording(blind.events, label="blind_retry lost_response", target=target("blind_retry"),
                                    faults=[f.to_dict() for f in FAULT]))
    print(f"   saved as run {run_id} in {db}")

    again = replay("blind_retry", load_run(db, run_id).events)
    show("2. Replay offline from the saved run (network disabled)", again.events, again.violations, again.result)
    same = again.events == blind.events and again.result == blind.result
    print("   identical trace and result:", same)

    safe = record("reconciling", FAULT)
    show("3. Record: reconciling client, same fault", safe.events, safe.violations, safe.result,
         safe.portal_applications)

    full = record("blind_retry_full", TWO_FAULTS)
    show("4a. Record: longer flow, lost response then rate limit (simulated faults)", full.events, full.violations,
         full.result, full.portal_applications)
    full_id = save_run(db, Recording(full.events, label="blind_retry_full", target=target("blind_retry_full"),
                                     faults=[f.to_dict() for f in TWO_FAULTS]))
    red = reduce_violation(full.events, list(INVARIANTS))
    show(f"4b. Reduce: keep {red.invariant} violated at #{red.anchor}", red.events, [red.violation])
    print(f"   {red.original_events} -> {len(red.events)} events, {red.tests} candidates tested, {red.seconds:.3f}s;"
          " the posting and the draft stay because the submissions use their output")
    save_run(db, Recording(red.events, label="blind_retry_full reduced", origin=REDUCED,
                           target=target("blind_retry_full"), faults=[f.to_dict() for f in TWO_FAULTS],
                           reduced_from={"run": full_id, "invariant": red.invariant, "anchor": red.anchor,
                                         "kept": red.kept, "original_events": red.original_events,
                                         "tests": red.tests, "seconds": round(red.seconds, 6)}))
    print("   (1-minimal, not a global minimum; the reduced trace is a regression fixture, not a replayable run)")

    ok = (bool(blind.violations) and bool(again.violations) and not safe.violations and same
          and len(red.events) < red.original_events)
    print("\nDemo", "OK: the property separates both clients, the failure replays offline, "
                    "and the trace reduces to what the property needs." if ok else "FAILED")
    print(f"Explore the runs:  python -m reprolab --db {db} list")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))

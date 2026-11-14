"""H4: new faults, crash and restart, and the bounded explorer."""

import pytest

from examples.portal_demo.applier import FIND, SUBMIT
from examples.portal_demo.invariants import no_blind_resubmit
from examples.portal_demo.scenario import SCENARIOS
from reprolab import BoundaryError, Fault, Session, WorkerCrash
from reprolab import scenario as rl
from reprolab.cli import main as cli
from reprolab.events import CRASH_AFTER, EFFECT_UNKNOWN, FAULT_KINDS, RESTART, Event
from reprolab.explore import ORACLE_ONLY, PROPERTY, UNHANDLED, _shrink, classify, explore
from reprolab.store import list_runs

NO_CRASH = tuple(k for k in FAULT_KINDS if k != CRASH_AFTER)


# -- faults --------------------------------------------------------------------------

def test_timeout_does_not_run_the_call_but_reports_unknown_effect():
    rec = Session.record(faults=[Fault("svc", 1, "timeout")])
    with pytest.raises(BoundaryError) as err:
        rec.call("svc", {}, lambda r: pytest.fail("must not run"))
    assert (err.value.type, err.value.effect) == ("Timeout", EFFECT_UNKNOWN)


def test_duplicate_delivers_twice_and_invalid_output_empties_the_answer():
    calls = []
    rec = Session.record(faults=[Fault("svc", 1, "duplicate"), Fault("svc", 2, "invalid_output")])
    assert rec.call("svc", {}, lambda r: calls.append(1) or {"id": len(calls)}) == {"id": 1}
    assert calls == [1, 1]
    assert rec.call("svc", {}, lambda r: calls.append(1) or {"id": 9}) == {}
    assert [e.fault["kind"] for e in rec.finish()] == ["duplicate", "invalid_output"]


def test_a_crash_cannot_be_swallowed_by_the_code_under_test():
    rec = Session.record(faults=[Fault("svc", 1, CRASH_AFTER)])
    calls = []
    with pytest.raises(WorkerCrash):
        try:
            rec.call("svc", {}, lambda r: calls.append(r) or {"id": 1})
        except Exception:  # noqa: BLE001 - what careless code would do
            pytest.fail("a crash is not an Exception")
    assert calls == [{}]  # the call took effect before the worker died
    rec.restart()
    crash, restart = rec.finish()
    assert crash.error["type"] == "WorkerCrash" and crash.fault == {"kind": CRASH_AFTER, "simulated": True}
    assert (restart.name, restart.deps) == (RESTART, (1,))


def test_crash_and_restart_replay_offline():
    faults = [Fault(SUBMIT, 1, CRASH_AFTER)]
    for name, violated in (("reconciling", True), ("journaled", False)):
        out = rl.record(SCENARIOS[name], faults)
        assert bool(out.violations) is violated and RESTART in [e.name for e in out.events]
        again = rl.replay(SCENARIOS[name], out.events)
        assert (again.events, again.result) == (out.events, out.result)


def test_a_malformed_lookup_settles_nothing():
    def ev(seq, name, outcome):
        return Event(seq=seq, type="call", name=name, kind="http", request={"candidate": "c", "job": "j"},
                     outcome=outcome)
    lost = {"error": {"type": "LostResponse", "message": "", "effect": "unknown"}}
    trace = [ev(1, SUBMIT, lost), ev(2, FIND, {"ok": {}}), ev(3, SUBMIT, {"ok": {"id": 2}})]
    assert [v.seq for v in no_blind_resubmit(trace)] == [3]


# -- classification ----------------------------------------------------------------------

@pytest.mark.parametrize("variant, faults, category", [
    ("reconciling", [Fault(SUBMIT, 1, CRASH_AFTER)], PROPERTY),
    ("reconciling", [Fault(SUBMIT, 1, "invalid_output")], UNHANDLED),
    ("journaled", [Fault(SUBMIT, 1, "duplicate")], ORACLE_ONLY),
    ("journaled", [Fault(SUBMIT, 1, "invalid_output")], None),
])
def test_runs_are_classified(variant, faults, category):
    findings = classify(SCENARIOS[variant], rl.record(SCENARIOS[variant], faults))
    assert [f.category for f in findings] == ([category] if category else [])


# -- explorer -----------------------------------------------------------------------------

def test_same_seed_same_schedules_and_findings():
    a = explore(SCENARIOS["reconciles_once"], seed=5, budget=60, kinds=NO_CRASH)
    b = explore(SCENARIOS["reconciles_once"], seed=5, budget=60, kinds=NO_CRASH)
    assert a.schedules == b.schedules
    assert [(c.signature, c.first_run, c.hits) for c in a.counterexamples] == \
        [(c.signature, c.first_run, c.hits) for c in b.counterexamples]


def test_finds_a_defect_that_needs_two_faults_and_reduces_it():
    r = explore(SCENARIOS["reconciles_once"], seed=1, budget=120, kinds=NO_CRASH)
    prop = [c for c in r.counterexamples if c.category == PROPERTY]
    assert prop and prop[0].signature == "no-blind-resubmit at portal.submit"
    assert len(prop[0].minimal) == 2  # no single fault reproduces it
    assert prop[0].reduced_events < prop[0].trace_events
    assert r.explored[1] == r.space[1]  # every single fault was tried before any pair


def test_correct_client_gets_no_property_finding():
    r = explore(SCENARIOS["journaled"], seed=0, budget=120)
    assert not [c for c in r.counterexamples if c.category == PROPERTY]
    assert "does not show the system is correct" in r.describe()


def test_shrinking_removes_faults_that_do_not_matter():
    scenario = SCENARIOS["blind_retry"]
    schedule = (Fault(FIND, 1, "rate_limited"), Fault(SUBMIT, 1, "lost_response"))
    out = rl.record(scenario, list(schedule))
    minimal, reexecutions, _ = _shrink(scenario, schedule, "no-blind-resubmit at portal.submit", out)
    assert minimal == (Fault(SUBMIT, 1, "lost_response"),) and reexecutions >= 1


def test_a_small_space_is_exhausted_and_says_so():
    r = explore(SCENARIOS["journaled"], seed=0, budget=500, kinds=("rate_limited",), max_faults=1)
    assert r.exhausted and r.runs == r.space[1] < 500


def test_cli_explore_gates_on_properties_and_saves_replayable_counterexamples(tmp_path, capsys):
    db = str(tmp_path / "runs.db")
    target = "examples.portal_demo.scenario:reconciling"
    assert cli(["--db", db, "explore", target, "--seed", "0", "--budget", "50", "--kinds", "crash_after"]) == 1
    minimal = next(r for r in list_runs(db) if r["origin"] == "recorded")
    capsys.readouterr()
    assert cli(["--db", db, "replay", minimal["id"]]) == 0  # the crash and the restart replay offline
    assert "property: VIOLATED" in capsys.readouterr().out
    assert cli(["--db", db, "explore", "examples.portal_demo.scenario:journaled", "--budget", "30",
                "--no-save"]) == 0

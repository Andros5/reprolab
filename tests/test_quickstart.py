"""The README's quickstart must keep working exactly as documented."""

from examples.quickstart import naive, reconciling
from reprolab import Fault
from reprolab import scenario as rl
from reprolab.explore import ORACLE_ONLY, PROPERTY, UNHANDLED, explore

LOST = [Fault("bank.charge", 1, "lost_response")]


def test_naive_charges_twice_and_the_property_sees_it():
    out = rl.record(naive, LOST)
    assert out.oracle == {"charges": 2}
    assert [(v.invariant, v.seq) for v in out.violations] == [("charge-at-most-once", 2)]


def test_reconciling_survives_a_lost_response():
    out = rl.record(reconciling, LOST)
    assert out.oracle == {"charges": 1}
    assert out.violations == []
    assert out.result == {"state": "already charged"}


def test_replay_is_offline_and_identical():
    for scenario in (naive, reconciling):
        recorded = rl.record(scenario, LOST)
        replayed = rl.replay(scenario, recorded.events)
        assert [e.to_dict() for e in replayed.events] == [e.to_dict() for e in recorded.events]
        assert replayed.violations == recorded.violations


def test_explorer_finds_what_the_readme_promises():
    report = explore(reconciling, seed=0, budget=50)
    found = {(c.category, c.minimal) for c in report.counterexamples}
    assert (PROPERTY, (Fault("bank.charge", 1, "crash_after"),)) in found
    assert (ORACLE_ONLY, (Fault("bank.charge", 1, "duplicate"),)) in found
    assert any(c.category == UNHANDLED for c in report.counterexamples)
    again = explore(reconciling, seed=0, budget=50)
    assert again.schedules == report.schedules

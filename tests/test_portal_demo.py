"""H1 acceptance: a lost response is captured, replays offline, and the property
distinguishes the defective client from the correct one."""

import pytest

from examples.portal_demo.__main__ import main
from examples.portal_demo.applier import FIND, SUBMIT
from examples.portal_demo.scenario import record, replay
from reprolab import LOST_RESPONSE, RATE_LIMITED, Fault, ReplayDivergence

LOST = [Fault(SUBMIT, 1, LOST_RESPONSE)]


def test_blind_retry_duplicates_and_violates_the_property():
    run = record("blind_retry", LOST)
    assert run.portal_applications == 2  # oracle: the portal really has a duplicate
    assert [v.seq for v in run.violations] == [4]


def test_reconciling_client_keeps_the_property_and_one_application():
    run = record("reconciling", LOST)
    assert run.portal_applications == 1
    assert run.violations == []
    assert run.result == {"state": "submitted", "id": 1, "reconciled": True}
    assert [e.name for e in run.events if e.type == "call"] == [SUBMIT, FIND]


@pytest.mark.parametrize("implementation", ["blind_retry", "reconciling"])
def test_replay_offline_reproduces_trace_result_and_verdict(implementation):
    original = record(implementation, LOST)
    again = replay(implementation, original.events)  # network disabled inside
    assert again.events == original.events
    assert again.result == original.result
    assert again.violations == original.violations


def test_property_without_faults_holds_for_both():
    for implementation in ("blind_retry", "reconciling"):
        run = record(implementation, [])
        assert run.violations == [] and run.portal_applications == 1


def test_retry_after_a_rejection_with_no_effect_is_allowed():
    run = record("reconciling", [Fault(SUBMIT, 1, RATE_LIMITED)])
    assert run.violations == [] and run.portal_applications == 1
    assert [e.name for e in run.events if e.type == "call"] == [SUBMIT, SUBMIT]


def test_replaying_a_recording_with_different_code_diverges_explicitly():
    blind = record("blind_retry", LOST)
    with pytest.raises(ReplayDivergence, match="portal.find"):
        replay("reconciling", blind.events)


def test_one_command_demo_succeeds(tmp_path, capsys):
    assert main(str(tmp_path / "demo.db")) == 0
    assert "Demo OK" in capsys.readouterr().out

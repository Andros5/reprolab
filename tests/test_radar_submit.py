"""ReproLab on the Swiss Job Radar's real submission path (examples/radar_submit).

The property tests on hand-written traces always run. The rest drive the radar's own
code and are skipped unless it is importable: run them with the radar's environment,

    PYTHONPATH="src;." <swiss-job-radar>/.venv/Scripts/python -m pytest tests/test_radar_submit.py
"""

import pytest

from examples.radar_submit.__main__ import reconcile_after_crash
from examples.radar_submit.adapter import CLICK, CONFIRMATION, URL
from examples.radar_submit.invariants import NAME, no_resend_after_uncertain
from examples.radar_submit.scenario import _oracle_check, rearm_control, web_restart, worker_restart
from reprolab import Fault
from reprolab import scenario as rl
from reprolab.events import CALL, CRASH_AFTER, FAULT_KINDS, Event
from reprolab.explore import PROPERTY, explore

try:
    import radar.web  # noqa: F401
    HAVE_RADAR = True
except ImportError:
    HAVE_RADAR = False
needs_radar = pytest.mark.skipif(not HAVE_RADAR, reason="the Swiss Job Radar is not importable in this environment")


def click(seq, ok=True, url=URL):
    outcome = {"ok": None} if ok else {"error": {"type": "LostResponse", "message": "", "effect": "unknown"}}
    return Event(seq=seq, type=CALL, name=CLICK, request={"url": url}, outcome=outcome)


def confirmation(seq, body="Thank you for applying"):
    return Event(seq=seq, type=CALL, name=CONFIRMATION, request={"url": URL}, outcome={"ok": {"body": body}})


def test_property_flags_any_second_click_and_says_why():
    assert no_resend_after_uncertain([click(1), confirmation(2)]) == []
    after_confirmation = no_resend_after_uncertain([click(1), confirmation(2), click(3)])
    assert [(v.invariant, v.seq) for v in after_confirmation] == [(NAME, 3)]
    assert "after the confirmation at #2" in after_confirmation[0].message
    uncertain = no_resend_after_uncertain([click(1, ok=False), click(2)])
    assert "unconfirmed click at #1" in uncertain[0].message
    assert no_resend_after_uncertain([click(1, ok=False), click(2, url=URL + "-other")]) == []
    # an empty confirmation page confirms nothing
    assert "unconfirmed" in no_resend_after_uncertain([click(1), confirmation(2, body=""), click(3)])[0].message


# -- against the radar's code ----------------------------------------------------------

ASKS_FOR_APPROVAL = "Se necesita una aprobación vigente"


def same(a, b):
    return [e.to_dict() for e in a.events] == [e.to_dict() for e in b.events] and a.result == b.result


@needs_radar
def test_fault_free_send_submits_once_and_replays_offline():
    out = rl.record(web_restart, [])
    assert [e.name for e in out.events] == [CLICK, CONFIRMATION]
    assert out.oracle["state"] == "submitted" and out.oracle["receipt"]
    assert (out.oracle["began"], out.oracle["portal_received"], out.violations) == (1, 1, [])
    assert same(rl.replay(web_restart, out.events), out)


@needs_radar
@pytest.mark.parametrize("scenario", [worker_restart, web_restart], ids=lambda s: s.name)
@pytest.mark.parametrize("site", [CLICK, CONFIRMATION])
@pytest.mark.parametrize("kind", FAULT_KINDS)
def test_no_single_fault_makes_the_radar_click_twice(scenario, site, kind):
    out = rl.record(scenario, [Fault(site, 1, kind)])
    assert out.violations == []
    assert sum(e.name == CLICK for e in out.events) == 1
    assert out.oracle["began"] == 1 and _oracle_check(out.oracle) is None
    if out.oracle["state"] != "submitted":  # every later attempt is refused before any click
        assert out.oracle["refusals"][-2:] == [ASKS_FOR_APPROVAL] * 2
    if (site, kind) == (CONFIRMATION, "invalid_output"):  # an empty confirmation page is no receipt
        assert out.oracle["state"] == "submission_unknown"
        assert out.oracle["refusals"][0] == "Se requiere un comprobante"
    assert same(rl.replay(scenario, out.events), out)


@needs_radar
def test_crash_after_the_click_leaves_sending_until_the_web_server_restarts():
    crash = [Fault(CLICK, 1, CRASH_AFTER)]
    worker = rl.record(worker_restart, crash)
    assert worker.oracle["state"] == "sending" and worker.oracle["portal_received"] == 1
    assert len(worker.oracle["refusals"]) == 3  # every blind re-send after the restart is refused
    web = rl.record(web_restart, crash)
    assert web.oracle["state"] == "submission_unknown"
    assert web.oracle["events"] == ["sending"]  # the recovery changes the state without writing an event


@needs_radar
def test_reconciliation_goes_through_the_api_and_a_new_approval():
    r = reconcile_after_crash()
    assert r["after_worker_restart"] == "sending"
    assert r["reconcile_while_web_kept_running"]["status"] == 409
    assert r["after_web_restart"] == "submission_unknown"
    assert r["reconcile_after_web_restart"] == {"status": 200, "state": "needs_review"}
    assert r["send_after_reconcile"] == f"refused: {ASKS_FOR_APPROVAL}"
    assert r["portal_received"] == 1


@needs_radar
def test_negative_control_is_caught_on_the_trace_and_by_the_oracle():
    out = rl.record(rearm_control, [Fault(CLICK, 1, "lost_response")])
    assert [(v.invariant, v.seq) for v in out.violations] == [(NAME, 2)]
    assert out.oracle["began"] == 2 and out.oracle["portal_received"] == 2
    assert _oracle_check(out.oracle) == "the radar began 2 submissions of one application"


@needs_radar
def test_explorer_finds_the_control_and_nothing_on_the_radar_over_every_single_fault():
    radar_report = explore(web_restart, seed=0, budget=24, reduce=False)
    assert radar_report.explored == {1: 24} and radar_report.counterexamples == []
    control = explore(rearm_control, seed=0, budget=10)
    assert [c.category for c in control.counterexamples] == [PROPERTY]
    assert control.counterexamples[0].minimal and control.counterexamples[0].reduced_events == 2

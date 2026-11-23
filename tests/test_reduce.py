"""Reduction keeps the same violated property at the same event and respects dependencies."""

import pytest

from examples.portal_demo.applier import DRAFT, JOB_INFO, SUBMIT
from examples.portal_demo.invariants import NAME, no_blind_resubmit
from examples.portal_demo.scenario import INVARIANTS, record
from reprolab import (
    LOST_RESPONSE,
    RATE_LIMITED,
    Event,
    Fault,
    NotReproduced,
    Session,
    check,
    reduce_trace,
    reduce_violation,
)
from reprolab.events import validate_trace

TWO_FAULTS = [Fault(SUBMIT, 1, LOST_RESPONSE), Fault(SUBMIT, 2, RATE_LIMITED)]


@pytest.fixture(scope="module")
def full_run():
    return record("blind_retry_full", TWO_FAULTS)


def _dependents_closure(events, seq):
    gone = {seq}
    for e in events:  # events are in seq order, so one pass is enough
        if gone & set(e.deps):
            gone.add(e.seq)
    return gone


def test_reduction_keeps_the_violation_and_what_it_depends_on(full_run):
    red = reduce_violation(full_run.events, list(INVARIANTS))
    assert (red.invariant, red.anchor, red.original_events) == (NAME, 9, 15)
    names = [(e.seq, e.name) for e in red.events]
    # The uncertain submission (#5), the resubmission (#9), and what their requests use:
    # the tokens (#4, #8), the drafted letter (#3) and the posting it was drafted from (#2).
    assert names == [(2, JOB_INFO), (3, DRAFT), (4, "token"), (5, SUBMIT), (8, "token"), (9, SUBMIT)]
    assert red.violation.seq == 9 and "uncertain outcome at #5" in red.violation.message
    validate_trace(red.events, contiguous=False)


def test_reduced_trace_is_one_minimal(full_run):
    red = reduce_violation(full_run.events, list(INVARIANTS))
    for e in red.events:
        gone = _dependents_closure(red.events, e.seq)
        smaller = [x for x in red.events if x.seq not in gone]
        assert not any(v.invariant == NAME and v.seq == 9 for v in check(smaller, list(INVARIANTS))), e.seq


def test_anchor_selects_which_violation_is_preserved(full_run):
    red = reduce_violation(full_run.events, list(INVARIANTS), anchor=13)
    assert red.anchor == 13 and red.kept == [2, 3, 4, 5, 12, 13]


def test_reduction_does_not_slide_to_another_violation():
    # Two independent applications fail the same way. Reducing at the second one must not
    # return the (smaller) first failure, even though it violates the same invariant.
    rec = Session.record(faults=[Fault(SUBMIT, 1, LOST_RESPONSE), Fault(SUBMIT, 3, LOST_RESPONSE)])
    for job in ("job-1", "job-2"):
        for _ in range(2):
            try:
                rec.call(SUBMIT, {"candidate": "c", "job": job}, lambda r: {"id": 1})
            except Exception:
                pass
    events = rec.finish()
    assert [v.seq for v in check(events, [no_blind_resubmit])] == [2, 4]
    red = reduce_violation(events, [no_blind_resubmit], anchor=4)
    assert red.kept == [3, 4]


def test_nothing_to_reduce_is_reported_not_invented():
    safe = record("reconciling_full", TWO_FAULTS)
    with pytest.raises(NotReproduced, match="no invariant"):
        reduce_violation(safe.events, list(INVARIANTS))


def test_wrong_invariant_or_anchor_is_rejected(full_run):
    with pytest.raises(NotReproduced, match="not violated at event #7"):
        reduce_violation(full_run.events, list(INVARIANTS), anchor=7)
    with pytest.raises(NotReproduced, match="'other' is not violated"):
        reduce_violation(full_run.events, list(INVARIANTS), invariant="other")


def _ok(seq, name, deps=()):
    return Event(seq=seq, type="call", name=name, kind="tool", request={}, outcome={"ok": None}, deps=tuple(deps))


def test_generic_reduction_finds_a_needle_among_noise_and_honours_chains():
    # 200 events; the property "a and b both present" needs #50 and #150, and #150 needs
    # the chain #149 <- #148.
    events = [_ok(i, "noise") for i in range(1, 201)]
    events[49] = _ok(50, "a")
    events[147] = _ok(148, "root")
    events[148] = _ok(149, "mid", deps=[148])
    events[149] = _ok(150, "b", deps=[149])
    holds = lambda evs: {"a", "b"} <= {e.name for e in evs}  # noqa: E731
    reduced, tests = reduce_trace(events, holds)
    assert [e.seq for e in reduced] == [50, 148, 149, 150]
    assert tests < 200  # far fewer candidates than one-by-one removal would need

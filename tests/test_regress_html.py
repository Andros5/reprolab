"""H5: differential replay against new code, and the visual reports."""

import re

import pytest

from examples.portal_demo.applier import SUBMIT
from examples.portal_demo.scenario import SCENARIOS, target
from reprolab import Fault, Recording, ReplayDivergence, Session, reduce_violation
from reprolab import html as H
from reprolab import scenario as rl
from reprolab.cli import main as cli
from reprolab.diff import DIFFERENT_CALL, first_divergence, normalize_nondeterminism
from reprolab.regress import (
    COMPATIBLE,
    FIXED,
    INCOMPATIBLE,
    NOT_REPLAYABLE,
    REGRESSED,
    STILL_FAILING,
    STILL_PASSING,
    UNKNOWN,
    regress,
)
from reprolab.store import REDUCED, list_runs

LOST = [Fault(SUBMIT, 1, "lost_response")]
CRASH = [Fault(SUBMIT, 1, "crash_after")]


def recording(name, faults, **kw):
    out = rl.record(SCENARIOS[name], faults)
    return Recording(out.events, label=name, target=target(name), faults=[f.to_dict() for f in faults], **kw)


def test_divergence_says_where_replay_stopped_matching():
    rec = Session.record()
    rec.call("a", {}, lambda r: 1)
    rec.call("b", {}, lambda r: 2)
    rep = Session.replay(rec.finish())
    rep.call("a", {}, lambda r: 1)
    with pytest.raises(ReplayDivergence) as err:
        rep.call("c", {}, lambda r: 3)
    assert (err.value.seq, err.value.reproduced) == (2, 1)


def test_randomness_alone_is_not_a_difference_when_ignored():
    a, b = (rl.record(SCENARIOS["blind_retry"], LOST).events for _ in range(2))
    assert first_divergence(a, b).position == 0  # different tokens
    assert first_divergence(a, b, ignore_nondeterminism=True) is None
    tokens = [e.outcome["ok"] for e in normalize_nondeterminism(a) if e.type == "random"]
    assert tokens == ["<random 1>", "<random 2>"]
    assert normalize_nondeterminism(a)[1].request["request_id"] == "<random 1>"  # the role survives


@pytest.mark.parametrize("old, faults, new, compatibility, verdict", [
    ("blind_retry", LOST, "journaled", INCOMPATIBLE, FIXED),
    ("reconciling", CRASH, "journaled", INCOMPATIBLE, FIXED),
    ("reconciling", CRASH, "reconciling", COMPATIBLE, STILL_FAILING),
    ("reconciling", LOST, "blind_retry", INCOMPATIBLE, REGRESSED),
    ("reconciling", LOST, "journaled", COMPATIBLE, STILL_PASSING),
    ("blind_retry", [], "journaled", COMPATIBLE, STILL_PASSING),
])
def test_regress_verdicts(old, faults, new, compatibility, verdict):
    r = regress(recording(old, faults), SCENARIOS[new], target(new))
    assert (r.compatibility, r.verdict) == (compatibility, verdict)
    if compatibility == INCOMPATIBLE:
        assert r.rerecorded and r.divergence_seq is not None and r.reproduced >= 1
        assert set(r.faults_fired) == set(r.faults_planned)


def test_incompatible_recording_points_at_the_changed_behaviour():
    r = regress(recording("reconciling", CRASH), SCENARIOS["journaled"], target("journaled"))
    assert (r.divergence_seq, r.reproduced) == (4, 3)  # after the crash and restart, a lookup instead of a token
    assert r.first_difference.kind == DIFFERENT_CALL and r.first_difference.b.name == "portal.find"


def test_without_rerecording_the_verdict_stays_unknown_and_reduced_runs_are_refused():
    r = regress(recording("blind_retry", LOST), SCENARIOS["journaled"], rerecord=False)
    assert (r.compatibility, r.verdict) == (INCOMPATIBLE, UNKNOWN)
    rec = recording("blind_retry", LOST)
    red = reduce_violation(rec.events, list(SCENARIOS["blind_retry"].invariants))
    reduced = Recording(red.events, origin=REDUCED, target=rec.target, reduced_from={
        "run": "x", "invariant": red.invariant, "anchor": red.anchor, "kept": red.kept,
        "original_events": red.original_events, "tests": red.tests, "seconds": 0.0})
    assert regress(reduced, SCENARIOS["journaled"]).compatibility == NOT_REPLAYABLE


def test_cli_regress_gates_and_stores_rerecorded_runs(tmp_path, capsys):
    db = str(tmp_path / "runs.db")
    t = "examples.portal_demo.scenario:"
    cli(["--db", db, "record", t + "reconciling", "--fault", "portal.submit:1:crash_after"])
    assert cli(["--db", db, "regress", "--target", t + "journaled"]) == 0
    assert cli(["--db", db, "regress", "--target", t + "reconciling", "--from", t + "reconciling"]) == 1
    out = capsys.readouterr().out
    assert "fixed" in out and "still failing" in out
    assert any(r["label"].startswith("regress ") for r in list_runs(db))


# -- HTML --------------------------------------------------------------------------------

def test_html_page_is_self_contained_and_theme_aware():
    out = rl.record(SCENARIOS["blind_retry"], LOST)
    page = H.page("Trace test", [("run", "run", "A run", H.run_view(out.events, out.violations, title="t"))])
    assert page.startswith("<!doctype html>") and "<title>Trace test</title>" in page
    assert "prefers-color-scheme: dark" in page and ':root[data-theme="dark"]' in page
    assert not re.search(r'<script[^>]+src=', page)  # no external scripts
    assert 'class="ev fault' in page and "violation" in page and "<path data-from=" in page
    fragment = H.page("Trace test", [], fragment=True)
    assert "<!doctype" not in fragment and "<html" not in fragment


def test_embedded_event_data_cannot_close_its_script_tag():
    rec = Session.record()
    rec.call("svc", {"note": "</script><b>x</b>"}, lambda r: "ok")
    page = H.page("T", [("r", "r", "r", H.run_view(rec.finish(), [], title="t"))])
    assert "</script><b>" not in page


def test_cli_html_writes_run_compare_and_reduction_views(tmp_path):
    db = str(tmp_path / "runs.db")
    t = "examples.portal_demo.scenario:blind_retry"
    cli(["--db", db, "record", t, "--fault", "portal.submit:1:lost_response"])
    cli(["--db", db, "record", t, "--fault", "portal.submit:1:lost_response"])
    a, b = (r["id"] for r in list_runs(db))
    cli(["--db", db, "reduce", a])
    reduced = next(r["id"] for r in list_runs(db) if r["origin"] == REDUCED)
    for args, marker in (([a], "Run "), ([a, "--compare", b, "--ignore-nondeterminism"], "identical for"),
                         ([reduced], "faded rows were removed")):
        out = tmp_path / f"{args[0]}-{len(args)}.html"
        assert cli(["--db", db, "html", *args, "-o", str(out)]) == 0
        assert marker in out.read_text(encoding="utf-8")


def test_showcase_builds_from_live_runs():
    from examples.showcase import build
    page = build(fragment=True)
    for anchor in ("lost-response", "reduction", "explorer", "regression", "citalab"):
        assert f'id="{anchor}"' in page
    assert "12/12" in page and "<!doctype" not in page

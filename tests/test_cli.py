"""The CLI end to end: record, list, show, replay, reduce, export."""

import pytest

from reprolab import REDUCED, Recording, load_run
from reprolab.cli import main
from reprolab.store import list_runs

FULL = "examples.portal_demo.scenario:blind_retry_full"
FAULTS = ["--fault", "portal.submit:1:lost_response", "--fault", "portal.submit:2:rate_limited"]


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "runs.db")


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_record_replay_reduce_export(db, capsys, tmp_path):
    code, out = run(capsys, "--db", db, "record", FULL, *FAULTS)
    assert code == 0 and "property: VIOLATED" in out and "[simulated fault: lost_response]" in out
    assert "oracle (real state, not part of the trace): {'applications': 2}" in out
    original = list_runs(db)[0]["id"]

    code, out = run(capsys, "--db", db, "list")
    assert code == 0 and original in out and "recorded" in out

    code, out = run(capsys, "--db", db, "replay", original[:5])
    assert code == 0 and "15 of 15 recorded events reproduced, network disabled" in out
    assert "does not show a service or LLM would answer the same" in out

    code, out = run(capsys, "--db", db, "reduce", original)
    assert code == 0 and "15 -> 6 events" in out and "original " + original + " unchanged" in out
    reduced = next(r for r in list_runs(db) if r["origin"] == REDUCED)
    rec = load_run(db, reduced["id"])
    assert rec.reduced_from["run"] == original and rec.reduced_from["kept"] == [2, 3, 4, 5, 8, 9]
    assert len(load_run(db, original).events) == 15  # the original is untouched

    code, out = run(capsys, "--db", db, "show", reduced["id"])
    assert code == 0 and "a trace, not an execution" in out and "15 -> 6 events" in out

    code, out = run(capsys, "--db", db, "replay", reduced["id"])
    assert code == 1 and "reduced trace, not an execution" in out

    path = tmp_path / "reduced.json"
    code, _ = run(capsys, "--db", db, "export", reduced["id"], "-o", str(path))
    assert code == 0 and Recording.from_doc(path.read_text(encoding="utf-8")).origin == REDUCED


def test_replay_against_other_code_reports_the_divergence(db, capsys):
    run(capsys, "--db", db, "record", FULL, *FAULTS)
    original = list_runs(db)[0]["id"]
    code, out = run(capsys, "--db", db, "replay", original, "--target",
                    "examples.portal_demo.scenario:reconciling_full")
    assert code == 1 and "DIVERGED" in out and "portal.find" in out


def test_errors_are_reported_without_tracebacks(db, capsys):
    assert run(capsys, "--db", db, "record", FULL, "--fault", "portal.submit:one:lost_response")[0] == 2
    assert run(capsys, "--db", db, "record", "examples.portal_demo.scenario:nothing")[0] == 2
    assert run(capsys, "--db", db, "show", "missing")[0] == 2
    run(capsys, "--db", db, "record", "examples.portal_demo.scenario:reconciling")
    code, out = run(capsys, "--db", db, "reduce", list_runs(db)[0]["id"])
    assert code == 1 and "no invariant is violated" in out

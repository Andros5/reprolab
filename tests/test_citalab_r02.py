"""H3: the CitaLab N-R02 investigation is checkable from the vendored evidence.

The re-execution tests need CitaLab installed (a separate environment, see
docs/investigations/citalab-r02.md) and are skipped otherwise.
"""

import json
import shutil
from collections import Counter
from dataclasses import replace

import pytest

from examples.citalab_r02.importer import DATA, load_episodes, resolve, to_recording
from examples.citalab_r02.invariants import NAME
from examples.citalab_r02.scenario import r02
from reprolab import RECONSTRUCTED, Recording, check, load_run, reduce_violation, save_run
from reprolab.cli import main as cli
from reprolab.diff import SAME_REQUEST_DIFFERENT_OUTCOME, first_divergence
from reprolab.events import validate_trace

INVARIANTS = list(r02.invariants)
FAILED = {"groq:M5:N-R02:primary", "groq:S1:N-R02:primary", "groq:H:N-R02:primary",
          "groq:M5:N-CF-R02:counterfactual", "groq:S1:N-CF-R02:counterfactual", "groq:H:N-CF-R02:counterfactual",
          "google:H:N-R02:primary", "google:M5:N-CF-R02:counterfactual", "google:H:N-CF-R02:counterfactual"}


@pytest.fixture(scope="module")
def episodes():
    return load_episodes()


@pytest.fixture(scope="module")
def recs(episodes):
    return {ep.cell_id: to_recording(ep) for ep in episodes}


def test_evidence_is_checked_byte_for_byte(tmp_path):
    copy = tmp_path / "data"
    shutil.copytree(DATA, copy)
    trace = next((copy / "traces").iterdir())
    trace.write_bytes(trace.read_bytes().replace(b'"book"', b'"bOok"', 1))
    with pytest.raises(ValueError, match="SHA-256"):
        load_episodes(copy)


def test_every_event_cites_resolvable_evidence(episodes, recs):
    documents = {}
    for ep in episodes:
        documents[(ep.row_source, ep.row_sha256)] = ep.row
        documents[(ep.trace_source, ep.trace_sha256)] = ep.trace
    for rec in recs.values():
        rec.validate()
        assert rec.origin == RECONSTRUCTED
        for e in rec.events:
            for src in e.evidence["sources"]:
                cited = resolve(src["pointer"], documents[(src["source"], src["sha256"])])
                if e.name.startswith("tool.") and e.evidence["rule"] is None:
                    assert e.request == cited.get("arguments")  # verbatim means unchanged values
                if e.kind == "user" and e.name != "user.end":
                    assert e.outcome["ok"]["text"] == cited["user"]
                if e.kind == "llm" and src["source"].endswith(".json"):
                    assert e.request["input"] == cited["input"] and e.request["prompt_hash"] == cited["prompt_hash"]


def test_only_derived_events_carry_a_rule(recs):
    rules = Counter(e.evidence["rule"] is not None for rec in recs.values() for e in rec.events)
    assert rules[True] == 88 and all(e.kind == "llm" for rec in recs.values() for e in rec.events if e.reconstructed)


def test_property_agrees_with_citalabs_oracle_on_all_twelve(recs):
    for cell, rec in recs.items():
        violations = check(rec.events, INVARIANTS)
        assert bool(violations) == (cell in FAILED), cell
        assert bool(violations) != rec.extra["citalab"]["oracle_goal"]["pass"], cell
        if violations:
            write = next(e for e in rec.events if e.seq == violations[0].seq)
            assert write.name == "core.write" and write.outcome["ok"]["operation"] == "book"


def test_gemini_answered_one_identical_request_two_ways(recs):
    firsts = [next(e for e in recs[c].events if e.name == "llm.context")
              for c in ("google:M5:N-R02:primary", "google:H:N-R02:primary",
                        "google:M5:N-CF-R02:counterfactual", "google:H:N-CF-R02:counterfactual")]
    assert all(e.request == firsts[0].request for e in firsts)
    assert Counter(e.outcome["ok"]["intent"] for e in firsts) == {"book": 3, "reschedule": 1}
    groq = [next(e for e in recs[c].events if e.name == "llm.context") for c in recs if c.startswith("groq") and ":S1:" not in c]
    assert {e.outcome["ok"]["intent"] for e in groq} == {"book"}


def test_first_divergence_between_success_and_failure(recs):
    d = first_divergence(recs["google:M5:N-R02:primary"].events, recs["google:H:N-R02:primary"].events)
    assert (d.position, d.kind, d.a.name) == (1, SAME_REQUEST_DIFFERENT_OUTCOME, "llm.context")
    assert set(d.paths) == {"/outcome/ok/intent", "/outcome/ok/appointment_id"}


def test_reduction_keeps_the_causal_chain(recs):
    red = reduce_violation(recs["google:H:N-R02:primary"].events, INVARIANTS)
    assert [e.name for e in red.events] == ["user.message", "llm.context", "user.message", "llm.context",
                                            "tool.propose_booking", "core.proposal", "user.confirm",
                                            "tool.confirm", "core.write"]
    assert red.events[1].outcome["ok"]["intent"] == "book" and red.invariant == NAME
    validate_trace(red.events, contiguous=False)


def test_reconstructed_runs_store_export_and_refuse_plain_replay(recs, tmp_path, capsys):
    db = str(tmp_path / "runs.db")
    run_id = save_run(db, recs["groq:H:N-R02:primary"])
    loaded = load_run(db, run_id)
    assert loaded.events == recs["groq:H:N-R02:primary"].events and loaded.origin == RECONSTRUCTED
    assert Recording.from_doc(loaded.to_doc()).events == loaded.events
    assert cli(["--db", db, "replay", run_id]) == 1
    assert "re-executing that system's code" in capsys.readouterr().err
    assert cli(["--db", db, "show", run_id]) == 0
    assert "[reconstructed]" in capsys.readouterr().out


# -- re-execution of the evaluated CitaLab code (needs CitaLab installed) ---------------

def test_reexecution_reproduces_all_twelve_episodes(episodes):
    pytest.importorskip("citalab")
    from examples.citalab_r02.reexecute import reexecute
    for ep in episodes:
        r = reexecute(ep)
        assert r.faithful, (ep.cell_id, r.divergence, [t for t in r.turns])
        assert ("apt-0004" in r.effects["created"]) == (ep.cell_id in FAILED)


def test_reexecution_detects_a_changed_answer(episodes, monkeypatch):
    pytest.importorskip("citalab")
    import examples.citalab_r02.reexecute as rx
    original = rx.llm_trace

    def tampered(ep):
        events = original(ep)
        content = json.loads(events[0].outcome["ok"]["content"])
        content.update(intent="reschedule", appointment_id="ind-apt-f")
        events[0] = replace(events[0], outcome={"ok": {"content": json.dumps(content)}})
        return events

    monkeypatch.setattr(rx, "llm_trace", tampered)
    ep = next(e for e in episodes if e.cell_id == "google:H:N-R02:primary")
    r = rx.reexecute(ep)
    assert not r.faithful and "Request differs at #3 llm.context" in r.divergence


def test_counterfactual_moves_the_appointment(episodes):
    pytest.importorskip("citalab")
    from examples.citalab_r02.reexecute import gemini_h_counterfactual
    r = gemini_h_counterfactual(episodes)
    assert r.effects == {"created": [], "moved": ["ind-apt-f"]}
    assert r.substitutions == ["call 1 llm.context", "call 3 llm.context"]
    assert all(t.status_match for t in r.turns)

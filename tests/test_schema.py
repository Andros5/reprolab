"""The schema is stable: a recording made today is read, written and replayed the same way,
and recordings from earlier versions are migrated on read."""

import json
import sqlite3
from pathlib import Path

import pytest

from examples.portal_demo.scenario import INVARIANTS, blind_retry, blind_retry_full
from reprolab import (
    REDUCED, Event, Recording, ReplayDivergence, SchemaError, UnsupportedSchema, check, load_run, reduce_violation, save_run,
)
from reprolab import scenario as rl

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "blind_retry_full.v3.json"
GOLDEN_V2 = FIXTURES / "blind_retry_full.v2.json"  # the same run, exported by H2


def golden() -> Recording:
    return Recording.from_doc(GOLDEN.read_text(encoding="utf-8"))


def test_golden_document_round_trips_byte_for_byte():
    text = GOLDEN.read_text(encoding="utf-8")
    assert golden().to_doc() == text


def test_v2_document_migrates_to_exactly_the_v3_golden():
    old = Recording.from_doc(GOLDEN_V2.read_text(encoding="utf-8"))
    assert old.stored_version == 2 and all(e.evidence is None for e in old.events)
    assert old.to_doc() == GOLDEN.read_text(encoding="utf-8")


def test_golden_recording_still_replays_with_the_current_code():
    rec = golden()
    out = rl.replay(blind_retry_full, rec.events)  # offline; diverges if the code or schema drifted
    assert out.result == {"state": "submitted", "id": 2}
    assert [v.seq for v in out.violations] == [9, 13]


def test_golden_recording_reduces_to_the_same_events():
    red = reduce_violation(golden().events, list(INVARIANTS))
    assert red.kept == [2, 3, 4, 5, 8, 9]


def test_golden_marks_injected_faults_as_simulated():
    faults = [e.fault for e in golden().events if e.fault]
    assert faults == [{"kind": "lost_response", "simulated": True}, {"kind": "rate_limited", "simulated": True}]


def _event(**changes):
    base = {"seq": 2, "type": "call", "name": "svc", "kind": "http", "request": {}, "outcome": {"ok": 1},
            "fault": None, "deps": [1], "op": None, "evidence": None}
    return {**base, **changes}


@pytest.mark.parametrize("data, message", [
    ({**_event(), "extra": 1}, "unknown"),
    ({k: v for k, v in _event().items() if k != "deps"}, "missing"),
    (_event(type="sleep"), "type must be"),
    (_event(kind="grpc"), "kind of a call"),
    (_event(outcome={"ok": 1, "error": {}}), "outcome must be"),
    (_event(outcome={"error": {"type": "X", "message": "", "effect": "maybe"}}), "effect"),
    (_event(fault={"kind": "lost_response", "simulated": False}), "simulated: true"),
    (_event(fault={"kind": "meteor", "simulated": True}), "unknown fault"),
    (_event(deps=[2]), "earlier events"),
    (_event(deps=[1, 1]), "unique"),
    (_event(type="clock", kind="", request={"a": 1}), "no kind, request or fault"),
    (_event(type="clock", kind="", request=None, outcome={"error": {"type": "X", "message": "", "effect": "none"}}),
     "cannot fail"),
    (_event(op=""), "op must be"),
    (_event(evidence={"sources": []}), "evidence must be"),
    (_event(evidence={"sources": [], "rule": None}), "exactly one source"),
    (_event(evidence={"sources": [{"source": "f", "pointer": "/0"}], "rule": None}), "source, pointer, sha256"),
    (_event(evidence={"sources": [], "rule": ""}), "rule must be"),
])
def test_strict_validation_rejects_malformed_events(data, message):
    with pytest.raises(SchemaError, match=message):
        Event.from_dict(data)


def test_recorded_runs_are_contiguous_and_reduced_runs_keep_their_dependencies():
    events = golden().events
    with pytest.raises(SchemaError, match="contiguous"):
        Recording([e for e in events if e.seq != 1]).validate()
    with pytest.raises(SchemaError, match="depends on events not in the trace"):
        Recording([e for e in events if e.seq != 4], origin=REDUCED, reduced_from={
            "run": "x", "invariant": "i", "anchor": 9, "kept": [], "original_events": 15, "tests": 1,
            "seconds": 0.0}).validate()
    with pytest.raises(SchemaError, match="reduced_from"):
        Recording(events, origin=REDUCED).validate()


def test_document_with_another_version_or_unknown_header_is_rejected():
    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    with pytest.raises(UnsupportedSchema):
        Recording.from_doc(json.dumps({**doc, "schema_version": 4}))
    with pytest.raises(SchemaError, match="run header"):
        Recording.from_doc(json.dumps({**doc, "run": {**doc["run"], "colour": "red"}}))


def test_v1_runs_written_by_h1_are_migrated_on_read(tmp_path):
    # Exactly what H1 stored: v1 bodies, fault as a plain string, no deps, no op.
    db = tmp_path / "h1.db"
    save_run(db, Recording([]))  # creates the tables
    token = "0c5ffe4d8e77452599c3486cc3ef6e59"
    bodies = [
        {"seq": 1, "type": "random", "name": "token", "kind": "", "request": None, "outcome": {"ok": token},
         "fault": None},
        {"seq": 2, "type": "call", "name": "portal.submit", "kind": "http",
         "request": {"candidate": "synthetic-candidate-1", "job": "job-42", "request_id": token},
         "outcome": {"error": {"type": "LostResponse", "message": "lost (injected)", "effect": "unknown"}},
         "fault": "lost_response"},
    ]
    meta = {"implementation": "blind_retry",
            "faults": [{"name": "portal.submit", "occurrence": 1, "kind": "lost_response"}]}
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO runs VALUES('h1run000000','2026-11-13T10:00:00+00:00','h1',1,?)", (json.dumps(meta),))
        c.executemany("INSERT INTO events VALUES('h1run000000',?,?)", [(b["seq"], json.dumps(b)) for b in bodies])
    rec = load_run(db, "h1run")
    assert rec.stored_version == 1 and rec.origin == "recorded"
    assert rec.events[1].fault == {"kind": "lost_response", "simulated": True}
    assert rec.events[1].deps == (1,)  # inferred from the token that flows into the request
    assert rec.faults == meta["faults"] and rec.extra == {"implementation": "blind_retry"}
    assert check(rec.events, list(INVARIANTS)) == []  # one submission alone violates nothing
    with pytest.raises(ReplayDivergence, match="extra random"):
        rl.replay(blind_retry, rec.events)  # the H1 client retries; this recording stops: divergence


def _cite(seq):
    return {"sources": [{"source": "log.jsonl:1", "pointer": f"/events/{seq}", "sha256": "ab" * 32}], "rule": None}


def test_evidence_must_match_the_origin_of_the_run():
    from dataclasses import replace
    events = golden().events
    with pytest.raises(SchemaError, match="no external evidence"):
        Recording([replace(events[0], evidence=_cite(1)), *events[1:]]).validate()
    cited = [replace(e, evidence=_cite(e.seq)) for e in events]
    Recording(cited, origin="reconstructed").validate()
    with pytest.raises(SchemaError, match=r"must cite its evidence; missing at \[2\]"):
        Recording([cited[0], events[1], *cited[2:]], origin="reconstructed").validate()

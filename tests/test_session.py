import socket

import pytest

from reprolab import (
    EFFECT_NONE, EFFECT_UNKNOWN, LOST_RESPONSE, RATE_LIMITED, BoundaryError, Fault, NetworkBlocked,
    ReplayDivergence, Session, load_run, list_runs, no_network, save_run,
)
from reprolab.store import UnsupportedSchema


def echo(request):
    return {"echo": request}


def test_record_then_replay_returns_recorded_values_without_calling():
    rec = Session.record()
    assert rec.call("svc", {"a": 1}, echo) == {"echo": {"a": 1}}
    t, tok = rec.now(), rec.token()
    events = rec.finish()

    rep = Session.replay(events)
    assert rep.call("svc", {"a": 1}, lambda r: pytest.fail("must not run")) == {"echo": {"a": 1}}
    assert (rep.now(), rep.token()) == (t, tok)
    rep.finish()


def test_lost_response_runs_the_call_and_reports_unknown_effect():
    calls = []
    rec = Session.record(faults=[Fault("svc", 1, LOST_RESPONSE)])
    with pytest.raises(BoundaryError) as err:
        rec.call("svc", {}, lambda r: calls.append(r) or {"id": 1})
    assert calls == [{}]  # the side effect happened
    assert err.value.effect == EFFECT_UNKNOWN
    event = rec.finish()[0]
    assert event.fault == LOST_RESPONSE and event.error["type"] == "LostResponse"


def test_rate_limit_does_not_run_the_call_and_reports_no_effect():
    rec = Session.record(faults=[Fault("svc", 2, RATE_LIMITED)])
    rec.call("svc", {}, echo)
    with pytest.raises(BoundaryError) as err:
        rec.call("svc", {}, lambda r: pytest.fail("must not run"))
    assert err.value.effect == EFFECT_NONE


def test_real_exceptions_are_recorded_and_replayed_as_the_same_boundary_error():
    def boom(_):
        raise ConnectionResetError("peer reset")

    rec = Session.record()
    with pytest.raises(BoundaryError):
        rec.call("svc", {}, boom)
    rep = Session.replay(rec.finish())
    with pytest.raises(BoundaryError) as err:
        rep.call("svc", {}, boom)
    assert (err.value.type, err.value.effect) == ("ConnectionResetError", EFFECT_UNKNOWN)


@pytest.mark.parametrize("act, message", [
    (lambda s: s.call("other", {"a": 1}, echo), "made call 'other'"),
    (lambda s: s.call("svc", {"a": 2}, echo), "Request differs"),
])
def test_replay_divergence_is_explicit(act, message):
    rec = Session.record()
    rec.call("svc", {"a": 1}, echo)
    rep = Session.replay(rec.finish())
    with pytest.raises(ReplayDivergence, match=message):
        act(rep)


def test_replay_that_stops_early_or_goes_further_diverges():
    rec = Session.record()
    rec.call("svc", {}, echo)
    events = rec.finish()
    with pytest.raises(ReplayDivergence, match="recording continues"):
        Session.replay(events).finish()
    rep = Session.replay(events)
    rep.call("svc", {}, echo)
    with pytest.raises(ReplayDivergence, match="extra call"):
        rep.call("svc", {}, echo)


def test_faults_belong_to_recordings_not_replays():
    with pytest.raises(ValueError):
        Session("replay", events=[], faults=[Fault("svc", 1, LOST_RESPONSE)])
    with pytest.raises(ValueError):
        Fault("svc", 0, LOST_RESPONSE)


def test_store_round_trip(tmp_path):
    rec = Session.record(faults=[Fault("svc", 1, LOST_RESPONSE)])
    with pytest.raises(BoundaryError):
        rec.call("svc", {"x": "ñ"}, echo)
    events = rec.finish()
    db = tmp_path / "runs.db"
    run_id = save_run(db, events, label="demo", meta={"k": 1})
    meta, loaded = load_run(db, run_id)
    assert loaded == events and meta == {"label": "demo", "k": 1}
    assert list_runs(db)[0]["events"] == 1


def test_store_rejects_unknown_schema_versions(tmp_path):
    import sqlite3

    db = tmp_path / "runs.db"
    run_id = save_run(db, [])
    with sqlite3.connect(db) as c:
        c.execute("UPDATE runs SET schema_version=99")
    with pytest.raises(UnsupportedSchema):
        load_run(db, run_id)


def test_no_network_blocks_connections_and_restores_them():
    with no_network():
        with pytest.raises(NetworkBlocked):
            socket.create_connection(("127.0.0.1", 9))
    assert socket.create_connection is not None and "refuse" not in socket.create_connection.__name__

import socket

import pytest

from reprolab import (
    EFFECT_NONE, EFFECT_UNKNOWN, LOST_RESPONSE, RATE_LIMITED, BoundaryError, Fault, NetworkBlocked,
    Recording, ReplayDivergence, Session, load_run, list_runs, no_network, save_run,
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
    assert event.fault == {"kind": LOST_RESPONSE, "simulated": True}
    assert event.error["type"] == "LostResponse"


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
    run_id = save_run(db, Recording(events, label="demo", target="m:a", faults=[{"name": "svc", "occurrence": 1,
                                                                             "kind": LOST_RESPONSE}], extra={"k": 1}))
    loaded = load_run(db, run_id[:6])  # a unique prefix is enough
    assert loaded.events == events and loaded.id == run_id
    assert (loaded.label, loaded.target, loaded.extra, loaded.origin) == ("demo", "m:a", {"k": 1}, "recorded")
    assert list_runs(db)[0]["events"] == 1


def test_store_rejects_unknown_schema_versions(tmp_path):
    import sqlite3

    db = tmp_path / "runs.db"
    run_id = save_run(db, Recording([]))
    with sqlite3.connect(db) as c:
        c.execute("UPDATE runs SET schema_version=99")
    with pytest.raises(UnsupportedSchema):
        load_run(db, run_id)


def test_no_network_blocks_connections_and_restores_them():
    with no_network():
        with pytest.raises(NetworkBlocked):
            socket.create_connection(("127.0.0.1", 9))
    assert socket.create_connection is not None and "refuse" not in socket.create_connection.__name__


# -- dependencies and operations -----------------------------------------------------

def test_values_flowing_from_earlier_events_become_dependencies():
    rec = Session.record()
    tok = rec.token()
    found = rec.call("lookup", {}, lambda r: {"ref": "order-12345", "n": 1})
    rec.call("pay", {"idempotency": tok, "order": found["ref"], "n": 1}, echo)
    rec.call("ping", {"n": 1, "short": "ok"}, echo)  # small ints and short strings never link
    events = rec.finish()
    assert [e.deps for e in events] == [(), (), (1, 2), ()]


def test_clock_readings_link_by_value_and_explicit_deps_are_kept():
    rec = Session.record()
    t = rec.now()
    rec.call("log", {"at": t}, echo)
    rec.call("after_log", {}, echo, deps=[rec.last_seq])  # control dependency, declared by hand
    events = rec.finish()
    assert [e.deps for e in events] == [(), (1,), (2,)]
    with pytest.raises(ValueError):
        Session.record().call("x", {}, echo, deps=[1])  # cannot depend on the future


def test_operation_groups_events_and_replay_checks_it():
    rec = Session.record()
    with rec.operation("checkout"):
        rec.call("svc", {}, echo)
    rec.call("svc", {}, echo)
    events = rec.finish()
    assert [e.op for e in events] == ["checkout", None]
    rep = Session.replay(events)
    with pytest.raises(ReplayDivergence, match="Operation differs"):
        rep.call("svc", {}, echo)  # same call outside its recorded operation


def test_fault_parse():
    assert Fault.parse("portal.submit:2:rate_limited") == Fault("portal.submit", 2, RATE_LIMITED)
    for bad in ("portal.submit:x:lost_response", "submit:1", "submit:1:explode"):
        with pytest.raises(ValueError):
            Fault.parse(bad)

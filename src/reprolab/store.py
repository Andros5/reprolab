"""Recordings on disk: one SQLite file of append-only runs, and portable JSON documents.

A run never changes once saved. Reducing a run saves a new run with origin "reduced"
and its provenance; the original stays as it was recorded.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reprolab.events import (
    READABLE_VERSIONS, SCHEMA_VERSION, Event, SchemaError, infer_deps, migrate_v1, migrate_v2, validate_trace,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    schema_version INTEGER NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS events(
    run_id TEXT NOT NULL REFERENCES runs(id),
    seq INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY(run_id, seq)
);
"""

# Where a run comes from.
RECORDED = "recorded"  # an execution captured by a Session
REDUCED = "reduced"  # a subset of another run's events; a trace, not an execution
RECONSTRUCTED = "reconstructed"  # rebuilt from another system's logs; every event cites its evidence
ORIGINS = (RECORDED, REDUCED, RECONSTRUCTED)

_META_FIELDS = ("origin", "target", "faults", "reduced_from", "extra")
_REDUCED_FROM_FIELDS = ("run", "invariant", "anchor", "kept", "original_events", "tests", "seconds")


class UnsupportedSchema(ValueError):
    pass


@dataclass
class Recording:
    events: list[Event]
    label: str = ""
    origin: str = RECORDED
    target: str | None = None  # "module:attribute" of the scenario that produced it
    faults: list[dict[str, Any]] = field(default_factory=list)  # injection plan: {name, occurrence, kind}
    reduced_from: dict[str, Any] | None = None  # provenance of a reduced run
    extra: dict[str, Any] = field(default_factory=dict)  # free-form user metadata
    id: str | None = None
    created_at: str | None = None
    stored_version: int = SCHEMA_VERSION  # schema version on disk (1 = migrated on read)

    def validate(self) -> None:
        if self.origin not in ORIGINS:
            raise SchemaError(f"origin must be one of {list(ORIGINS)}, got {self.origin!r}")
        if (self.origin == REDUCED) != (self.reduced_from is not None):
            raise SchemaError("reduced_from is required for reduced runs and forbidden otherwise")
        if self.reduced_from is not None and set(self.reduced_from) != set(_REDUCED_FROM_FIELDS):
            raise SchemaError(f"reduced_from must have exactly {list(_REDUCED_FROM_FIELDS)}")
        if self.target is not None and (not isinstance(self.target, str) or ":" not in self.target):
            raise SchemaError("target must be null or 'module:attribute'")
        for f in self.faults:
            if not isinstance(f, dict) or set(f) != {"name", "occurrence", "kind"}:
                raise SchemaError(f"fault plan entries are {{name, occurrence, kind}}, got {f!r}")
        if not isinstance(self.extra, dict):
            raise SchemaError("extra must be an object")
        if self.origin == RECORDED and any(e.evidence is not None for e in self.events):
            raise SchemaError("a recorded run is observed by a Session: its events carry no external evidence")
        if self.origin == RECONSTRUCTED and any(e.evidence is None for e in self.events):
            missing = [e.seq for e in self.events if e.evidence is None]
            raise SchemaError(f"every event of a reconstructed run must cite its evidence; missing at {missing}")
        validate_trace(self.events, contiguous=self.origin != REDUCED)

    def _meta(self) -> dict[str, Any]:
        return {"origin": self.origin, "target": self.target, "faults": self.faults,
                "reduced_from": self.reduced_from, "extra": self.extra}

    # -- portable JSON document (export, fixtures) ----------------------------------

    def to_doc(self) -> str:
        doc = {
            "schema_version": SCHEMA_VERSION,
            "run": {"id": self.id, "created_at": self.created_at, "label": self.label, **self._meta()},
            "events": [e.to_dict() for e in self.events],
        }
        return json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_doc(cls, text: str) -> "Recording":
        doc = json.loads(text)
        if not isinstance(doc, dict) or set(doc) != {"schema_version", "run", "events"}:
            raise SchemaError("a recording document has exactly: schema_version, run, events")
        version = doc["schema_version"]
        if version not in (2, SCHEMA_VERSION):  # documents (export) exist since v2
            raise UnsupportedSchema(f"document uses schema v{version}; documents are read in v2 and v{SCHEMA_VERSION}")
        if version == 2:
            doc["events"] = [migrate_v2(e) for e in doc["events"]]
        run = doc["run"]
        if not isinstance(run, dict) or set(run) != {"id", "created_at", "label", *_META_FIELDS}:
            raise SchemaError(f"run header fields must be id, created_at, label, {', '.join(_META_FIELDS)}")
        rec = cls(events=[Event.from_dict(e) for e in doc["events"]], stored_version=version, **run)
        rec.validate()
        return rec


def _connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def save_run(path: str | Path, recording: Recording) -> str:
    """Validate and store a recording; returns its new run id."""
    recording.validate()
    run_id = uuid.uuid4().hex[:12]
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect(path)) as db, db:
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?)",
                   (run_id, created, recording.label, SCHEMA_VERSION,
                    json.dumps(recording._meta(), sort_keys=True, ensure_ascii=False)))
        db.executemany("INSERT INTO events VALUES(?,?,?)",
                       [(run_id, e.seq, e.to_json()) for e in recording.events])
    recording.id, recording.created_at, recording.stored_version = run_id, created, SCHEMA_VERSION
    return run_id


def resolve_id(path: str | Path, ref: str) -> str:
    """Accept a full run id or a unique prefix of one."""
    with closing(_connect(path)) as db:
        ids = [i for (i,) in db.execute("SELECT id FROM runs WHERE id LIKE ? || '%'", (ref,))]
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise KeyError(f"No run {ref!r} in {path}")
    raise KeyError(f"Run prefix {ref!r} is ambiguous in {path}: {', '.join(sorted(ids))}")


def load_run(path: str | Path, ref: str) -> Recording:
    run_id = resolve_id(path, ref)
    with closing(_connect(path)) as db:
        created, label, version, meta = db.execute(
            "SELECT created_at, label, schema_version, meta FROM runs WHERE id=?", (run_id,)).fetchone()
        bodies = [json.loads(b) for (b,) in db.execute(
            "SELECT body FROM events WHERE run_id=? ORDER BY seq", (run_id,))]
    if version not in READABLE_VERSIONS:
        raise UnsupportedSchema(f"Run {run_id} uses event schema v{version}; this ReproLab reads "
                                f"v{', v'.join(map(str, READABLE_VERSIONS))}")
    meta = json.loads(meta)
    if version == 1:
        events = infer_deps(Event.from_dict(migrate_v1(b)) for b in bodies)
        faults = meta.pop("faults", [])
        rec = Recording(events=events, label=label, faults=faults, extra=meta)
    else:
        if set(meta) != set(_META_FIELDS):
            raise SchemaError(f"run {run_id}: metadata fields must be {list(_META_FIELDS)}")
        if version == 2:
            bodies = [migrate_v2(b) for b in bodies]
        rec = Recording(events=[Event.from_dict(b) for b in bodies], label=label, **meta)
    rec = replace(rec, id=run_id, created_at=created, stored_version=version)
    rec.validate()
    return rec


def list_runs(path: str | Path) -> list[dict[str, Any]]:
    with closing(_connect(path)) as db:
        rows = db.execute(
            "SELECT r.id, r.created_at, r.label, r.schema_version, r.meta, COUNT(e.seq) FROM runs r "
            "LEFT JOIN events e ON e.run_id=r.id GROUP BY r.id ORDER BY r.created_at, r.rowid").fetchall()
    out = []
    for i, c, label, version, meta, n in rows:
        meta = json.loads(meta)
        out.append({"id": i, "created_at": c, "label": label, "schema_version": version, "events": n,
                    "origin": meta.get("origin", RECORDED), "target": meta.get("target")})
    return out

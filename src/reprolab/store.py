"""Recordings on disk: one SQLite file, append-only runs of versioned events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reprolab.events import SCHEMA_VERSION, Event

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


class UnsupportedSchema(ValueError):
    pass


def _connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def save_run(path: str | Path, events: list[Event], *, label: str = "", meta: dict[str, Any] | None = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    with closing(_connect(path)) as db, db:
        db.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?)",
            (run_id, datetime.now(timezone.utc).isoformat(), label, SCHEMA_VERSION,
             json.dumps(meta or {}, sort_keys=True, ensure_ascii=False)),
        )
        db.executemany("INSERT INTO events VALUES(?,?,?)", [(run_id, e.seq, e.to_json()) for e in events])
    return run_id


def load_run(path: str | Path, run_id: str) -> tuple[dict[str, Any], list[Event]]:
    with closing(_connect(path)) as db:
        row = db.execute("SELECT label, schema_version, meta FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"No run {run_id!r} in {path}")
        label, version, meta = row
        if version != SCHEMA_VERSION:
            raise UnsupportedSchema(f"Run {run_id} uses event schema v{version}; this ReproLab reads v{SCHEMA_VERSION}")
        events = [Event.from_json(b) for (b,) in db.execute(
            "SELECT body FROM events WHERE run_id=? ORDER BY seq", (run_id,))]
    return {"label": label, **json.loads(meta)}, events


def list_runs(path: str | Path) -> list[dict[str, Any]]:
    with closing(_connect(path)) as db:
        return [
            {"id": i, "created_at": c, "label": l, "events": n}
            for i, c, l, n in db.execute(
                "SELECT r.id, r.created_at, r.label, COUNT(e.seq) FROM runs r "
                "LEFT JOIN events e ON e.run_id=r.id GROUP BY r.id ORDER BY r.created_at")
        ]

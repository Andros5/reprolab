"""Rebuild ReproLab traces from CitaLab's logs of the N-R02 episodes.

Each episode becomes a run with origin "reconstructed". Every event cites its evidence:
the file (path in the CitaLab repository), a JSON pointer inside it, and the SHA-256 of
that document (the whole trace file, or the single line of results.jsonl).

Verbatim events (rule: null) copy their values unchanged from the cited object. Some
fields are left out (timestamps, token counts, provider-opaque data), but nothing is
altered. Events whose position or content had to be derived say so with a rule.

Mapping:
- user turns                -> call "user.message" / "user.confirm" / "user.end" (kind user)
- assistant model calls     -> call "llm.<agent>" (kind llm), from the trace file
- tool calls in turn events -> call "tool.<name>" (kind tool); outcome = policy decision
- proposals, policy, writes -> call "core.proposal" / "core.policy" / "core.write"

Dependencies: inferred by value (ReproLab's default) plus these declared rules, which
over-approximate on purpose so that a reduction never drops a possible cause:
- everything in a turn depends on that turn's user event;
- a tool, proposal, policy or write event depends on every model call before it in the
  same turn;
- a proposal depends on the tool call that created it;
- a write depends on the proposal it executes (same proposal_id) and on the confirmation.

The user simulator's own model calls are not imported: their result is the user turn.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reprolab.events import CALL, Event, infer_deps
from reprolab.store import RECONSTRUCTED, Recording

DATA = Path(__file__).parent / "data"
CAMPAIGN = "output/evaluation/final-independent-v1"
TARGET = "examples.citalab_r02.scenario:r02"

RULE_POSITION_TEXT = ("position inferred: the call writes the reply text and has no entry in the turn's event "
                      "log, so it is placed after the turn's actions")
RULE_POSITION_S1 = ("position inferred: S1 logs the model's tool request after running the tool, so the call "
                    "is placed before the tool it requested")
RULE_JOIN = ("joined by order: the n-th call of this agent in the turn's log is its n-th record in the trace file; "
             "the request comes from the trace record, the outcome is the parsed output CitaLab logged for the turn")


@dataclass(frozen=True)
class Episode:
    cell_id: str
    row: dict[str, Any]
    line: int  # line in CitaLab's results.jsonl
    row_sha256: str
    trace: list[dict[str, Any]]
    trace_source: str
    trace_sha256: str

    @property
    def row_source(self) -> str:
        return f"{CAMPAIGN}/results.jsonl:{self.line}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_episodes(data: Path = DATA) -> list[Episode]:
    """Load the vendored episodes, checking every byte against sources.json."""
    sources = json.loads((data / "sources.json").read_text(encoding="utf-8"))
    lines = (data / "results-r02.jsonl").read_bytes().splitlines()
    traces = {t["cell_id"]: t for t in sources["traces"]}
    episodes = []
    for raw, meta in zip(lines, sources["results"], strict=True):
        if sha256(raw) != meta["sha256"]:
            raise ValueError(f"{meta['cell_id']}: result line does not match its recorded SHA-256")
        row = json.loads(raw)
        t = traces[row["cell_id"]]
        trace_bytes = (data / t["file"]).read_bytes()
        if sha256(trace_bytes) != t["sha256"]:
            raise ValueError(f"{t['file']}: trace file does not match its recorded SHA-256")
        episodes.append(Episode(row["cell_id"], row, meta["line"], meta["sha256"], json.loads(trace_bytes),
                                t["source"], t["sha256"]))
    return episodes


def _assistant_records(ep: Episode) -> list[tuple[int, dict]]:
    return [(i, r) for i, r in enumerate(ep.trace) if r["agent"] != "user-simulator"]


class _Builder:
    def __init__(self, ep: Episode):
        self.ep = ep
        self.events: list[Event] = []

    def cite_row(self, pointer: str) -> dict:
        return {"source": self.ep.row_source, "pointer": pointer, "sha256": self.ep.row_sha256}

    def cite_trace(self, index: int) -> dict:
        return {"source": self.ep.trace_source, "pointer": f"/{index}", "sha256": self.ep.trace_sha256}

    def add(self, name: str, kind: str, request: Any, outcome: dict, sources: list[dict], rule: str | None,
            deps: set[int] = frozenset()) -> int:
        seq = len(self.events) + 1
        self.events.append(Event(seq=seq, type=CALL, name=name, kind=kind, request=request, outcome=outcome,
                                 deps=tuple(sorted(deps)), evidence={"sources": sources, "rule": rule}))
        return seq


def _llm_event(b: _Builder, index: int, record: dict, rule: str | None, extra_sources: list[dict],
               deps: set[int], parsed: Any = None) -> int:
    request = {"agent": record["agent"], "model": record["model"], "prompt_hash": record["prompt_hash"],
               "input": record["input"], "schema": record["schema"]}
    if record["status"] == "success" and parsed is not None:
        outcome = {"ok": parsed}
    elif record["status"] == "success":
        outcome = {"ok": {k: v for k, v in record["output"].items() if k != "extra_content"}}  # opaque provider data
    else:
        outcome = {"error": {"type": record.get("error_type") or "LLMError", "message": str(record["output"])[:200],
                             "effect": "none"}}
    return b.add(f"llm.{record['agent']}", "llm", request, outcome, [b.cite_trace(index), *extra_sources], rule, deps)


def to_recording(ep: Episode) -> Recording:
    b = _Builder(ep)
    records = _assistant_records(ep)
    cursor = 0
    proposals: dict[str, int] = {}  # proposal_id -> seq
    for k, turn in enumerate(ep.row["turns"]):
        turn_records = records[cursor:cursor + len(turn["calls"])]
        cursor += len(turn["calls"])
        if [c["agent"] for c in turn["calls"]] != [r["agent"] for _, r in turn_records]:
            raise ValueError(f"{ep.cell_id} turn {k}: calls and trace records do not line up")

        action = turn["action"]
        user = b.add(f"user.{action}", "user", None, {"ok": {"action": action, "text": turn["user"]}},
                     [b.cite_row(f"/turns/{k}")], None)
        llm_in_turn: list[int] = []
        confirm_seq: int | None = None
        unused = list(turn_records)

        def take(agent: str) -> tuple[int, dict]:
            for pos, (i, r) in enumerate(unused):
                if r["agent"] == agent:
                    return unused.pop(pos)
            raise ValueError(f"{ep.cell_id} turn {k}: no trace record left for agent {agent!r}")

        events = list(enumerate(turn["events"]))
        # S1 logs "agent single" after the tool it requested: put the model call first.
        ordered: list[tuple[int, dict, bool]] = []
        for j, e in events:
            if e["kind"] == "agent" and e["agent"] == "single":
                tool = (e.get("detail") or {}).get("tool")
                at = max((n for n, (_, x, _) in enumerate(ordered)
                          if x["kind"] == "tool" and x["name"] == tool), default=None)
                if at is not None:
                    ordered.insert(at, (j, e, True))
                    continue
            ordered.append((j, e, False))

        for j, e, moved in ordered:
            pointer = f"/turns/{k}/events/{j}"
            kind = e["kind"]
            if kind == "agent":
                i, r = take(e["agent"])
                rule = RULE_POSITION_S1 if moved else RULE_JOIN
                llm_in_turn.append(_llm_event(b, i, r, rule, [b.cite_row(pointer)], {user, *llm_in_turn},
                                              parsed=e.get("detail")))
            elif kind == "tool":
                outcome = {"ok": e.get("decision")}
                seq = b.add(f"tool.{e['name']}", "tool", e.get("arguments"), outcome, [b.cite_row(pointer)], None,
                            {user, *llm_in_turn})
                if e["name"] == "confirm":
                    confirm_seq = seq
            elif kind == "proposal":
                prev = b.events[-1]
                deps = {user, *llm_in_turn} | ({prev.seq} if prev.name.startswith("tool.propose") else set())
                seq = b.add("core.proposal", "tool", None, {"ok": e["proposal"]}, [b.cite_row(pointer)], None, deps)
                proposals[e["proposal"]["proposal_id"]] = seq
            elif kind in ("policy", "write"):
                deps = {user, *llm_in_turn} | ({confirm_seq} if confirm_seq else set())
                body = e["decision"] if kind == "policy" else e["receipt"]
                if kind == "write" and body.get("proposal_id") in proposals:
                    deps.add(proposals[body["proposal_id"]])
                b.add(f"core.{kind}", "tool", None, {"ok": body}, [b.cite_row(pointer)], None, deps)
            else:
                raise ValueError(f"{ep.cell_id}: unknown event kind {kind!r} at {pointer}")
        for i, r in unused:  # reply writers: not in the event log
            llm_in_turn.append(_llm_event(b, i, r, RULE_POSITION_TEXT, [], {user, *llm_in_turn}))

    users = [n for n, m in enumerate(ep.row["transcript"]) if m["role"] == "user"]
    if len(users) > len(ep.row["turns"]):  # the simulated user's closing message
        n = users[-1]
        b.add("user.end", "user", None, {"ok": {"action": "end", "text": ep.row["transcript"][n]["text"]}},
              [b.cite_row(f"/transcript/{n}")], None)

    events = infer_deps(b.events)
    return Recording(
        events, label=f"CitaLab {ep.cell_id}", origin=RECONSTRUCTED, target=TARGET,
        extra={"citalab": {"cell_id": ep.cell_id, "architecture": ep.row["architecture"], "model": ep.row["model"],
                           "provider": ep.row["provider"], "unit_id": ep.row["unit_id"],
                           "oracle_goal": ep.row["checks"]["goal"], "effects": ep.row["effects"],
                           "source": ep.row_source, "sha256": ep.row_sha256}})


def resolve(pointer: str, document: Any) -> Any:
    """RFC 6901 JSON pointer lookup."""
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document

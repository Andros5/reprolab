"""Re-execute CitaLab's evaluated code against the recorded model outputs, offline.

    .venv-citalab/Scripts/python -m examples.citalab_r02.reexecute

Needs a separate environment with CitaLab installed (see the investigation report). The
code must be the evaluated code: the vendoring step checks every source file against the
campaign manifest.

How it works:
- The real ``ChatClient`` builds every request (system prompt, input, schema); only its
  network method ``_post`` is replaced. It crosses a ReproLab ``Session`` in replay mode,
  which checks each request against the recorded one and returns the recorded answer.
  The recorded request is agent, model, prompt hash, input and schema; the HTTP body was
  not logged, so parameters such as temperature are taken from the manifest, not compared.
- CitaLab draws one uninstrumented random value: the proposal id. The adapter serves the
  recorded ids through a second replay session, in order.
- The person's turns come from the evidence, not from the simulator.
- Checked: the same model calls with identical requests, in the same order and all of
  them; the same event log and reply in every turn; and the same final agenda.

A counterfactual mode replaces chosen model outputs and lets every call that has no
recorded answer fail, so CitaLab falls back to its deterministic text. Its result is a
hypothesis test under stated assumptions, never evidence of what happened.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from examples.citalab_r02.importer import DATA, Episode, load_episodes
from reprolab.events import CALL, RANDOM, Event
from reprolab.netguard import no_network
from reprolab.session import BoundaryError, ReplayDivergence, Session


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def llm_trace(ep: Episode) -> list[Event]:
    """The assistant's model calls in the order they were made (the trace file order)."""
    events = []
    for i, record in enumerate(r for r in ep.trace if r["agent"] != "user-simulator"):
        output = {k: v for k, v in record["output"].items() if k != "extra_content"}
        events.append(Event(seq=i + 1, type=CALL, name=f"llm.{record['agent']}", kind="llm",
                            request=_request(record["agent"], record["model"], record["prompt_hash"],
                                             record["input"], record["schema"]),
                            outcome={"ok": output}))
    return events


def token_trace(ep: Episode) -> list[Event]:
    """The proposal ids CitaLab drew, in order, as random events."""
    ids = [e["proposal"]["proposal_id"] for t in ep.row["turns"] for e in t["events"] if e["kind"] == "proposal"]
    return [Event(seq=i + 1, type=RANDOM, name="token", outcome={"ok": pid.removeprefix("prop-")})
            for i, pid in enumerate(ids)]


def _request(agent: str, model: str, prompt_hash: str, trace_input: Any, schema: Any) -> dict:
    return _jsonable({"agent": agent, "model": model, "prompt_hash": prompt_hash, "input": trace_input,
                      "schema": schema})


@dataclass
class TurnCheck:
    n: int
    events_match: bool
    reply_match: bool
    status_match: bool
    first_event_difference: str | None = None


@dataclass
class Reexecution:
    cell_id: str
    initial_state_matches: bool
    turns: list[TurnCheck] = field(default_factory=list)
    llm_calls: int = 0
    divergence: str | None = None
    final_state_matches: bool | None = None
    effects: dict | None = None
    substitutions: list[str] = field(default_factory=list)
    unrecorded_calls: list[str] = field(default_factory=list)

    @property
    def faithful(self) -> bool:
        return (self.divergence is None and self.initial_state_matches and bool(self.final_state_matches)
                and all(t.events_match and t.reply_match and t.status_match for t in self.turns))


def _first_difference(got: list[dict], want: list[dict]) -> str | None:
    for i, (g, w) in enumerate(zip(got, want)):
        if g != w:
            return f"event {i}: re-executed {json.dumps(g, ensure_ascii=False)[:160]} / recorded " \
                   f"{json.dumps(w, ensure_ascii=False)[:160]}"
    if len(got) != len(want):
        return f"re-executed {len(got)} events, recorded {len(want)}"
    return None


def _effects(before: dict, after: dict) -> dict:
    b, a = before["Appointment"], after["Appointment"]
    return {"created": sorted(set(a) - set(b)),
            "moved": sorted(k for k in b if k in a and a[k].get("start") != b[k].get("start"))}


def reexecute(ep: Episode, substitute: dict[int, Any] | None = None) -> Reexecution:
    """Run the evaluated assistant over the recorded turns.

    ``substitute`` maps a model-call position (1-based, in call order) to an output that
    replaces the recorded one: a counterfactual. With substitutions, calls whose request
    no longer matches the recording raise an LLM error, and CitaLab falls back.
    """
    from citalab.assistant import tools as citalab_tools
    from citalab.assistant.engine import Assistant
    from citalab.config import ProviderConfig, Settings
    from citalab.domain.policy import Auth
    from citalab.evaluation.fixtures import build_agenda, build_profiles, reference_time
    from citalab.llm.client import ChatClient, LLMError, _hash

    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    scenarios = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
    row = ep.row
    family = row["scenario"]
    now = reference_time(scenarios)
    agenda = build_agenda(family, now, scenarios.get("agenda"))
    profiles = build_profiles(family.get("profile", {}), now)
    before = agenda.snapshot()
    report = Reexecution(ep.cell_id, _jsonable(before) == row["initial_state"])

    recorded = llm_trace(ep)
    substitute = substitute or {}
    llm = Session.replay(recorded) if not substitute else None
    tokens = Session.replay(token_trace(ep))
    position = 0

    class ReplayClient(ChatClient):
        def _post(self, agent, payload, trace_input, system, schema, prompt_version):  # noqa: ANN001
            nonlocal position
            position += 1
            request = _request(agent, self.provider.model, _hash(system), trace_input, schema)
            if llm is not None:
                message = llm.call(f"llm.{agent}", request, _unreachable, kind="llm")
                return {"choices": [{"message": message}]}
            # Counterfactual: substituted output, else the recorded one if the request still
            # matches the call at this position, else no answer (CitaLab falls back).
            if position in substitute:
                report.substitutions.append(f"call {position} llm.{agent}")
                return {"choices": [{"message": substitute[position]}]}
            if position <= len(recorded) and recorded[position - 1].request == request:
                return {"choices": [{"message": recorded[position - 1].outcome["ok"]}]}
            report.unrecorded_calls.append(f"call {position} llm.{agent}")
            raise LLMError("not-recorded", f"no recorded answer for call {position} ({agent})")

    def _unreachable(_request: Any) -> Any:
        raise AssertionError("a replayed model call reached the network")

    provider = ProviderConfig(row["provider"], "http://offline.invalid", "offline", row["model"], "low")
    settings = Settings(providers={row["provider"]: provider}, temperature=manifest["temperature"],
                        max_output_tokens=manifest["max_output_tokens"], max_attempts=manifest["max_attempts"],
                        timeout_seconds=manifest["timeout_seconds"])
    client = ReplayClient(provider, settings)
    original_uuid = citalab_tools.uuid
    citalab_tools.uuid = SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=tokens.token()))
    try:
        assistant = Assistant(row["architecture"], client, agenda, profiles, Auth("patient-ana", "patient-ana"))
        with no_network():
            for turn in row["turns"]:
                result = assistant.turn(turn["action"], turn["user"])
                got = _jsonable(result.events)
                report.turns.append(TurnCheck(turn["n"], got == turn["events"], result.response == turn["assistant"],
                                              result.status == turn["status"], _first_difference(got, turn["events"])))
        if llm is not None:
            llm.finish()
        report.llm_calls = position
    except (ReplayDivergence, BoundaryError) as exc:
        report.divergence = str(exc)
        report.llm_calls = position
        return report
    finally:
        citalab_tools.uuid = original_uuid
        client.close()
    after = _jsonable(agenda.snapshot())
    if not substitute:
        report.final_state_matches = after == row["final_state"]
    report.effects = _effects(_jsonable(before), after)
    return report


COUNTERFACTUAL_ASSUMPTIONS = (
    "call 1 (context, turn 1) gets the answer Gemini gave in M5 to a byte-identical recorded request",
    "call 3 (context, turn 2) gets Gemini M5's turn-2 answer, given to a similar but different request "
    "(the user worded the choice differently): an assumption, not a recorded answer to this request",
    "the person's turns are the recorded ones; turn 1's reply is unchanged (the writer's request stays identical, "
    "so its recorded text is served), but the person might have answered turn 2's proposal differently",
    "calls with no recorded answer fail, so CitaLab writes its deterministic fallback text",
)


def gemini_h_counterfactual(episodes: list[Episode] | None = None) -> Reexecution:
    """Gemini H, N-R02: what the evaluated code does if the context agent answers as it did in M5."""
    eps = {e.cell_id: e for e in (episodes or load_episodes())}
    h, m5 = eps["google:H:N-R02:primary"], eps["google:M5:N-R02:primary"]
    m5_calls, h_calls = llm_trace(m5), llm_trace(h)
    if m5_calls[0].request != h_calls[0].request or m5_calls[6].name != "llm.context":
        raise ValueError("the evidence no longer supports this counterfactual")
    return reexecute(h, substitute={1: m5_calls[0].outcome["ok"], 3: m5_calls[6].outcome["ok"]})


def main() -> int:
    ok = True
    for ep in load_episodes():
        r = reexecute(ep)
        ok &= r.faithful
        mark = "REPRODUCED" if r.faithful else "DIVERGED"
        print(f"{mark:10} {ep.cell_id:34} model calls {r.llm_calls:2}, turns {len(r.turns)}, "
              f"effects {r.effects}" + (f"\n           {r.divergence}" if r.divergence else ""))
        for t in r.turns:
            if not (t.events_match and t.reply_match and t.status_match):
                print(f"           turn {t.n}: events {t.events_match}, reply {t.reply_match}, status {t.status_match}"
                      f"; {t.first_event_difference}")
    cf = gemini_h_counterfactual()
    print(f"\nCounterfactual, Gemini H N-R02 (a hypothesis test, not evidence): effects {cf.effects}; "
          f"substituted {cf.substitutions}; no recorded answer for {cf.unrecorded_calls}")
    for a in COUNTERFACTUAL_ASSUMPTIONS:
        print(f"  assumption: {a}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

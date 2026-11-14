"""Clients that submit a job application through the fake portal.

All of them route every external interaction through a ReproLab Session, so a run can
be recorded and later replayed offline.

- ``apply_blind_retry``: retries any failed submission. After a lost response it
  submits again and the portal ends up with two applications.
- ``apply_reconciling``: treats an outcome with unknown effect as uncertain. Before
  any new submission it reconciles by looking the application up, like the Swiss Job
  Radar's ``submission_unknown`` state does.
- ``apply_full``: a longer, more realistic flow around either strategy. It reads the
  job posting, drafts a cover letter with an LLM call, and logs failures to telemetry.
  Most of those events are irrelevant to the failure, which makes it a useful input
  for trace reduction.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

from reprolab import EFFECT_NONE, BoundaryError, Session

SUBMIT = "portal.submit"
FIND = "portal.find"
JOB_INFO = "portal.job"
DRAFT = "llm.draft_cover_letter"
LOG = "telemetry.log"


class PortalClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url
        self.timeout = timeout

    def submit(self, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/applications", data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def find(self, query: dict) -> dict:
        url = f"{self.base_url}/applications?candidate={query['candidate']}&job={query['job']}"
        with urllib.request.urlopen(url, timeout=self.timeout) as r:
            return json.load(r)

    def job(self, query: dict) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/jobs/{query['job']}", timeout=self.timeout) as r:
            return json.load(r)


class OfflineClient:
    """Stands in for PortalClient during replay: it must never be reached."""

    def submit(self, payload: dict) -> dict:
        raise AssertionError("replay reached the real portal")

    find = job = submit


def draft_cover_letter(request: dict) -> dict:
    """Stand-in for an LLM call: a fixed template, no model is called.

    In a real agent this would be a model call. Replay reuses the recorded text either
    way, so the stub does not change what the demo shows."""
    return {"text": f"Dear hiring team, {request['candidate']} would like to apply for the role of "
                    f"{request['title']}. (synthetic draft)"}


class Telemetry:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def log(self, entry: dict) -> dict:
        self.entries.append(entry)
        return {"logged": True}


class OfflineTelemetry:
    def log(self, entry: dict) -> dict:
        raise AssertionError("replay reached the real telemetry sink")


OnError = Callable[[BoundaryError], None]


def _submit(session: Session, client, candidate: str, job: str, extra: dict | None) -> dict:
    payload = {"candidate": candidate, "job": job, "request_id": session.token(), **(extra or {})}
    return session.call(SUBMIT, payload, client.submit)


def apply_blind_retry(session: Session, client, candidate: str, job: str, attempts: int = 3, *,
                      extra: dict | None = None, on_error: OnError | None = None) -> dict[str, Any]:
    for _ in range(attempts):
        try:
            return {"state": "submitted", "id": _submit(session, client, candidate, job, extra)["id"]}
        except BoundaryError as error:
            if on_error:
                on_error(error)
            continue  # defect: retries even when the first attempt may have succeeded
    return {"state": "failed"}


def apply_reconciling(session: Session, client, candidate: str, job: str, attempts: int = 3, *,
                      extra: dict | None = None, on_error: OnError | None = None) -> dict[str, Any]:
    for _ in range(attempts):
        try:
            return {"state": "submitted", "id": _submit(session, client, candidate, job, extra)["id"]}
        except BoundaryError as error:
            if on_error:
                on_error(error)
            if error.effect == EFFECT_NONE:
                continue  # nothing happened on the portal: retrying is safe
            # Uncertain: no new submission until the portal says whether it exists.
            try:
                found = session.call(FIND, {"candidate": candidate, "job": job}, client.find)["applications"]
            except BoundaryError:
                return {"state": "submission_unknown"}  # still uncertain: stop and ask a human
            if found:
                return {"state": "submitted", "id": found[0]["id"], "reconciled": True}
    return {"state": "failed"}


IMPLEMENTATIONS = {"blind_retry": apply_blind_retry, "reconciling": apply_reconciling}


def apply_full(session: Session, env, candidate: str, job: str, strategy: str) -> dict[str, Any]:
    """Read the posting, draft a letter, submit with ``strategy``, log what happens."""

    def log(entry: dict) -> None:
        session.call(LOG, {**entry, "at": session.now()}, env.telemetry.log, kind="tool")

    with session.operation(f"apply:{candidate}:{job}"):
        session.now()  # start of the attempt, kept for timing
        posting = session.call(JOB_INFO, {"job": job}, env.client.job)
        letter = session.call(DRAFT, {"candidate": candidate, "title": posting["title"]},
                              draft_cover_letter, kind="llm")["text"]
        result = IMPLEMENTATIONS[strategy](
            session, env.client, candidate, job, extra={"cover_letter": letter},
            on_error=lambda error: log({"event": "submit_failed", "error": error.type}))
        log({"event": "finished", "state": result["state"]})
    return result

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
from collections.abc import Callable
from typing import Any

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


# -- Seeded variants for the explorer (H4) ----------------------------------------------
# Each is a plausible implementation with a known label, so the explorer's results can be
# scored: does it find the defective ones, and does it stay quiet on the correct one?


def apply_retry_on_find_error(session: Session, client, candidate: str, job: str, attempts: int = 3, *,
                              extra: dict | None = None, on_error: OnError | None = None) -> dict[str, Any]:
    """Defective: reconciles after an uncertain outcome, but if the lookup itself fails it
    retries the submission instead of stopping."""
    for _ in range(attempts):
        try:
            return {"state": "submitted", "id": _submit(session, client, candidate, job, extra)["id"]}
        except BoundaryError as error:
            if error.effect == EFFECT_NONE:
                continue
            try:
                found = session.call(FIND, {"candidate": candidate, "job": job}, client.find)["applications"]
            except BoundaryError:
                continue  # defect: still uncertain, yet submits again
            if found:
                return {"state": "submitted", "id": found[0]["id"], "reconciled": True}
    return {"state": "failed"}


def apply_reconciles_once(session: Session, client, candidate: str, job: str, attempts: int = 3, *,
                          extra: dict | None = None, on_error: OnError | None = None) -> dict[str, Any]:
    """Defective: reconciles after the first uncertain outcome only. A second uncertain
    outcome in the same attempt is retried blindly. Needs two faults to show."""
    reconciled = False
    for _ in range(attempts):
        try:
            return {"state": "submitted", "id": _submit(session, client, candidate, job, extra)["id"]}
        except BoundaryError as error:
            if error.effect == EFFECT_NONE or reconciled:
                continue  # defect when reconciled: the new outcome is just as uncertain
            reconciled = True
            try:
                found = session.call(FIND, {"candidate": candidate, "job": job}, client.find)["applications"]
            except BoundaryError:
                return {"state": "submission_unknown"}
            if found:
                return {"state": "submitted", "id": found[0]["id"], "reconciled": True}
    return {"state": "failed"}


def apply_journaled(session: Session, client, candidate: str, job: str, attempts: int = 3, *,
                    extra: dict | None = None, on_error: OnError | None = None,
                    journal: dict | None = None) -> dict[str, Any]:
    """Correct, including across crashes: like the Swiss Job Radar's ``submission_unknown``
    state, it writes "pending" to a durable journal before submitting, and a restarted
    worker reconciles a pending submission before anything else. Malformed responses are
    treated as uncertain outcomes, not trusted."""
    journal = {} if journal is None else journal
    key = f"{candidate}:{job}"

    def lookup() -> list | None:  # None: still unknown
        try:
            found = session.call(FIND, {"candidate": candidate, "job": job}, client.find).get("applications")
        except BoundaryError:
            return None
        return found if isinstance(found, list) and all("id" in a for a in found) else None

    def settle(found: list | None) -> dict[str, Any] | None:
        if found is None:
            return {"state": "submission_unknown"}  # stop and ask a human
        if found:
            journal[key] = "done"
            return {"state": "submitted", "id": found[0]["id"], "reconciled": True}
        return None  # certainly not submitted: a new submission is safe

    if journal.get(key) == "pending":  # a previous worker may have submitted
        settled = settle(lookup())
        if settled:
            return settled
    for _ in range(attempts):
        journal[key] = "pending"
        try:
            response = _submit(session, client, candidate, job, extra)
        except BoundaryError as error:
            if on_error:
                on_error(error)
            if error.effect == EFFECT_NONE:
                continue
            settled = settle(lookup())
            if settled:
                return settled
            continue
        if "id" not in response:  # malformed: the portal may or may not have stored it
            settled = settle(lookup())
            if settled:
                return settled
            continue
        journal[key] = "done"
        return {"state": "submitted", "id": response["id"]}
    return {"state": "failed"}


IMPLEMENTATIONS = {
    "blind_retry": apply_blind_retry, "reconciling": apply_reconciling,
    "retry_on_find_error": apply_retry_on_find_error, "reconciles_once": apply_reconciles_once,
    "journaled": apply_journaled,
}
# Ground truth for scoring the explorer: which variants violate the property under which faults.
LABELS = {
    "blind_retry": "defective",
    "retry_on_find_error": "defective",
    "reconciles_once": "defective (needs two faults)",
    "reconciling": "correct within one process; defective across a crash",
    "journaled": "correct",
}


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

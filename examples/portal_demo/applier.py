"""Two clients that submit a job application through the fake portal.

Both route every external interaction through a ReproLab Session, so a run can be
recorded and later replayed offline.

- ``apply_blind_retry``: retries any failed submission. After a lost response it
  submits again and the portal ends up with two applications.
- ``apply_reconciling``: treats an outcome with unknown effect as uncertain. Before
  any new submission it reconciles by looking the application up, like the Swiss Job
  Radar's ``submission_unknown`` state does.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from reprolab import EFFECT_NONE, BoundaryError, Session

SUBMIT = "portal.submit"
FIND = "portal.find"


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


class OfflineClient:
    """Stands in for PortalClient during replay: it must never be reached."""

    def submit(self, payload: dict) -> dict:
        raise AssertionError("replay reached the real portal")

    find = submit


def _submit(session: Session, client, candidate: str, job: str) -> dict:
    payload = {"candidate": candidate, "job": job, "request_id": session.token()}
    return session.call(SUBMIT, payload, client.submit)


def apply_blind_retry(session: Session, client, candidate: str, job: str, attempts: int = 3) -> dict[str, Any]:
    for _ in range(attempts):
        try:
            return {"state": "submitted", "id": _submit(session, client, candidate, job)["id"]}
        except BoundaryError:
            continue  # defect: retries even when the first attempt may have succeeded
    return {"state": "failed"}


def apply_reconciling(session: Session, client, candidate: str, job: str, attempts: int = 3) -> dict[str, Any]:
    for _ in range(attempts):
        try:
            return {"state": "submitted", "id": _submit(session, client, candidate, job)["id"]}
        except BoundaryError as error:
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

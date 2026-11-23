"""Drive the Swiss Job Radar's evaluated ``send()`` with a fake browser page.

The radar's code is used as it is: ``radar.portals.inspect`` and ``send``, and the
application state machine in ``radar.workspace.Workspace``. Only the browser is
replaced, by ``FakePage``, which answers the few Playwright calls ``send()`` makes from a
synthetic hosted form. Two of them are the network seam and cross a ReproLab ``Session``:

- ``portal.click``: the final "Submit application" click, the one that takes effect;
- ``portal.confirmation``: the wait for the confirmation text after it.

Everything else ``send()`` reads (the form fields, the body text, the captcha check) is
static synthetic content and is not instrumented.

All data is synthetic. The radar's workspace lives in a temporary directory, and the
process works inside it, so the radar's own ``.env`` and ``profile.md`` are never read.
``RADAR_PREVIEW_MODE`` is read by ``send()`` from the process environment; the adapter
pins it to "0" for its own scope only and restores it afterwards. That is safe because
nothing here can reach a real portal: the page is fake, and the live environment runs
under ``reprolab.no_network``.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reprolab.session import Session

CLICK, CONFIRMATION = "portal.click", "portal.confirmation"
HOST = "jobs.ashbyhq.com"  # one of the hosts radar.portals.HOSTS supports
URL = f"https://{HOST}/synthetic-co/0001"
BUTTON = "Submit application"
FORM_TEXT = "Synthetic Co - Backend Developer (synthetic posting)\nEmail\nResume\nSubmit application"
CONFIRMATION_TEXT = "Thank you for applying. Your application has been received."
FORM = [  # what radar.portals.fields() reads from the synthetic form
    {"index": 0, "name": "email", "id": "email", "type": "email", "required": True, "label": "Email",
     "options": []},
    {"index": 1, "name": "resume", "id": "resume", "type": "file", "required": True, "label": "Resume",
     "options": []},
]
PROFILE = {"name": "Synthetic Candidate", "email": "candidate@example.invalid", "location": "Synthetic City",
           "languages": {"English": "B2"}, "facts": []}
JOB = {"source": "ashby", "company": "Synthetic Co", "external_id": "0001", "title": "Backend Developer",
       "url": URL, "locations": ["Zurich"], "description": "Synthetic posting for a ReproLab test. " * 5}
CV = b"%PDF-1.4\n% synthetic CV for a ReproLab test\n"


class SyntheticPortal:
    """The remote side. It outlives a worker crash: what it received stays received."""

    def __init__(self) -> None:
        self.received: list[dict] = []

    def submit(self, request: dict) -> None:
        self.received.append(request)
        return None  # Playwright's click() returns nothing

    def confirmation(self, request: dict) -> dict:
        if not self.received:
            raise TimeoutError("the confirmation text never appeared")
        assert re.search(request["pattern"], CONFIRMATION_TEXT, re.I)
        return {"body": CONFIRMATION_TEXT}


class OfflinePortal:
    """For replay: every answer comes from the recording."""

    received: list[dict] = []

    def submit(self, request: dict) -> None:
        raise AssertionError("a replayed click reached the portal")

    confirmation = submit


class FakePage:
    """The Playwright calls radar.portals.inspect/send make, answered from the synthetic form."""

    def __init__(self, session: Session | None, portal: Any):
        self.session, self.portal = session, portal
        self.url, self.body, self.values = "about:blank", "", {}

    def goto(self, url: str, wait_until: str | None = None) -> None:
        self.url, self.body, self.values = url, FORM_TEXT, {}

    def locator(self, selector: str) -> _Locator:
        return _Locator(self, selector)

    def get_by_role(self, role: str, name: re.Pattern) -> _Button:
        assert role == "button"
        return _Button(self, 1 if name.search(BUTTON) else 0)

    def get_by_text(self, pattern: re.Pattern) -> _Text:
        return _Text(self, pattern)


class _Locator:
    def __init__(self, page: FakePage, selector: str):
        self.page, self.selector = page, selector

    def evaluate_all(self, _script: str) -> list[dict]:
        assert self.selector.startswith("input:not([type=hidden])"), self.selector
        return copy.deepcopy(FORM)

    def inner_text(self) -> str:
        assert self.selector == "body", self.selector
        return self.page.body

    def nth(self, index: int) -> _Field:
        return _Field(self.page, FORM[index]["name"])

    def count(self) -> int:
        if self.selector == ":invalid":  # a required field left empty is invalid in a browser
            return sum(1 for f in FORM if f["required"] and f["name"] not in self.page.values)
        assert "recaptcha" in self.selector, self.selector
        return 0


@dataclass
class _Field:
    page: FakePage
    name: str

    def fill(self, value: str) -> None:
        self.page.values[self.name] = value

    def set_input_files(self, path: str) -> None:  # the request carries the file's hash, not its temp path
        self.page.values[self.name] = {"sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


@dataclass
class _Button:
    page: FakePage
    matches: int

    def count(self) -> int:
        return self.matches

    def click(self, timeout: int | None = None) -> None:
        p = self.page
        request = {"url": p.url, "button": BUTTON, "fields": p.values, "timeout": timeout}
        return p.session.call(CLICK, request, p.portal.submit)


@dataclass
class _Text:
    page: FakePage
    pattern: re.Pattern

    @property
    def first(self) -> _Text:
        return self

    def wait_for(self, timeout: int | None = None) -> None:
        p = self.page
        shown = p.session.call(CONFIRMATION, {"url": p.url, "pattern": self.pattern.pattern, "timeout": timeout},
                               p.portal.confirmation)
        p.body = shown.get("body", "") if isinstance(shown, dict) else ""


# -- the radar's workspace -----------------------------------------------------------

@contextmanager
def inside(root: Path) -> Iterator[None]:
    """Work in ``root`` with preview mode pinned off, restoring both afterwards."""
    cwd, preview = os.getcwd(), os.environ.get("RADAR_PREVIEW_MODE")
    os.chdir(root)
    os.environ["RADAR_PREVIEW_MODE"] = "0"
    try:
        yield
    finally:
        os.chdir(cwd)
        if preview is None:
            os.environ.pop("RADAR_PREVIEW_MODE", None)
        else:
            os.environ["RADAR_PREVIEW_MODE"] = preview


def approved_application(root: Path) -> str:
    """A synthetic application, inspected and approved through the radar's own API, on a
    portal whose policy allows submission. Returns its id."""
    from radar.portals import inspect
    from radar.workspace import Workspace, encoded

    cv = root / "artifacts" / "cv.pdf"
    cv.parent.mkdir(parents=True)
    cv.write_bytes(CV)
    with inside(root), Workspace(root / "radar.db") as ws:
        ws.save_profile(PROFILE)
        aid = ws.create_application(ws.upsert(JOB))["id"]
        ws.save_package(aid, {"artifacts": [{"kind": "cv", "path": str(cv),
                                             "sha256": hashlib.sha256(CV).hexdigest()}],
                              "answers": {}, "blockers": []})
        inspect(ws, aid, FakePage(None, None))
        ws.approve(aid, ws.package_hash(ws.application(aid)))
        with ws.db:
            ws.db.execute("INSERT INTO portal_policies VALUES(?,?)", (HOST, encoded(
                {"capability": "submit", "reviewed_at": "synthetic", "terms_url": "https://example.invalid/terms"})))
    return aid


def restart_web(db: Path) -> None:
    """The web server's real startup recovery (its FastAPI lifespan), without serving."""
    from radar.web import create_app

    app = create_app(db, token="t" * 32, scheduler=False)

    async def cycle() -> None:
        async with app.router.lifespan_context(app):
            pass

    # Stepped by hand: without the scheduler the lifespan never suspends, and an asyncio
    # loop would open a socket pair, which the live environment's network guard refuses.
    try:
        cycle().send(None)
    except StopIteration:
        return
    raise RuntimeError("the radar's startup recovery suspended; it needs an event loop now")


@dataclass
class RadarEnv:
    root: Path
    aid: str
    portal: Any
    starts: int = 0  # durable: how many times the worker has started
    refusals: list[str] = field(default_factory=list)

    @property
    def db(self) -> Path:
        return self.root / "radar.db"


@contextmanager
def radar_env(portal: Any) -> Iterator[RadarEnv]:
    root = Path(tempfile.mkdtemp(prefix="reprolab-radar-"))
    try:
        yield RadarEnv(root, approved_application(root), portal)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def db_state(env: RadarEnv) -> dict[str, Any]:
    """The radar's own record of the application: the oracle, separate from the trace."""
    from radar.workspace import Workspace

    with inside(env.root), Workspace(env.db) as ws:
        app = ws.application(env.aid)
        kinds = [e["kind"] for e in app["events"]]
    return {"state": app["state"], "began": kinds.count("sending"), "receipt": bool(app["receipt"]),
            "events": [k for k in kinds if k not in ("package_updated", "approved")],
            "portal_received": len(env.portal.received), "refusals": list(env.refusals)}

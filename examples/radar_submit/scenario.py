"""The radar's submission path as ReproLab scenarios.

    reprolab explore examples.radar_submit.scenario:worker_restart --seed 0 --budget 200

The code under test is ``radar.portals.send``, called the way ``radar-web browser <id>
send`` calls it (``portals.runner``: open the workspace, call ``send``), by an insistent
operator: up to ``ATTEMPTS`` times, until the radar records the application as submitted.
It does not look at the state first, so only the radar's own guard can stop a re-send.

- ``worker_restart``: after a simulated crash only the process that ran ``send`` restarts.
- ``web_restart``: the web server restarts too, and its real startup recovery runs.
- ``rearm_control``: a deliberately defective operator who, after an uncertain outcome,
  puts the application back to "approved" with the radar's ``set_state``. No radar code
  path does this; it is the negative control that shows the property can fail here.

Oracle: the radar's own database (state, how many submissions it began, receipt) and the
synthetic portal (what it received). It is read after recording and never replayed.
"""

from __future__ import annotations

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from examples.radar_submit.adapter import (
    FakePage,
    OfflinePortal,
    RadarEnv,
    SyntheticPortal,
    db_state,
    inside,
    radar_env,
    restart_web,
)
from examples.radar_submit.invariants import no_resend_after_uncertain
from reprolab import BoundaryError, Scenario, no_network

ATTEMPTS = 3
INVARIANTS = (no_resend_after_uncertain,)


def _operator(web_restart: bool, rearm: bool = False):
    def run(session, env: RadarEnv) -> dict[str, Any]:
        from radar.portals import send
        from radar.workspace import Workspace

        if env.starts and web_restart:
            restart_web(env.db)
        env.starts += 1
        with inside(env.root):
            for _ in range(ATTEMPTS):
                with Workspace(env.db) as ws:
                    state = ws.application(env.aid)["state"]
                    if state == "submitted":
                        break
                    if rearm and state == "submission_unknown":
                        ws.set_state(env.aid, "approved", "control: re-armed without reconciling")
                    try:
                        send(ws, env.aid, FakePage(session, env.portal))
                    except BoundaryError:
                        pass  # the click's outcome is unknown; send() has recorded it
                    except ValueError as refused:
                        env.refusals.append(str(refused))
        return {"state": db_state(env)["state"], "refusals": len(env.refusals)}

    return run


@contextmanager
def _live() -> Iterator[RadarEnv]:
    with no_network(), radar_env(SyntheticPortal()) as env:
        yield env


@contextmanager
def _offline_env() -> Iterator[RadarEnv]:
    with radar_env(OfflinePortal()) as env:
        yield env


class _Offline:
    """``Scenario.offline`` returns the environment itself; the radar's local workspace is
    rebuilt for the replay (it is local state, not a boundary). The previous replay's
    workspace is removed when the next one starts, and the last one at exit."""

    def __init__(self) -> None:
        self._cm = None
        atexit.register(self.close)

    def __call__(self) -> RadarEnv:
        self.close()
        self._cm = _offline_env()
        return self._cm.__enter__()

    def close(self) -> None:
        if self._cm is not None:
            self._cm.__exit__(None, None, None)
            self._cm = None


def _oracle_check(reading: dict[str, Any]) -> str | None:
    if reading["began"] > 1:
        return f"the radar began {reading['began']} submissions of one application"
    if reading["state"] == "submitted" and not reading["portal_received"]:
        return "the radar recorded a receipt the portal never received"
    if reading["state"] == "approved" and reading["portal_received"]:
        return "the application is re-armed for sending after the portal received it"
    return None


def _scenario(name: str, description: str, **kwargs) -> Scenario:
    return Scenario(name=name, invariants=INVARIANTS, run=_operator(**kwargs), live=_live, offline=_Offline(),
                    oracle=db_state, oracle_check=_oracle_check, description=description)


worker_restart = _scenario("radar_worker_restart", "radar send(); after a crash only the worker restarts",
                           web_restart=False)
web_restart = _scenario("radar_web_restart", "radar send(); after a crash the web server's recovery runs too",
                        web_restart=True)
rearm_control = _scenario("radar_rearm_control", "negative control: the operator re-arms with set_state",
                          web_restart=True, rearm=True)
SCENARIOS = {s.name: s for s in (worker_restart, web_restart, rearm_control)}

"""The portal scenarios, as ReproLab targets, plus helpers used by the demo and tests.

CLI targets:
    examples.portal_demo.scenario:blind_retry        short flow, defective retry
    examples.portal_demo.scenario:reconciling        short flow, reconciles first
    examples.portal_demo.scenario:blind_retry_full   posting + LLM draft + telemetry
    examples.portal_demo.scenario:reconciling_full
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from examples.portal_demo.applier import (
    IMPLEMENTATIONS, OfflineClient, OfflineTelemetry, PortalClient, Telemetry, apply_full,
)
from examples.portal_demo.invariants import no_blind_resubmit
from examples.portal_demo.portal import Portal
from reprolab import Event, Fault, Scenario
from reprolab import scenario as rl
from reprolab.invariants import Violation

CANDIDATE, JOB = "synthetic-candidate-1", "job-42"
INVARIANTS = (no_blind_resubmit,)


@dataclass
class PortalEnv:
    client: Any
    telemetry: Any
    portal: Portal | None = None


@contextmanager
def _live() -> Iterator[PortalEnv]:
    with Portal() as portal:
        yield PortalEnv(PortalClient(portal.url), Telemetry(), portal)


def _offline() -> PortalEnv:
    return PortalEnv(OfflineClient(), OfflineTelemetry())


def _oracle(env: PortalEnv) -> dict[str, Any]:
    return {"applications": env.portal.count(CANDIDATE, JOB)}


def _short(strategy: str) -> Scenario:
    return Scenario(
        name=strategy, invariants=INVARIANTS, live=_live, offline=_offline, oracle=_oracle,
        run=lambda session, env: IMPLEMENTATIONS[strategy](session, env.client, CANDIDATE, JOB),
        description=f"submit one application with the {strategy} client")


def _full(strategy: str) -> Scenario:
    return Scenario(
        name=f"{strategy}_full", invariants=INVARIANTS, live=_live, offline=_offline, oracle=_oracle,
        run=lambda session, env: apply_full(session, env, CANDIDATE, JOB, strategy),
        description=f"read the posting, draft a letter (stub LLM), submit with {strategy}, log to telemetry")


blind_retry = _short("blind_retry")
reconciling = _short("reconciling")
blind_retry_full = _full("blind_retry")
reconciling_full = _full("reconciling")
SCENARIOS = {s.name: s for s in (blind_retry, reconciling, blind_retry_full, reconciling_full)}


def target(name: str) -> str:
    return f"{__name__}:{name}"


@dataclass
class Run:
    implementation: str
    result: dict[str, Any]
    events: list[Event]
    violations: list[Violation]
    portal_applications: int | None = None  # oracle, only known when recording
    faults: list[Fault] = field(default_factory=list)


def record(implementation: str, faults: list[Fault]) -> Run:
    out = rl.record(SCENARIOS[implementation], faults)
    return Run(implementation, out.result, out.events, out.violations, out.oracle["applications"], out.faults)


def replay(implementation: str, events: list[Event]) -> Run:
    """Re-run the code against a recording with the network disabled."""
    out = rl.replay(SCENARIOS[implementation], events)
    return Run(implementation, out.result, out.events, out.violations)

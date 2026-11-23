"""Quickstart: ReproLab around your own code, in one file.

    python -m examples.quickstart
    reprolab explore examples.quickstart:naive --budget 50

A worker pays an invoice through an external service. The service is an in-memory
stand-in here; in real code it would be an HTTP API, an LLM or a tool. Three steps:

1. route the external call through ``session.call``;
2. write the business property as a function of the recorded trace;
3. wrap both in a ``Scenario`` so the CLI can record, replay, reduce and explore it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from reprolab import BoundaryError, Event, Fault, Scenario, Session, Violation
from reprolab import scenario as rl

INVOICE = {"invoice": "INV-7", "amount": 120}


class Bank:
    """Stand-in for an external service. Its state is the oracle: what really happened."""

    def __init__(self) -> None:
        self.charges: list[dict] = []

    def charge(self, request: dict) -> dict:
        self.charges.append(request)
        return {"charge_id": len(self.charges)}

    def find(self, request: dict) -> dict:
        return {"charges": [c for c in self.charges if c["invoice"] == request["invoice"]]}


class Unreachable:
    """The environment during replay: any real call is a bug, because answers come from the recording."""

    def __getattr__(self, name: str):
        def unreachable(request):
            raise AssertionError(f"replay tried to reach the service ({name})")
        return unreachable


# 1. The code under test. Every external call goes through the session.

def pay_naive(session: Session, bank: Bank) -> dict:
    """Retries blindly: if the response is lost after the charge happened, it charges twice."""
    for _ in range(3):
        try:
            return session.call("bank.charge", INVOICE, bank.charge)
        except BoundaryError:
            continue
    return {"state": "gave up"}


def pay_reconciling(session: Session, bank: Bank) -> dict:
    """After an uncertain outcome, it asks the service before charging again."""
    for _ in range(3):
        try:
            return session.call("bank.charge", INVOICE, bank.charge)
        except BoundaryError as error:
            if error.effect == "none":
                continue  # the service says nothing happened: safe to retry
            try:
                found = session.call("bank.find", {"invoice": INVOICE["invoice"]}, bank.find)
            except BoundaryError:
                return {"state": "unknown"}  # cannot tell: stop and let a person decide
            if found["charges"]:
                return {"state": "already charged"}
    return {"state": "gave up"}


# 2. The business property, read from the trace alone.

def charge_at_most_once(events: list[Event]) -> list[Violation]:
    """Never charge again after a charge that happened or may have happened, unless a lookup said it did not."""
    uncertain_or_done: int | None = None
    violations = []
    for e in events:
        if e.name == "bank.charge":
            if uncertain_or_done is not None:
                violations.append(Violation("charge-at-most-once", e.seq,
                                            f"charges again after #{uncertain_or_done} without checking"))
            if e.ok or (e.error or {}).get("effect") == "unknown":
                uncertain_or_done = e.seq
        elif e.name == "bank.find" and e.ok:
            answer = e.outcome["ok"]
            if isinstance(answer, dict) and answer.get("charges") == []:
                uncertain_or_done = None  # a well-formed lookup settled it: nothing was charged
    return violations


# 3. Scenarios: how to run the code live, offline, and what the real state was.

@contextmanager
def _live() -> Iterator[Bank]:
    yield Bank()


def _scenario(name: str, run) -> Scenario:
    return Scenario(
        name=name, run=run, invariants=(charge_at_most_once,), live=_live, offline=Unreachable,
        oracle=lambda bank: {"charges": len(bank.charges)},
        oracle_check=lambda reading: f"{reading['charges']} charges for one invoice" if reading["charges"] > 1 else None,
        description="pay one invoice through an external service")


naive = _scenario("naive", pay_naive)
reconciling = _scenario("reconciling", pay_reconciling)


def main() -> None:
    lost = [Fault("bank.charge", 1, "lost_response")]  # simulated: the charge happens, the answer is lost
    for scenario in (naive, reconciling):
        recorded = rl.record(scenario, lost)
        replayed = rl.replay(scenario, recorded.events)  # network disabled; answers come from the recording
        print(f"{scenario.name:12} result {recorded.result}  real charges {recorded.oracle['charges']}")
        for v in recorded.violations:
            print(f"{'':12} {v}")
        same = [e.to_dict() for e in replayed.events] == [e.to_dict() for e in recorded.events]
        print(f"{'':12} offline replay: {'identical' if same else 'DIVERGED'}, "
              f"{len(replayed.violations)} violation(s)\n")


if __name__ == "__main__":
    main()

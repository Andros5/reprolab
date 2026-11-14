# ReproLab

Record, replay and reduce failures of agent and automation workflows, and turn them into regression tests for business properties.

**Status:** milestone H1 (proof of concept). Python standard library and SQLite, no external services.

## The H1 demo

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # bin/python on Linux/macOS
.venv/Scripts/python -m examples.portal_demo
```

A client submits a job application to a fake portal running on localhost. ReproLab injects a **lost response**: the portal stores the application, but the client never sees the confirmation.

1. **Blind retry client.** It submits again, and the portal now holds two applications. The property *no blind resubmit* is checked on the recorded trace and flags event #4.
2. **Offline replay.** The saved recording is replayed with the network disabled. It produces the same trace, the same result and the same violation.
3. **Reconciling client.** Under the same fault it looks the application up before doing anything else. The property holds, and the portal keeps exactly one application.

This mirrors the Swiss Job Radar's `submission_unknown` state. That state is a correct safeguard, and the blind-retry client is a deliberately defective variant that shows what the safeguard prevents.

## How it works

- **Boundaries.** Code routes external interactions through a `Session`: `session.call(name, request, fn)`, `session.now()` and `session.token()`.
- **Recording.** In record mode the real function runs, optionally with an injected fault. The outcome is stored as a versioned event: the result, or the error together with what the caller can know about side effects (`effect: none | unknown`).
- **Replay.** In replay mode nothing external runs. Each call must match the next recorded event, or a `ReplayDivergence` explains the difference. Recorded outcomes are returned or raised again.
- **Invariants.** Invariants read only the trace, so the original run and every replay get the same verdict. The portal's real state serves as a separate oracle while recording.

## Limits (by design)

- Determinism covers only the instrumented boundaries: calls, clock and random tokens. Threads, the OS and uninstrumented I/O are out of scope.
- Replay reuses recorded outcomes. It does not show that an LLM or a service would answer the same way again.
- Injected faults are simulations and are marked as such in each event (`fault`).
- By default, an unexpected exception counts as `effect: unknown`, which is the conservative choice. Adapters can classify errors more precisely.

## Roadmap

| Milestone | Done when |
|---|---|
| H1 | Local portal, capture, offline replay, and a test that tells the correct implementation from the defective one ✅ |
| H2 | Stable versioned schema, a record/replay CLI, and a reduction that keeps the same violated property |
| H3 | A documented investigation of a real agent failure (CitaLab), separating original evidence from reconstructions |
| H4 | A bounded explorer of fault schedules over the boundaries, with seeded scenarios, reduced counterexamples and metrics |
| H5 | Visual comparison and differential replay against a new version of the code |

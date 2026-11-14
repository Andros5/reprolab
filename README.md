# ReproLab

Record, replay and reduce failures of agent and automation workflows, and turn them into regression tests for business properties.

**Status:** milestone H2. Python standard library and SQLite, no external services.

## The demo

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # bin/python on Linux/macOS
.venv/Scripts/python -m examples.portal_demo
```

A client submits a job application to a fake portal running on localhost. ReproLab injects a **lost response**: the portal stores the application, but the client never sees the confirmation.

1. **Blind retry client.** It submits again, and the portal now holds two applications. The property *no blind resubmit* is checked on the recorded trace and flags event #4.
2. **Offline replay.** The saved recording is replayed with the network disabled. It produces the same trace, the same result and the same violation.
3. **Reconciling client.** Under the same fault it looks the application up before doing anything else. The property holds, and the portal keeps exactly one application.
4. **Reduction.** A longer flow reads the job posting, drafts a cover letter with an LLM call (a stub; no model is called) and logs to telemetry. It suffers a lost response and then a rate limit. Its 15-event trace reduces to the 6 events the violation needs. The posting and the draft stay in, because the submissions use their output.

This mirrors the Swiss Job Radar's `submission_unknown` state. That state is a correct safeguard, and the blind-retry client is a deliberately defective variant that shows what the safeguard prevents. All data is synthetic.

## Command line

```bash
reprolab record examples.portal_demo.scenario:blind_retry_full \
    --fault portal.submit:1:lost_response --fault portal.submit:2:rate_limited
reprolab list
reprolab show <run>             # header, trace, dependencies, violations
reprolab replay <run>           # re-run the recorded code offline; exit 1 on divergence
reprolab reduce <run>           # saves a new, reduced run; the original is kept
reprolab export <run> -o run.json
```

Runs are stored in `./reprolab.db` (or `--db`, or `$REPROLAB_DB`). A run can be named by a unique prefix of its id. `replay --target` runs a recording against other code, for example a fixed client, and reports the first point where it diverges.

## How it works

- **Boundaries.** Code routes external interactions through a `Session`: `session.call(name, request, fn)`, `session.now()` and `session.token()`. `session.operation(id)` groups the events of one business operation.
- **Recording.** In record mode the real function runs, optionally with an injected fault. The outcome is stored as an event: the result, or the error together with what the caller can know about side effects (`effect: none | unknown`).
- **Schema.** Events and runs follow a versioned, strictly validated schema ([docs/schema.md](docs/schema.md)). A frozen v2 recording in the tests must round-trip byte for byte and still replay. H1's v1 recordings are migrated on read.
- **Dependencies.** Each event lists the earlier events it depends on. They are inferred when a value one event produced (a token, an id, a drafted text, a timestamp) reappears in a later request, and can also be declared explicitly.
- **Replay.** In replay mode nothing external runs. Each call must match the next recorded event, or a `ReplayDivergence` explains the difference. Recorded outcomes are returned or raised again.
- **Invariants.** Invariants read only the trace, so the original run and every replay get the same verdict. The portal's real state serves as a separate oracle while recording.
- **Reduction.** Delta debugging (ddmin) over the events of a trace. Each candidate is closed under dependencies, so an event is never kept without the events it uses. A candidate is accepted only if the same invariant is still violated **at the same event**, so the search cannot slide to a different failure. The result is saved as a new run with `origin: reduced` and its provenance.

## Measured so far

Measured on the demo's longer flow only: the trace reduces from 15 to 6 events, after 55 distinct candidates, in a few milliseconds. These numbers come from one synthetic scenario, not from a benchmark.

## Limits (by design)

- Determinism covers only the instrumented boundaries: calls, clock and random tokens. Threads, the OS and uninstrumented I/O are out of scope.
- Replay reuses recorded outcomes. It does not show that an LLM or a service would answer the same way again.
- Injected faults are simulations and are marked as such in each event (`fault.simulated: true`).
- By default, an unexpected exception counts as `effect: unknown`, which is the conservative choice. Adapters can classify errors more precisely.
- Inferred dependencies follow data flow only. Control flow must be declared explicitly.
- A reduced trace is **1-minimal, not a global minimum**: removing any one remaining event, together with what depends on it, loses the violation.
- A reduced trace is **a trace, not an execution**. It isolates what the property needs to see and serves as a regression fixture, but the original code would not necessarily produce it, so `replay` refuses it. Reduction by re-execution, which removes injected faults and records again, belongs to the explorer (H4).

## Roadmap

| Milestone | Done when |
|---|---|
| H1 | Local portal, capture, offline replay, and a test that tells the correct implementation from the defective one ✅ |
| H2 | Stable versioned schema, a record/replay CLI, and a reduction that keeps the same violated property ✅ |
| H3 | A documented investigation of a real agent failure (CitaLab), separating original evidence from reconstructions |
| H4 | A bounded explorer of fault schedules over the boundaries, with seeded scenarios, reduced counterexamples and metrics |
| H5 | Visual comparison and differential replay against a new version of the code |

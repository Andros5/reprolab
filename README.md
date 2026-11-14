# ReproLab

Record, replay and reduce failures of agent and automation workflows, and turn them into regression tests for business properties.

**Status:** milestones H1–H5 complete. Python standard library and SQLite, no external services.

```bash
python -m examples.showcase        # runs every case live and writes showcase.html: one page, no dependencies
```

| Read | For |
|---|---|
| [Architecture](docs/architecture.md) | The pieces and how one failure flows through them |
| [Design decisions](docs/design-decisions.md) | Three choices, their alternatives and the evidence they paid off |
| [CitaLab investigation](docs/investigations/citalab-r02.md) | A real agent failure, from the logs |
| [Measured results](docs/metrics.md) | Seeded regressions, determinism, instrumentation overhead |
| [Pitch](docs/interview/pitch.md) · [demo script](docs/interview/demo-script.md) | The project in 30 seconds, 2 minutes and 3 minutes |

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

## A real failure: CitaLab N-R02

[CitaLab](https://github.com/Andros5/citalab) is a public, conversational assistant for synthetic healthcare appointments, evaluated in a master's thesis. In 9 of 12 episodes, a request to move an appointment ended with a new one, although every safety check passed. [The investigation](docs/investigations/citalab-r02.md) rebuilds those episodes as ReproLab traces, with every event citing its evidence. It keeps four levels apart: what the original logs show, what re-executing the evaluated code reproduces, what remains a hypothesis, and what is undetermined.

```bash
python -m examples.citalab_r02 --no-reexecute
```

- **Property.** A reschedule must replace its target. Checked on the traces, it agrees with CitaLab's own oracle in 12 of 12 episodes.
- **Identical requests, different answers.** Gemini's context agent received a byte-identical recorded request in 4 episodes and answered "reschedule" once and "book" three times. `reprolab diff` shows that the successful and the failed episode are identical up to that answer.
- **Re-execution.** CitaLab's evaluated code, re-executed offline against the recorded model answers, reproduces all 12 episodes: the same requests, events, replies and final agenda. A counterfactual run with the other interpretation moves the appointment instead. It is reported as a hypothesis test, with its assumptions.
- **Reduction.** Each failure reduces to its causal chain: user message → interpretation `book` → proposal → confirmation → write.

## Finding failures: the explorer

```bash
reprolab explore examples.portal_demo.scenario:reconciling --seed 0 --budget 200
```

The explorer runs a scenario under many fault schedules against the real local portal, checks the business property on every trace, and reduces what fails.

- **Faults.** Six kinds, all marked as simulated: lost response, 429, timeout (the request never arrives, which the caller cannot tell from a lost response), duplicate delivery, invalid output, and a worker crash right after a call takes effect. After a crash the code restarts with its durable state and an empty memory, and replay reproduces the crash and the restart.
- **Bounded and seeded search.** Call sites are discovered from the runs: retries and lookups only appear under faults. The order of the search:
  1. every single fault;
  2. coverage-guided pairs: a schedule that opened new sites is extended with a fault on each of them;
  3. the remaining schedules, in an order fixed by the seed.

  The same seed gives the same schedules and findings. The report always states how much of the space it covered.
- **Verdicts.** Property violation on the trace; failure only the oracle sees (real state wrong, trace clean); unhandled exception.
- **Counterexamples.** The first schedule of each finding is reduced by re-execution: faults are removed one at a time, recording again each time. Then its trace is reduced. Both runs are stored and replay offline. `explore` exits with 1 when a business property was violated, so it can gate a build.

**Seeded regressions.** Five client variants with known labels are scored with the same budget ([measured results](docs/metrics.md)):

- `blind_retry` retries anything.
- `retry_on_find_error` resubmits when the reconciling lookup fails.
- `reconciles_once` is blind on a second uncertain outcome, so it needs two faults to show.
- `reconciling` is correct within one process but forgets an uncertain submission when the worker crashes.
- `journaled` records "pending" durably before submitting and reconciles on restart, like the Swiss Job Radar's `submission_unknown`.

## Old failures as tests for new code

```bash
reprolab regress --target examples.portal_demo.scenario:journaled
reprolab html <run> --compare <new-run> --ignore-nondeterminism
```

`regress` replays every stored recording against a new version of the code:

- **Compatible.** A recording the new code still matches replays offline and gives its verdict.
- **Incompatible.** A recording it no longer matches is marked *incompatible from event #k*, with the reason. It is then recorded again under the same fault plan, against the local environment.

Each recording gets a verdict: **fixed**, **still failing**, **regressed** or **still passing**. The command exits with 1 while anything still fails, so the library of past incidents can gate a build. When it compares old and new traces, random tokens and clock readings are matched by order of appearance, so the first difference it reports is a change in behaviour, not a new random id.

`html` draws any run as a flight-recorder strip:

- solid marks are observed, diagonal hatching marks a simulated fault, and a dashed outline marks an event reconstructed from logs;
- arcs in the margin are dependencies;
- clicking an event shows its request, outcome and evidence.

It also draws two runs side by side from their first divergence, and a reduction with the dropped events faded.

## Command line

```bash
reprolab record examples.portal_demo.scenario:blind_retry_full \
    --fault portal.submit:1:lost_response --fault portal.submit:2:rate_limited
reprolab list
reprolab show <run>             # header, trace, dependencies, violations
reprolab replay <run>           # re-run the recorded code offline; exit 1 on divergence
reprolab reduce <run>           # saves a new, reduced run; the original is kept
reprolab diff <run-a> <run-b>   # first event where two runs diverge, and whether the request or only the answer differs
reprolab explore <target> --seed 0 --budget 200 [--max-faults 2] [--kinds ...] [--report out.json]
reprolab regress --target <new-target> [--from <old-target>] [--runs a,b] [--report out.json]
reprolab html <run> [--compare <run>] [--ignore-nondeterminism] [-o page.html]
reprolab export <run> -o run.json
```

Runs are stored in `./reprolab.db` (or `--db`, or `$REPROLAB_DB`). A run can be named by a unique prefix of its id. `replay --target` runs a recording against other code, for example a fixed client, and reports the first point where it diverges.

## How it works

- **Boundaries.** Code routes external interactions through a `Session`: `session.call(name, request, fn)`, `session.now()` and `session.token()`. `session.operation(id)` groups the events of one business operation.
- **Recording.** In record mode the real function runs, optionally with an injected fault. The outcome is stored as an event: the result, or the error together with what the caller can know about side effects (`effect: none | unknown`).
- **Schema.** Events and runs follow a versioned, strictly validated schema ([docs/schema.md](docs/schema.md)). A frozen v3 recording in the tests must round-trip byte for byte and still replay. Older recordings (v1 from H1, v2 from H2) are migrated on read.
- **Evidence.** A run rebuilt from another system's logs has `origin: reconstructed`, and each of its events cites its source: a file, a JSON pointer and a SHA-256. An event copied verbatim says so; an event derived by a rule states the rule.
- **Dependencies.** Each event lists the earlier events it depends on. They are inferred when a value one event produced (a token, an id, a drafted text, a timestamp) reappears in a later request, and can also be declared explicitly.
- **Replay.** In replay mode nothing external runs. Each call must match the next recorded event, or a `ReplayDivergence` explains the difference. Recorded outcomes are returned or raised again.
- **Invariants.** Invariants read only the trace, so the original run and every replay get the same verdict. The portal's real state serves as a separate oracle while recording.
- **First divergence.** `diff` compares two runs event by event. It reports where they first differ: a different call, the same call with a different request, or the same request with a different answer. The last case is the signature of non-determinism on the other side of the boundary.
- **Differential replay.** `regress` replays stored recordings against new code, says where each stops matching, and re-records the incompatible ones under the same faults.
- **Exploration.** See [the explorer](#finding-failures-the-explorer): bounded, seeded, coverage-guided schedules of injected faults, with counterexamples reduced by re-execution.
- **Reduction.** Delta debugging (ddmin) over the events of a trace. Each candidate is closed under dependencies, so an event is never kept without the events it uses. A candidate is accepted only if the same invariant is still violated **at the same event**, so the search cannot slide to a different failure. The result is saved as a new run with `origin: reduced` and its provenance.

## Measured so far

- **Portal demo, longer flow:** the trace reduces from 15 to 6 events, after 55 distinct candidates, in a few milliseconds.
- **CitaLab N-R02, 12 real episodes:**
  - the property agrees with CitaLab's oracle in 12 of 12;
  - re-execution reproduces 12 of 12;
  - the 9 failures reduce from 15–25 events to 9–17.

- **Explorer, seeded regressions** (budget 200, seeds 0–2, [details](docs/metrics.md)):
  - defects found in 21 of 21 explorations of a defective variant, with 0 false alarms in 9 explorations of a correct one;
  - with crashes in the fault set, a single `crash_after` exposes every defective variant within 6 runs;
  - without crashes, the two defects that need two faults are found after 26 and 41 runs, every seed alike, because the coverage-guided extensions come before the seeded random part;
  - each counterexample's trace reduces to 4 events;
  - about 35 runs per second, each against a fresh local portal;
  - the same seed gives identical schedules and findings.
- **Swiss Job Radar, real `send()` ([report](docs/investigations/radar-submit.md)):** 0 radar lines changed, 220 adapter lines, the radar's 366 tests still pass; no second click under any of 240 schedules of up to 2 faults per restart model, but a crash after the click leaves `sending`, which `/reconcile` refuses until the web server restarts.
- **Instrumentation:** recording a boundary call costs about 14 µs, 1.6% of a lookup to the local portal over HTTP; a stored event takes about 340 bytes in SQLite.

These numbers describe these cases only; they are not a benchmark.

## Limits (by design)

- Determinism covers only the instrumented boundaries: calls, clock and random tokens. Threads, the OS and uninstrumented I/O are out of scope.
- Replay reuses recorded outcomes. It does not show that an LLM or a service would answer the same way again.
- Injected faults are simulations and are marked as such in each event (`fault.simulated: true`).
- By default, an unexpected exception counts as `effect: unknown`, which is the conservative choice. Adapters can classify errors more precisely.
- Inferred dependencies follow data flow only. Control flow must be declared explicitly.
- A reduced trace is **1-minimal, not a global minimum**: removing any one remaining event, together with what depends on it, loses the violation.
- A reconstructed run is only as good as the logs it comes from. Derived events say which rule produced them, and `replay` refuses such runs: they are replayed by re-executing the original system's code through an adapter.
- `regress` re-applies a recording's faults by call name and occurrence. If the new code calls differently, a planned fault can land on a different step or not fire at all, so the report lists the faults planned and the faults that fired.
- `diff` compares values exactly. Provider-generated ids count as differences, so the first difference it reports can be noise and has to be read.
- A reduced trace is **a trace, not an execution**. It isolates what the property needs to see and serves as a regression fixture, but the original code would not necessarily produce it, so `replay` refuses it. The explorer's reduction of fault schedules does re-execute, so its minimal counterexamples are real runs.
- The explorer covers the schedules it reports and nothing else. A clean exploration is not a proof of correctness. Faults are injected only at instrumented boundaries, and only into scenarios that can run against a local environment; CitaLab, for example, would need real model calls.
- A crash is simulated at a boundary, after the call took effect. Crashes elsewhere, such as halfway through writing local state, are not modelled.

## Roadmap

| Milestone | Done when |
|---|---|
| H1 | Local portal, capture, offline replay, and a test that tells the correct implementation from the defective one ✅ |
| H2 | Stable versioned schema, a record/replay CLI, and a reduction that keeps the same violated property ✅ |
| H3 | A documented investigation of a real agent failure (CitaLab), separating original evidence from reconstructions ✅ |
| H4 | A bounded explorer of fault schedules over the boundaries, with seeded scenarios, reduced counterexamples and metrics ✅ |
| H5 | Visual comparison and differential replay against a new version of the code, detecting the recordings that stop being compatible ✅ |

# Investigation: the Swiss Job Radar's real submission path under injected faults

The Swiss Job Radar can submit an approved job application on a hosted form (Ashby, Greenhouse, Lever). After the final click, if it cannot confirm that the portal received the application, it records the state `submission_unknown` and refuses to send again until a person reconciles it. ReproLab's portal demo only mirrors that idea on a synthetic client. This page applies ReproLab to the radar's **own code**, without changing it, and measures what that costs.

Everything here uses synthetic data, and nothing reaches a real portal: the browser is a fake, and recording runs with the network disabled.

## Summary

- **The safeguard holds in everything tried.** The operator retries `send()` up to three times, without checking the state first. Under every single fault and every pair of faults on the click and on the confirmation, the radar clicked at most once per application, and it began at most one submission. Each later attempt was refused before any click by `begin_submission`: *"Se necesita una aprobación vigente"*. This covers the two restart models, 240 schedules each, with the space over the known call sites exhausted.
- **A crash between `begin_submission` and `receipt` leaves `sending`.** The worker dies right after the click took effect. Its restart does not change the state, and a blind re-send is refused. The application only becomes `submission_unknown` when the **web server** restarts, because that is where the recovery runs.
- **Until then it cannot be reconciled through the API.** While the web server keeps running, `/reconcile` answers 409, *"El envío no está pendiente de conciliación"*. After a web restart, it accepts "not received" and returns the application to `needs_review`. A new send is still refused until someone approves the application again. This is a liveness gap, not a safety failure: nothing is ever sent twice.
- **The recovery writes no event.** The web server's startup moves `sending` to `submission_unknown` with a bare `UPDATE`. The application's event log then shows `sending` and nothing else, although the workspace module describes its state changes as auditable.
- **The check can fail.** A deliberately defective operator, the negative control, puts the application back to `approved` with the radar's own `set_state` after an uncertain outcome. The property is violated at the second click, the radar's database records two submissions begun, and the portal holds two applications. The explorer finds it in its first run and reduces it to one fault and two events. No radar code path does this; the control only shows that the guarantee rests on the `approved` state.
- **Cost:** 220 lines of adapter code (fake page, synthetic workspace, scenarios and property; 414 lines with comments and docstrings). 0 lines changed in the radar, whose 366 tests still pass.

## What runs, and what is replaced

| Real radar code, unchanged | Replaced by the adapter |
|---|---|
| `radar.portals.inspect` and `send`: policy check, form hash, filling, document hashes, captcha check, final click, wait, receipt | The Playwright `page`: `FakePage` answers the calls `send()` makes from a synthetic Ashby-like form with two required fields (email and résumé) |
| `radar.workspace.Workspace`: `save_profile`, `upsert`, `create_application`, `save_package`, `approve`, `begin_submission`, `receipt`, `set_state` | The remote portal: `SyntheticPortal` stores what it receives and shows a confirmation text |
| The web server's startup recovery (its FastAPI lifespan, run without serving) and the `/reconcile` endpoint | The operator: it calls `send()` the way `radar-web browser <id> send` does (`portals.runner`), up to three times |

Two calls of the fake page cross a ReproLab `Session`, and only these can be faulted:

- `portal.click`, the final *Submit application* click. Its request holds the form URL, the button, the filled values (the résumé by its SHA-256, not its temporary path) and the timeout.
- `portal.confirmation`, the wait for the confirmation text. Its result is the body the page shows, which `send()` then stores as the receipt.

The rest of what `send()` reads (form fields, body text, captcha frames, invalid fields) is static synthetic content and is not instrumented. If `send()` asks for a selector the fake does not know, the adapter fails loudly instead of guessing.

**The test path is not blocked by `RADAR_PREVIEW_MODE`.** The variable is read by `send()` from the process environment. The radar's local `.env` sets it to `1`, but only the radar's entry points load `.env`, from the working directory. The adapter works inside a temporary directory, so neither the radar's `.env` nor its `profile.md` is ever read. It also pins the variable to `0` for its own scope and restores it afterwards. This mirrors the radar's own `test_real_documents_and_hosted_form`, which drives `send()` with a routed page and no preview flag. The application, its approval and the portal policy (`capability: submit`, reviewed) are created through the radar's own API, as in that test.

## The property and the oracle

> **No re-send after an uncertain outcome.** Once the final click of an application was made, the radar does not click it again unless that submission has been reconciled.

The check reads only the trace ([invariants.py](../../examples/radar_submit/invariants.py)). In the radar, reconciliation is a human act: `/reconcile` with "not received", then a new approval. A run contains no such act, so any second click on the same form is a violation. The message says whether the first click was confirmed or uncertain. It is the same idea as the portal demo's *no blind resubmit*.

The separate oracle is the radar's own database, read after recording and never replayed. It reports:

- the state;
- how many submissions the radar began (`sending` events);
- whether it has a receipt;
- and, for comparison, how many applications the synthetic portal received.

It flags three conditions: more than one submission begun, a receipt the portal never received, and an application put back to `approved` after the portal received it.

## Results

Reproduce with `python -m examples.radar_submit`. The numbers below are in [radar-submit.json](radar-submit.json).

### Single faults

Two restart models: `worker_restart`, where after a crash only the process that ran `send()` restarts, and `web_restart`, where the web server restarts too and its recovery runs. They differ only after a crash.

| Fault (simulated) | State left | Clicks | Portal holds | Later attempts |
|---|---|---|---|---|
| none | `submitted` | 1 | 1 | — |
| click: lost response | `submission_unknown` | 1 | 1 | refused |
| click: 429 | `submission_unknown` | 1 | 0 | refused |
| click: timeout | `submission_unknown` | 1 | 0 | refused |
| click: duplicate delivery | `submitted` | 1 | **2** | — |
| click: invalid output | `submitted` | 1 | 1 | — |
| click: crash after it took effect | `sending` (worker restart) / `submission_unknown` (web restart) | 1 | 1 | refused |
| confirmation: lost response, 429 or timeout | `submission_unknown` | 1 | 1 | refused |
| confirmation: duplicate | `submitted` | 1 | 1 | — |
| confirmation: invalid output (empty page) | `submission_unknown` | 1 | 1 | refused |
| confirmation: crash after it took effect | `sending` / `submission_unknown` | 1 | 1 | refused |

Every one of the 26 recordings replays offline with the same trace and result. How to read the rows:

- **Invalid output on the click** changes nothing, because a Playwright click returns nothing.
- **Invalid output on the confirmation** shows an empty page. `receipt()` refuses empty evidence (*"Se requiere un comprobante"*), and `send()` turns that into `submission_unknown`. It is conservative and correct.
- **A 429 or a timeout on the click** is treated like any other uncertain outcome, although the portal received nothing. That is conservative too. A hosted form does not answer a click with a 429; these rows only show that every error after `begin_submission` ends in `submission_unknown`.
- **Duplicate delivery** makes the portal hold two applications while the radar clicked once and recorded one. No client-side guard can see this. It would need idempotency on the portal's side. Browsers generally do not resend a form POST on their own, so this is a property of the fault model, not a radar defect. The oracle reports the count and does not flag it.

### Crash right after the click, then reconciliation

The crash happens while the web server keeps running ([`reconcile_after_crash`](../../examples/radar_submit/__main__.py)).

| Step | Result |
|---|---|
| Worker restarts; the operator tries three more times | state `sending`; all three refused; the portal holds 1 |
| `POST /reconcile` "not received" | **409**, *"El envío no está pendiente de conciliación"* |
| Web server restarts (real lifespan) | state `submission_unknown`; no event written |
| `POST /reconcile` "not received" | 200, state `needs_review`, approval cleared |
| `send()` again | refused: a new approval is needed |

A manual receipt (`/receipt`) is accepted in any state, so a person who finds the application on the portal can still record it. The gap concerns only the "not received" path, while the web server keeps running.

### Exploration

Seed 0, budget 300, at most 2 faults, all six fault kinds.

| Scenario | Schedules run | Space over the known sites | Findings |
|---|---|---|---|
| `worker_restart` | 240 | exhausted (24 single, 216 pairs) | none |
| `web_restart` | 240 | exhausted (24 single, 216 pairs) | none |
| `rearm_control` (defective on purpose) | 300 | 48 of 48 single, 252 of 1008 pairs | property violated at the 2nd click: first at run 1, 138 of 300 runs; minimal schedule: 1 fault (`portal.click:1:lost_response`); trace 3 → 2 events |

Read "exhausted" with care. The known sites include `portal.click#2` and `portal.confirmation#2`, which the explorer adds speculatively and the radar never reaches. So many pairs are single faults in effect. The distinct pairs that land are the 36 combinations of a fault on the click with a fault on the confirmation. The explorer runs about 3 schedules per second here, against about 35 for the portal demo, because each run builds a fresh radar workspace.

## Integration cost

| Measure | Value |
|---|---|
| Lines changed in the radar | **0** (`git status` of the radar repository unchanged, same commit `a7f5f6f`) |
| The radar's own test suite | 366 passed, with the adapter in place (it adds nothing to the radar's environment) |
| Adapter: fake page and synthetic workspace ([adapter.py](../../examples/radar_submit/adapter.py)) | 153 code lines (260 with docs) |
| Scenarios, operator and oracle check ([scenario.py](../../examples/radar_submit/scenario.py)) | 43 code lines (116) |
| Property ([invariants.py](../../examples/radar_submit/invariants.py)) | 24 code lines (38) |
| Measurement script ([\_\_main\_\_.py](../../examples/radar_submit/__main__.py)), tests ([test_radar_submit.py](../../tests/test_radar_submit.py)) | 149 and 120 lines, not counted as adapter |
| Changes to ReproLab's core | none |

Code lines exclude blank lines, comments and docstrings. Two adapter details were not obvious:

- The radar's startup recovery is an `async` lifespan. On Windows, an asyncio event loop opens a local socket pair, which the live environment's network guard refuses. Without the scheduler the lifespan never suspends, so the adapter steps the coroutine by hand. It raises if the lifespan ever suspends.
- The radar's environment is needed: its dependencies (FastAPI, Playwright's package and others) are imported by `radar.web` and `radar.portals`. ReproLab is added to it only through `PYTHONPATH`, and nothing is installed into it.

## Limits

- **Only two calls are boundaries.** Faults on navigation, on the form read or on uploading the file are not modelled. A crash is simulated only right after a boundary call took effect, not halfway through a database write.
- **The fake page is not a browser.** It answers what `send()` asks, from one synthetic form. It does not exercise the radar's selectors against real portal HTML. The radar's own Playwright test does that for one form.
- **The operator bypasses the UI.** The UI refuses to queue a send unless the state is `approved`, which is a second guard. The operator calls `send()` directly, as the `browser` CLI command does, so that only the guard in `send()` and `begin_submission` is tested. The browser worker's task queue is not driven.
- **One application, one portal, one process at a time.** Two workers sending concurrently are not explored here. `begin_submission` uses `BEGIN IMMEDIATE` and a conditional `UPDATE`, which this setup does not exercise.
- **A clean exploration is not a proof.** It covers the schedules listed above and nothing else.

## Reproduce

The radar must be importable, so use its own environment and put ReproLab on the path:

```bash
PYTHONPATH="src;." <swiss-job-radar>/.venv/Scripts/python -m examples.radar_submit --out radar-submit.json
PYTHONPATH="src;." <swiss-job-radar>/.venv/Scripts/python -m pytest tests/test_radar_submit.py
```

On Linux or macOS use `src:.` and `bin/python`. In ReproLab's own environment, the radar-dependent tests are skipped and the property tests on hand-written traces still run.

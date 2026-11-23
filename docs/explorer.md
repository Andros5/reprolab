# The explorer

```bash
reprolab explore examples.portal_demo.scenario:reconciling --seed 0 --budget 200
```

The explorer runs a scenario under many fault schedules against a real local environment. It checks the business property on every trace, compares the real state with the oracle, and reduces what fails.

## Search order

Call sites are discovered from the runs themselves, because retries and lookups only appear under faults. The search is bounded and seeded:

1. **Every single fault** on every known call site.
2. **Coverage-guided pairs.** A schedule that opened new call sites is extended with a fault on each of them.
3. **The remaining schedules**, in an order fixed by the seed.

The same seed gives the same schedules and the same findings. The report always says how much of the space it covered, and whether the budget ran out before the space was exhausted.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--seed` | 0 | Orders the random part of the search. |
| `--budget` | 200 | Schedules to run, not counting the baseline. |
| `--max-faults` | 2 | Faults per schedule. |
| `--kinds` | all six | Comma-separated fault kinds, such as `lost_response,timeout`. |
| `--extra-occurrences` | 1 | Occurrences beyond those seen, so that a fault can land on a call that only a retry makes. |
| `--report` | | Writes the report as JSON. |
| `--no-reduce` | | Keeps the first schedule of each finding as it is. |
| `--no-save` | | Does not store the counterexample runs. |

## Verdicts

- **property**: a business property is violated on the trace.
- **oracle-only**: the real state is wrong, but the trace is clean.
- **unhandled**: the code let an exception escape.

## Counterexamples

The explorer reduces the first schedule of each finding by re-execution: it removes the faults one at a time, records again each time, and keeps the smallest schedule that still produces the finding. It then reduces that run's trace. Both runs are stored and replay offline. `explore` exits with 1 when a business property was violated, so it can gate a build.

## Seeded regressions

Five variants of the portal client with known labels are scored with the same budget. The results are in [measured results](metrics.md).

| Variant | Defect |
|---|---|
| `blind_retry` | Retries anything. |
| `retry_on_find_error` | Resubmits when the reconciling lookup fails. |
| `reconciles_once` | Is blind on a second uncertain outcome, so it needs two faults to show. |
| `reconciling` | Is correct within one process, but forgets an uncertain submission when the worker crashes. |
| `journaled` | None known. It records "pending" durably before submitting and reconciles on restart, like the Swiss Job Radar's `submission_unknown`. |

With crashes in the fault set, a single `crash_after` exposes every defective variant within 6 runs. Without crashes, the two defects that need two faults are found after 26 and 41 runs for every seed alike, because the coverage-guided extensions come before the seeded random part.

## What it does not show

The explorer covers the schedules it reports and nothing else, so a clean exploration is not a proof of correctness. Faults are injected only at instrumented boundaries, and only into scenarios that can run against a local environment. CitaLab, for example, would need real model calls. A crash is simulated at a boundary, after the call took effect. Crashes elsewhere, such as halfway through writing local state, are not modelled.

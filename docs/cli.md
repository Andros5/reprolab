# Command-line reference

```text
reprolab [--db PATH] <command> ...
```

Runs are stored in SQLite at `./reprolab.db`, or at the path given by `--db` or `$REPROLAB_DB`. Wherever a run is expected, any unique prefix of its id works. A *target* is a `Scenario` named as `module:attribute`, and the current directory is importable, as with pytest.

## Commands

| Command | What it does | Exit code |
|---|---|---|
| `record <target> [--fault NAME:N:KIND ...] [--label TEXT]` | Runs the scenario for real, with optional injected faults, and saves the run. | 0 |
| `list` | Lists the stored runs. | 0 |
| `show <run> [--target T]` | Prints the header, trace, dependencies and violations. | 0 |
| `replay <run> [--target T]` | Re-runs the code against the recording with the network disabled. `--target` replays it against other code. | 1 on divergence |
| `reduce <run> [--invariant NAME] [--anchor SEQ] [--target T]` | Shrinks the trace while the same invariant stays violated at the same event. Saves a new run and keeps the original. | 1 if not reproduced |
| `diff <a> <b> [--ignore-nondeterminism]` | Reports the first event where two runs diverge, and how. | 0 |
| `explore <target> [options]` | Runs the scenario under many fault schedules and reduces what fails. See [the explorer](explorer.md). | 1 if a property can be violated |
| `regress --target T [options]` | Replays stored recordings against new code. See [regression](regress.md). | 1 while anything still fails |
| `html <run> [--compare RUN] [--ignore-nondeterminism] [-o FILE]` | Writes a visual HTML report. | 0 |
| `export <run> [-o FILE]` | Writes a run as a portable JSON document. | 0 |

Any command exits with 2 when the input is invalid, for example an unknown run, a bad target or a malformed fault. `replay` exits with 1 when it is asked to replay a reduced or reconstructed run, because neither is an execution of the code.

## Faults

```bash
reprolab record examples.portal_demo.scenario:blind_retry_full \
    --fault portal.submit:1:lost_response --fault portal.submit:2:rate_limited
```

The format is `name:occurrence:kind`, and `occurrence` starts at 1. The kinds are `lost_response`, `rate_limited`, `timeout`, `duplicate`, `invalid_output` and `crash_after`, described in [concepts](concepts.md#faults).

## Examples shipped with the repository

| Target | Description |
|---|---|
| `examples.quickstart:naive`, `:reconciling` | Paying an invoice. This is the [getting started](getting-started.md) example. |
| `examples.portal_demo.scenario:blind_retry`, `:reconciling` | Submitting a job application to a local portal. |
| `examples.portal_demo.scenario:blind_retry_full`, `:reconciling_full` | The same, plus reading the posting, drafting a letter with a stub LLM, and logging to telemetry. |
| `examples.portal_demo.scenario:retry_on_find_error`, `:reconciles_once`, `:journaled` | Seeded variants for the explorer. |

Runnable modules:

```bash
python -m examples.quickstart
python -m examples.portal_demo [db]
python -m examples.showcase [-o showcase.html]
python -m examples.citalab_r02 [--no-reexecute] [--db PATH]
python -m examples.portal_demo.metrics          # regenerates docs/metrics.md
```

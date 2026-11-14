# Event schema v2

A recording is a run header plus an ordered list of events. This page is the contract;
`src/reprolab/events.py` and `src/reprolab/store.py` enforce it. Parsing is strict:
missing fields, unknown fields and out-of-range values are errors.

`tests/fixtures/blind_retry_full.v2.json` is a frozen v2 recording. The tests require it
to round-trip byte for byte, to replay offline with the current code, and to reduce to the
same events. A change that breaks any of these is a schema change and needs a new version.

## Event

| Field | Type | Meaning |
|---|---|---|
| `seq` | int ≥ 1 | Position in the original run. Stable: a reduction keeps the original numbers. |
| `type` | `call` \| `clock` \| `random` | A boundary call, a clock reading, or a random token. |
| `name` | non-empty string | Boundary name, e.g. `portal.submit`; `now` and `token` for clock and random. |
| `kind` | `http` \| `llm` \| `tool`, or `""` | Kind of call; empty for clock and random. |
| `request` | JSON value, or `null` | What the code sent. Always `null` for clock and random. |
| `outcome` | `{"ok": value}` \| `{"error": {type, message, effect}}` | What the code observed. Only calls can fail. |
| `fault` | `null` \| `{"kind": ..., "simulated": true}` | Fault injected by ReproLab on this call. `simulated` is always `true`: a reader never mistakes an injected fault for a real incident. Kinds: `lost_response`, `rate_limited`. |
| `deps` | sorted list of earlier `seq` | Events this one depends on. |
| `op` | string \| `null` | Business operation the event belongs to (`session.operation(...)`). |

`effect` says what the caller can know about side effects: `none` (rejected before acting) or
`unknown` (may have taken effect). An unexpected exception counts as `unknown`.

### Dependencies

`deps` is filled in two ways:

- **Inferred by value.** If a request contains a distinctive value that an earlier event
  produced, the request depends on that event. Distinctive means a string of 8 or more
  characters, or a non-integral float (a clock reading). Small integers and short strings
  never link, to avoid false dependencies. When several events produced the same value,
  the first one counts as its origin.
- **Declared explicitly** with `session.call(..., deps=[seq])`, using `session.last_seq`.

Inference sees data flow only. Control flow ("B ran because A failed") does not show up in
values, so it must be declared explicitly when a reduction has to respect it.

## Run header

| Field | Meaning |
|---|---|
| `id`, `created_at`, `label` | Identity and a human label. |
| `origin` | `recorded` (an execution captured by a `Session`) or `reduced` (a subset of another run's events). H3 will add `reconstructed`. |
| `target` | `module:attribute` of the scenario, so `replay` knows which code to run again. |
| `faults` | Injection plan: `[{name, occurrence, kind}]`. |
| `reduced_from` | For reduced runs only: `{run, invariant, anchor, kept, original_events, tests, seconds}`. |
| `extra` | Free-form object for user metadata. |

Trace rules: `seq` increases. A recorded run is contiguous (`1..n`). Every dependency must
be present in the trace, including in a reduced one.

## Storage and portability

- SQLite: table `runs(id, created_at, label, schema_version, meta)` and
  `events(run_id, seq, body)`, one JSON body per event. Runs are append-only; a reduction
  saves a new run.
- JSON document (`reprolab export`):
  `{"schema_version": 2, "run": {...header...}, "events": [...]}`, keys sorted, two-space indent.

## Versions

- **v1** (H1): no `deps` or `op`, and `fault` was a plain string. v1 runs in SQLite are
  migrated on read: the fault becomes `{kind, simulated: true}`, `deps` are inferred by
  value, and unknown metadata moves to `extra`. The file on disk is not rewritten.
- **v2** (H2): this page.
- A version this ReproLab does not know is refused with `UnsupportedSchema`, never guessed.

# Concepts

## Boundaries and the session

Code routes its external interactions through a `Session`:

- `session.call(name, request, fn)` crosses a boundary such as HTTP, an LLM or a tool.
- `session.now()` reads the clock.
- `session.token()` draws a random identifier.

`session.operation(id)` groups the events of one business operation. Everything inside the process is assumed deterministic; everything outside it is recorded.

## Recording

In record mode the real function runs, optionally with an injected fault. The outcome is stored as an event: either the result, or the error together with what the caller can know about side effects (`effect: none | unknown`). By default an unexpected exception counts as `effect: unknown`, which is the conservative choice. Adapters can classify errors more precisely with `Session(classify=...)`.

## Faults

| Kind | What happens | Effect seen by the caller |
|---|---|---|
| `lost_response` | The call runs and takes effect; the response is lost. | `unknown` |
| `rate_limited` | HTTP 429 before anything happens. | `none` |
| `timeout` | The request never arrives, which the caller cannot tell from a lost response. | `unknown` |
| `duplicate` | The request is delivered twice; both deliveries take effect. | the first answer |
| `invalid_output` | The answer arrives malformed. | a malformed value |
| `crash_after` | The call takes effect, then the worker dies. It restarts with its durable state and an empty memory. | the restart |

A fault is addressed as `name:occurrence:kind`, for example `portal.submit:2:rate_limited`. Every injected fault is stored with `simulated: true`.

## Schema and evidence

Events and runs follow a versioned, strictly validated schema ([schema v3](schema.md)). A frozen v3 recording in the tests must round-trip byte for byte and still replay. Older recordings (v1 and v2) are migrated on read.

A run rebuilt from another system's logs has `origin: reconstructed`, and each of its events cites its source with a file, a JSON pointer and a SHA-256. An event copied verbatim says so, and an event derived by a rule states the rule. Runs have one of three origins: `recorded`, `reduced` or `reconstructed`.

## Dependencies

Each event lists the earlier events it depends on. They are inferred when a value that one event produced reappears in a later request: a token, an id, a drafted text or a timestamp. They can also be declared explicitly with `session.call(..., deps=[seq])`. Inferred dependencies follow data flow only, so control flow must be declared.

## Replay

In replay mode nothing external runs, and any socket connection raises an error. Each call must match the next recorded event, or a `ReplayDivergence` explains the difference. Recorded outcomes are returned or raised again, and a recorded crash is raised again too. Replay shows that *your code* behaves the same given the same answers. It does not show that the outside world would answer the same way again.

## Invariants and the oracle

Invariants read only the trace, so the original run and every replay get the same verdict. The real state of the environment (the *oracle*) is read separately while recording, and it is never replayed. The explorer reports three kinds of finding:

- **property**: a business property is violated on the trace;
- **oracle-only**: the real state is wrong but the trace looks clean;
- **unhandled**: the code raised an exception it did not handle.

## First divergence

`diff` compares two runs event by event and reports where they first differ:

- a **different call**;
- the **same call with a different request**;
- the **same request with a different answer**, which is the signature of non-determinism on the other side of the boundary.

With `--ignore-nondeterminism`, random tokens and clock readings are matched by order of appearance, so a fresh random id does not count as a difference.

## Reduction

Delta debugging (ddmin) runs over the events of a trace. Each candidate is closed under dependencies, so an event is never kept without the events it uses. A candidate is accepted only if the same invariant is still violated **at the same event**, so the search cannot slide to a different failure. The result is saved as a new run with `origin: reduced` and its provenance.

The result is **1-minimal, not a global minimum**: removing any one remaining event, together with what depends on it, loses the violation. A reduced trace is a regression fixture, not an execution, so `replay` refuses it. The explorer's reduction of fault *schedules* does re-execute, so its minimal counterexamples are real runs.

# Roadmap

## Done in 1.0.0

| Milestone | Done when |
|---|---|
| H1 | A local portal, capture, offline replay, and a test that tells the correct implementation from the defective one. |
| H2 | A stable versioned schema, a record and replay CLI, and a reduction that keeps the same property violated. |
| H3 | A documented investigation of a real agent failure (CitaLab) that separates the original evidence from reconstructions. |
| H4 | A bounded explorer of fault schedules over the boundaries, with seeded scenarios, reduced counterexamples and metrics. |
| H5 | Visual comparison, and differential replay against a new version of the code that detects the recordings that stop being compatible. |

## Since 1.0.0

- An investigation of the Swiss Job Radar's real submission path, using an adapter and no changes to the radar ([report](investigations/radar-submit.md)).
- A one-file quickstart example and these guides.

## Ideas, not commitments

Each idea keeps the project's constraints: the standard library only, local runs only, and limits stated next to the claims.

- **Adapters for common clients.** Thin wrappers so that `requests`, `httpx` or an LLM SDK cross a session boundary without hand-written calls. These would be optional extras, and the core would stay dependency-free.
- **A pytest plugin**, so that stored counterexamples run as ordinary test items.
- **Crashes between boundaries.** Model a crash while local state is half written, for workers that keep their own journal.
- **Control-flow dependencies.** Infer them from `session.operation` scopes, not only from data flow.
- **An id-aware diff**, to tell provider-generated ids from real differences.

Proposals are welcome as issues. Please read [CONTRIBUTING.md](../CONTRIBUTING.md) first.

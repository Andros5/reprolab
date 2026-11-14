# Three design decisions

Each one had a credible alternative. These are the choices, what they cost, and the evidence in this repository that they paid off.

## 1. Record at explicit boundaries, not the whole process

**Decision.** Code routes calls, the clock and randomness through a `Session`. Only those boundaries are recorded and replayed.

**Alternatives considered.**
- **Record and replay the whole process** (rr-style, or a deterministic runtime). Complete in principle, but tied to an OS or a runtime, heavy, and opaque: a reader cannot see what was captured.
- **Record at the HTTP layer** (VCR-style cassettes). Easy to adopt, but blind to LLM SDKs, local tools, clocks and random ids, and it records transport details instead of meaning.
- **Durable-execution frameworks** (event-sourced workflows). Strong guarantees, but they require writing the system in their model. ReproLab has to fit systems that already exist.

**Cost.** Determinism covers only what goes through the boundaries. CitaLab showed exactly this: one random value (the proposal id) was drawn outside them, and the re-execution adapter had to serve it from the recording explicitly.

**Why it paid off.** Every recorded fact is visible and typed: what was requested, what came back, and what the caller could know about side effects (`effect: none | unknown`). That one field is what lets a property tell a safe retry from a blind one.

## 2. Properties read the trace; the real state is a separate oracle

**Decision.** Invariants are functions of the event list only. The real state (the portal's database, CitaLab's agenda) is read separately, while recording, and never replayed.

**Alternatives considered.**
- **Check the final state only.** Simple, but a replay has no real state to check. A reduction could not tell whether it still shows the same failure, and the verdict would not say *when* the property broke.
- **Mix both in one check.** Convenient, but then a disagreement between the trace and reality is invisible.

**Cost.** Some failures cannot be seen in the trace.

**Why it paid off.**
- Replays and reductions keep the original verdict, anchored to an event.
- Keeping the two apart surfaces a third category. Under `duplicate` delivery the explorer reports an **oracle-only** finding: the portal holds two applications although no client step was wrong. That is a server-side idempotency problem, which no client fix can solve.
- In CitaLab, the trace property and CitaLab's own oracle agree on 12 of 12 episodes. Two independent checks agreeing is evidence, not just one check repeated.

## 3. Two reductions, each honest about what it is

**Decision.**
- **Trace reduction:** ddmin over recorded events, closed under dependencies and anchored to the same violation. It never re-executes.
- **Schedule reduction:** inside the explorer, faults are removed one at a time and the code is **re-executed** each time.

**Alternatives considered.**
- **Only input or schedule shrinking** (classic delta debugging, Hypothesis-style). It yields real executions, but needs a runnable system. CitaLab's episodes cannot be re-run without paid model calls, and the evidence is the logs.
- **Only trace reduction.** It works on any evidence, but its result is a trace, not an execution, and could be mistaken for one.

**Cost.** Two mechanisms, and labels that must stay honest. A reduced run is stored with `origin: reduced` and its provenance, and `replay` refuses it.

**Why it paid off.**
- **Trace reduction** turned CitaLab's 16-event failure into the 9-event causal chain `book` → proposal → confirmation → write, without one model call.
- **Schedule reduction** drops faults that do not matter: a lost response plus an irrelevant 429 shrinks to the lost response alone (`tests/test_explore.py`). Its minimal counterexample is a real run that replays offline.

---

A fourth choice runs through all three: **provenance per event**. Imported events cite a file, a JSON pointer and a SHA-256. Derived events state the rule that produced them, and simulated faults say they are simulated. In an investigation, that is what separates a demonstrated cause from a plausible story.

# Limits

ReproLab makes narrow claims and states where they stop. Each limit below is deliberate.

## Replay and determinism

- **Determinism covers only the instrumented boundaries**: calls, the clock and random tokens. Threads, the OS and uninstrumented I/O are out of scope.
- **Replay reuses recorded outcomes.** It shows that the code behaves the same given the same answers. It does not show that an LLM or a service would answer the same way again.
- By default, an unexpected exception counts as `effect: unknown`, which is the conservative choice. Adapters can classify errors more precisely.

## Faults and exploration

- **Injected faults are simulations**, and each event marks them as such (`fault.simulated: true`).
- **A crash is simulated at a boundary, after the call took effect.** Crashes elsewhere, such as halfway through writing local state, are not modelled.
- **The explorer covers the schedules it reports and nothing else.** A clean exploration is not a proof of correctness.
- Faults are injected only at instrumented boundaries, and only into scenarios that can run against a local environment. CitaLab, for example, would need real model calls.

## Reduction

- A reduced trace is **1-minimal, not a global minimum**: removing any one remaining event, together with what depends on it, loses the violation.
- A reduced trace is **a trace, not an execution**. It isolates what the property needs to see and serves as a regression fixture, but the original code would not necessarily produce it, so `replay` refuses it. The explorer's reduction of fault schedules does re-execute, so its minimal counterexamples are real runs.
- **Inferred dependencies follow data flow only.** Control flow must be declared explicitly.

## Evidence and comparison

- **A reconstructed run is only as good as the logs it comes from.** Derived events say which rule produced them, and `replay` refuses such runs. They are replayed by re-executing the original system's code through an adapter.
- `diff` compares values exactly. Provider-generated ids count as differences, so the first difference it reports can be noise and has to be read. `--ignore-nondeterminism` covers only the session's own tokens and clock readings.
- `regress` re-applies a recording's faults by call name and occurrence. If the new code calls differently, a planned fault can land on a different step or not fire at all. The report lists both the faults planned and the faults that fired.

## Measurements

The numbers in this repository describe these cases on one machine. They are not a benchmark.

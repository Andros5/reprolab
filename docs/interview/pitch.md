# How to explain ReproLab

## In 30 seconds

> Agents and automations fail in the gaps: a response that never arrives, a retry that duplicates an order, a model that answers the same question two ways. ReproLab records what a workflow did at its boundaries and replays it offline. It injects the faults production will eventually deliver and checks business properties on the trace. Every failure it finds is shrunk to the few events that explain it. I used it to investigate a real failure in my own agent project, keeping what the logs prove apart from what is only a hypothesis.

## In two minutes

1. **The problem.** In stateful workflows the bugs that cost money are not in the happy path. They come from partial failures: the submission went through but the confirmation was lost, the worker crashed after the write, the tool returned garbage. They are hard to reproduce and easy to misattribute.
2. **The mechanism.** Code routes calls, the clock and randomness through a `Session`. In record mode the real call runs, optionally with a simulated fault; in replay mode nothing external runs and the recorded answer comes back. Properties such as "never resubmit while the outcome is uncertain" read only the trace, so a replay gets the same verdict as the original run.
3. **Finding failures.** The explorer runs a scenario under bounded, seeded fault schedules. A crash right after a submission breaks a client that keeps the property under every fault that leaves the process alive. The explorer reports it with a minimal fault schedule and a 4-event trace.
4. **A real case.** In CitaLab, 9 of 12 attempts to move an appointment created a second one. I rebuilt the episodes from the logs, with every event citing its source. The model's context agent had received a byte-identical request four times and answered "book" three times and "reschedule" once. Re-executing the evaluated code offline reproduced all 12 episodes exactly, so the deterministic core did what the model told it to.
5. **The limits I state.** Replay reuses recorded answers. It does not show that a model would answer the same again. A clean exploration is not a proof of correctness.

## Questions I expect

**"Tell me about a time an agent was wrong. How did you detect it?"**

- **Situation.** My thesis assistant passed every safety check, yet 9 of 12 reschedule requests ended with an extra appointment.
- **Task.** Find out where it went wrong without overclaiming.
- **Action.**
  - I wrote the business property ("a reschedule replaces its target") and checked it on traces rebuilt from the logs. It agreed with the evaluation's oracle on 12 of 12 episodes.
  - A first-divergence diff showed that a successful and a failed episode were identical until one model answer. The request was the same; the answer was not.
  - Re-executing the evaluated code against the recorded answers reproduced every episode.
- **Result.**
  - The cause is located in the model's interpretation, not in the code.
  - The thesis's "success with architecture M5" turned out to be variance on an identical input.
  - Why the model chooses "book" stays undetermined, and I say so.

**"How is this different from VCR or mocking?"**

Cassettes replay HTTP. ReproLab records meaning at every boundary, including the clock, random ids and LLM calls. It records what the caller could know about side effects, and it checks properties on the trace. It also explores faults and shrinks counterexamples, which a cassette library does not try to do.

**"How do you know the explorer is any good?"**

I seeded five client variants with known labels. With the same budget it found the defect in 21 of 21 explorations of a defective variant, and raised no false alarm in 9 explorations of a correct one. Without crashes in the fault set, the two defects that need two faults are found after 26 and 41 runs, because pairs that extend a schedule onto newly reached call sites come first. The numbers are in `docs/metrics.md`, with the script that regenerates them.

**"What would you do next?"**

- An adapter for a real SDK boundary, such as an LLM client or a queue.
- Exploring CitaLab with recorded model answers as a stub. The interesting faults there are tool errors and timeouts between the proposal and the confirmation.
- Using `regress` as a CI gate over a library of recorded incidents.

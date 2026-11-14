# Investigation: a reschedule request that created a new appointment (CitaLab N-R02)

CitaLab is a conversational assistant for synthetic healthcare appointments, evaluated in a master's thesis over 276 episodes. In 9 of them, a request to move an appointment ended with a second appointment instead. Every safety check passed. This page reports what ReproLab can establish about those 9 episodes, and keeps four levels apart: what the original evidence shows, what re-executing the evaluated code reproduces, what remains a hypothesis, and what is undetermined.

Run it all with one command (section [Reproduce](#reproduce)):

```bash
python -m examples.citalab_r02
```

## Summary

- **The failure is a property violation, not a safety breach.** In 9 of the 12 episodes of units N-R02 and N-CF-R02, the person confirmed a proposal and the system completed a `book` while the request was to move appointment `ind-apt-f`. On the reconstructed traces, the property *reschedule-replaces-target* matches CitaLab's own goal check in 12 of 12 episodes.
- **The first deviation is the model's interpretation.** In M5 and H, it is the context agent's first answer (`intent: book`). In S1, it is the model's choice of `propose_booking` on its third call.
- **The same request got two answers.** For Gemini, the context agent received a byte-identical recorded request in 4 episodes (same prompt hash, input, schema and model; temperature 0 in the campaign manifest). It answered `reschedule` once and `book` three times. The only M5/H success with Gemini is therefore not explained by the architecture: H received exactly the same request and answered differently.
- **The evaluated code reproduces every episode.** Re-executed offline against the recorded model answers, CitaLab's code produces the same model requests, events, replies and final agenda in 12 of 12 episodes. Given those answers, the deterministic core did exactly what the logs say.
- **Counterfactual.** Given the interpretation Gemini produced in M5, CitaLab's H code moves the appointment and creates nothing. This is a hypothesis test under the assumptions listed below, not evidence.

## The property

> A reschedule replaces its target. While the person is moving appointment T, the only write that may complete is the move of T.

The check reads only the trace ([invariants.py](../../examples/citalab_r02/invariants.py)). T is `ind-apt-f` for both units: it comes from `scenario.expect` in the corpus, not from anything the assistant saw. CitaLab's goal check (`checks.goal`, which compares the agenda before and after) serves as an independent oracle.

| Model | Architecture | N-R02 | N-CF-R02 | First interpretation |
|---|---|---|---|---|
| GPT-OSS 20B (Groq) | M5 | violated | violated | context: `book` (both) |
| GPT-OSS 20B (Groq) | S1 | violated | violated | proposes `book` (both) |
| GPT-OSS 20B (Groq) | H | violated | violated | context: `book` (both) |
| Gemini 3.5 Flash-Lite | M5 | holds | violated | context: `reschedule` / `book` |
| Gemini 3.5 Flash-Lite | S1 | holds | holds | proposes `reschedule` (both) |
| Gemini 3.5 Flash-Lite | H | violated | violated | context: `book` (both) |

Agreement with CitaLab's oracle: 12/12.

## Evidence and reconstruction

**Original evidence.** The original evidence is copied verbatim from CitaLab's public campaign `final-independent-v1` into [examples/citalab_r02/data](../../examples/citalab_r02/data):

- the 12 result lines;
- the 12 trace files they reference;
- CitaLab's repeated model calls about N-R02 (experiment B);
- the campaign manifest;
- the frozen corpus.

[sources.json](../../examples/citalab_r02/data/sources.json) records the origin path, the line number and the SHA-256 of each item. Loading fails if a single byte differs. The copy also checks that the 30 source files of the CitaLab checkout match the evaluated code hashes in the manifest, and they do.

**Reconstructed runs.** Each episode becomes a ReproLab run with `origin: reconstructed` ([importer.py](../../examples/citalab_r02/importer.py)). Every event cites its evidence as a file, a JSON pointer and a SHA-256, and the tests resolve every pointer.

- **Verbatim events** (138 of 226) copy their values unchanged from the cited object.
- **Derived events** (88, all of them model calls) carry a rule that states what was inferred:
  - **Joining.** A model call's request comes from the trace file and its parsed output from the turn's event log. The two are joined by their order within the turn, and the importer checks that agents and counts line up.
  - **Position.** Calls that only write the reply text have no entry in the event log. They are placed after the turn's actions.
  - **S1 order.** S1 logs the model's tool request after running the tool, so that call is placed before the tool it requested.
- **Dependencies** are inferred by value, plus declared rules. The declared rules over-approximate on purpose, so that a reduction never drops a possible cause: everything in a turn depends on that turn's user message; actions depend on every model call before them in the turn; a write depends on its proposal and on the confirmation.
- **Not imported:** the user simulator's own model calls. Their result is the user turn, which is imported.

## Level 1: what the original evidence shows

1. **The write.** All 9 failures end with a completed write `operation: book` (`apt-0004`), confirmed with the button and allowed by the policy check (`CMP-CONFIRM-01`). The 3 successes end with `operation: reschedule` of `ind-apt-f`.
2. **The first deviation.**
   - In M5 and H, it is the context agent's first answer: `intent: book`, `appointment_id: null`. The successful Gemini M5 episode answered `intent: reschedule`, `appointment_id: ind-apt-f`. Its first-divergence comparison with Gemini H finds the two traces identical up to that call, and the two answers differ only in those two fields.
   - In S1, the model chooses `propose_booking` (Groq, both episodes) or `propose_reschedule` (Gemini, both episodes) on its third call, after reading the preferences and the slots.
3. **Identical requests, different answers.** The first context call of each episode, grouped by its recorded request:

   | Model | Identical requests | Answers |
   |---|---|---|
   | Gemini 3.5 Flash-Lite | 4 (M5 and H, N-R02 and N-CF-R02) | `reschedule` ×1, `book` ×3 |
   | GPT-OSS 20B | 4 | `book` ×4 |

   CitaLab's experiment B repeated the same call 5 times per model with the evaluated prompt: `book` ×5 for both models. With a prompt that adds an instruction for this case, Gemini answered `reschedule` ×5 and GPT-OSS `reschedule` ×1 and `book` ×4.
4. **What this changes.** The thesis reports that the operation succeeded with Gemini in M5 and in S1. For M5 that success is not attributable to the architecture: the H context agent received the same request and answered `book`. Over the 9 known calls on this first message (4 in the campaign with byte-identical requests, plus the 5 repetitions of experiment B), Gemini answered `reschedule` once.

**Limit.** Only recorded fields can be compared. The HTTP body was not logged, so the temperature comes from the campaign manifest (0.0), not from each request. Provider-side differences cannot be ruled out.

## Level 2: what re-executing the evaluated code reproduces

[reexecute.py](../../examples/citalab_r02/reexecute.py) runs CitaLab's own `Assistant` over each episode, offline:

- **Model calls.** The real `ChatClient` builds every request, and only its network method is replaced. That method crosses a ReproLab `Session` in replay mode, which checks each request against the recorded one and returns the recorded answer.
- **Proposal ids.** CitaLab's one uninstrumented random value, the proposal id, is served from the recording through a second replay session.
- **The person's turns** come from the evidence.

Results:

- **12/12 episodes reproduced:**
  - every model call, with an identical request, in the same order, and no extra or missing call;
  - the same event log, reply and status in every turn;
  - the same final agenda.

  Given the recorded answers, there is no hidden path in the code: the core executed what the model interpreted.
- **The check is sensitive.** Changing the first answer of a failed episode to `reschedule` makes the re-execution diverge at the next context call, with a different request.
- **Turn 1 looks the same either way.** In H, the reply to the first message (the list of slots) is built from an identical request whether the interpretation is `book` or `reschedule`. The person sees the same options and has no signal yet that a new booking, rather than a move, is being prepared.

### Counterfactual: Gemini H with M5's interpretation

This is a hypothesis test, not evidence. Gemini H on N-R02 is re-executed with two answers substituted:

1. **Call 1** (context, turn 1) gets the answer Gemini gave in M5 to the byte-identical request: a recorded answer of the same model to the same input.
2. **Call 3** (context, turn 2) gets M5's turn-2 answer, which was given to a similar but different request (the person worded the choice differently). This is an assumption, not a recorded answer to this request.

The run also assumes:

- The person's turns are the recorded ones. Turn 1's reply is unchanged, as shown above, but the person might have answered turn 2's proposal differently.
- Calls with no recorded answer fail, so CitaLab writes its deterministic fallback text.

**Result:** the evaluated H code proposes a change, the confirmation moves `ind-apt-f`, and nothing is created. The turn statuses are the same as recorded. The deterministic core handles the reschedule correctly once it receives that interpretation.

## Level 3: hypotheses

- **The request is ambiguous.** It reads "¿Puedes buscarme otra hora para medicina de familia…?" (can you find me another time for general practice…?) and never says to move the existing appointment, although the input lists it. The model then resolves the ambiguity towards a new booking. Supporting evidence:
  - an instruction for this case flips Gemini to `reschedule` in 5 of 5 repetitions;
  - with GPT-OSS the same instruction works in 1 of 5;
  - Gemini S1, whose prompt and input differ, chose the reschedule in both episodes.

  This is consistent with ambiguity but does not isolate it as the cause.

## Level 4: undetermined

- Why the model chooses `book` over `reschedule` for this input.
- Why Gemini gave different answers to identical recorded requests at temperature 0. Possible explanations are server-side non-determinism or a parameter that was not logged, but neither can be checked from this evidence.

## Reductions

Each failure reduces to the events the violated property needs, keeping the same invariant violated at the same write. In H the result is 16 → 9 events:

```
user.message > llm.context (book) > user.message > llm.context > tool.propose_booking
  > core.proposal > user.confirm > tool.confirm > core.write (book)
```

The other architectures:

- **S1:** 15 → 9 events.
- **M5:** 25 → 17 events, or 16 for Gemini N-CF-R02. The reduction keeps M5's intermediate agents because the declared dependencies over-approximate.

## Reproduce

```bash
python -m examples.citalab_r02 --no-reexecute     # levels 1 and 3, no CitaLab needed
python -m reprolab --db <db> diff <run-a> <run-b>  # first divergence between two episodes
```

Re-execution needs CitaLab's dependencies in a separate environment (Python 3.13, about 80 MB):

```bash
python -m venv .venv-citalab
.venv-citalab/Scripts/python -m pip install -r ../citalab/requirements.txt
.venv-citalab/Scripts/python -m pip install --no-deps -e ../citalab -e .
.venv-citalab/Scripts/python -m examples.citalab_r02
```

To copy the evidence again from a CitaLab checkout: `python -m examples.citalab_r02.vendor --citalab ../citalab`.

## Limits of this investigation

- 12 episodes of one unit. The finding about identical requests concerns this input and these two models only.
- **Re-execution** reuses the recorded answers. It shows what the code does with them, not what a model would answer today.
- **First-divergence comparison** compares values exactly, so provider-generated ids (for example tool-call ids in S1) count as differences. The first difference it reports can therefore be noise, and has to be read.
- The **reconstructed order** of model calls within a turn follows the stated rules. Re-execution confirms it, because the calls are consumed in the trace file's real order with identical requests.

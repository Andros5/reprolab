# Demo video script (about 3 minutes)

A finished, 101-second motion version with no voice-over is attached to the [v1.0.0 release](https://github.com/Andros5/reprolab/releases/tag/v1.0.0). Its source is in [video/](../../video/). The script below is for a live, narrated demo, for example in an interview.

Record the terminal on one half of the screen and the generated page on the other. Commands assume the repository root with the virtual environment active. Every result shown is computed live; nothing is staged.

| Time | Screen | Say |
|---|---|---|
| 0:00 | `python -m examples.portal_demo` | "A client submits a job application. I make the portal lose its response. The client retries, and the portal now holds two applications. The property 'no blind resubmit' flags event 4 on the trace." |
| 0:30 | same output, the replay section | "I replay the saved run with the network disabled. Same trace, same result, same violation. Replay reuses recorded answers; it doesn't promise a service would answer the same way twice." |
| 0:50 | `reprolab explore examples.portal_demo.scenario:reconciling --budget 200` | "This client reconciles before retrying, and keeps the property under every fault that leaves the process alive. The explorer tries schedules of simulated faults with a fixed seed. One crash right after the submission is enough: the restarted worker forgot the uncertain submission. Minimal schedule: one fault. Trace: four events." |
| 1:30 | `reprolab regress --target examples.portal_demo.scenario:journaled` | "The fix writes 'pending' before submitting and reconciles on restart. The counterexamples the explorer stored become regression tests. A recording that still matches the new code replays offline; one that doesn't says at which event it stops matching and is re-recorded under the same faults. The crash counterexample: fixed." |
| 2:00 | `python -m examples.showcase`, open `showcase.html`, scroll to *A real agent failure* | "This is a real failure from my agent project. Nine of twelve reschedule requests created a new appointment. These traces are rebuilt from the logs. Every event cites a file, a JSON pointer and a hash, and dashed events say how they were derived. Two episodes are identical until the model receives the same request and answers differently." |
| 2:35 | scroll to the reduction under it | "Reduced to its causal chain: interpretation 'book', proposal, confirmation, write. And re-executing the evaluated code against the recorded answers reproduces all twelve episodes, so the deterministic core did what the model told it." |
| 2:55 | `docs/metrics.md` | "21 of 21 seeded defects found, no false alarms, deterministic per seed. Standard library and SQLite, nothing else." |

**Before recording:** delete `reprolab.db` so `list` and `regress` start clean, run each command once to warm the disk cache, and use a terminal width of about 110 columns.

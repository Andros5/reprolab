# Getting started

This guide takes you from installing ReproLab to a failure that you have recorded, replayed, reduced and kept as a regression test. It uses [`examples/quickstart.py`](../examples/quickstart.py), which is about 130 lines and runs without a network.

## 1. Install

ReproLab needs Python 3.11 or newer and has no runtime dependencies.

```bash
git clone https://github.com/Andros5/reprolab.git
cd reprolab
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"      # Windows
.venv/bin/python -m pip install -e ".[dev]"          # Linux and macOS
```

The `reprolab` command is now available inside the virtual environment. Runs are stored in `./reprolab.db`, or in the path given by `--db` or `$REPROLAB_DB`.

## 2. Route the boundaries through a session

A *boundary* is anything that leaves your process: an HTTP request, an LLM call, a tool, the clock, a random id. Pass each one through the session:

```python
def pay_naive(session, bank):
    for _ in range(3):
        try:
            return session.call("bank.charge", INVOICE, bank.charge)
        except BoundaryError:
            continue
    return {"state": "gave up"}
```

`session.call(name, request, fn)` runs `fn(request)` when recording and returns the recorded outcome when replaying. If the call fails, or a fault is injected, it raises a `BoundaryError` whose `effect` tells the caller what it can know:

| `effect` | Meaning | Example |
|---|---|---|
| `none` | The request certainly had no effect. | HTTP 429 |
| `unknown` | The request may or may not have taken effect. | lost response, timeout, a crash after the call |

Use `session.now()` for the clock and `session.token()` for random identifiers, so that replay can reproduce them too.

## 3. State the business property on the trace

An invariant is a function from the recorded events to a list of violations. It must read only the trace, so that a replay gets the same verdict as the original run:

```python
def charge_at_most_once(events):
    uncertain_or_done, violations = None, []
    for e in events:
        if e.name == "bank.charge":
            if uncertain_or_done is not None:
                violations.append(Violation("charge-at-most-once", e.seq, "charges again without checking"))
            if e.ok or (e.error or {}).get("effect") == "unknown":
                uncertain_or_done = e.seq
        elif e.name == "bank.find" and e.ok and e.outcome["ok"].get("charges") == []:
            uncertain_or_done = None
    return violations
```

Write invariants defensively. Under the `invalid_output` fault, an answer can be malformed, and the invariant must still return a verdict instead of raising an exception.

## 4. Wrap it in a scenario

```python
@contextmanager
def live():
    yield Bank()                       # a real or local service, for recording

naive = Scenario(
    name="naive", run=pay_naive, invariants=(charge_at_most_once,),
    live=live,                         # context manager: the real environment
    offline=Unreachable,               # environment for replay; touching it is a bug
    oracle=lambda bank: {"charges": len(bank.charges)},       # optional: the real state
    oracle_check=lambda r: "charged twice" if r["charges"] > 1 else None,
)
```

The **oracle** is separate evidence. It reads the real state after a recording and is never replayed. Some failures show up only there, such as a duplicate delivery that leaves no trace on the client side.

## 5. Record, replay and reduce

```bash
reprolab record examples.quickstart:naive --fault bank.charge:1:lost_response
reprolab list
reprolab show <run>          # trace, dependencies and violations
reprolab replay <run>        # runs offline; prints DIVERGED and exits 1 if the code no longer matches
reprolab reduce <run>        # saves a new reduced run; the original is kept
reprolab html <run>          # writes reprolab-<run>.html
```

A run can be named by any unique prefix of its id.

## 6. Explore

```bash
reprolab explore examples.quickstart:reconciling --seed 0 --budget 50
```

The explorer discovers the call sites, tries every single fault, then pairs on the paths those faults opened, then a seeded sample. It reduces each finding by re-execution. It exits with 1 when a business property can be violated, so it can gate a build. On this example it finds a crash-after-charge double charge, an unhandled malformed lookup, and a duplicate delivery that only the oracle sees. The [explorer guide](explorer.md) has the details.

## 7. Keep failures as regression tests

When you have fixed the code, replay every stored failure against the new version:

```bash
reprolab regress --target my_module:pay_fixed
```

Each recording gets a verdict: **fixed**, **still failing**, **regressed** or **still passing**. The command exits with 1 while anything still fails. See [regression and reports](regress.md).

## Next

- [Concepts](concepts.md): what is recorded, dependencies, evidence, and divergence.
- [CLI reference](cli.md): every command, option and exit code.
- [Limits](limits.md): what ReproLab does not claim.

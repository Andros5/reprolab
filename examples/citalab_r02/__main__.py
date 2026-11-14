"""The N-R02 investigation in one command:  python -m examples.citalab_r02 [--db PATH]

1. Load the vendored CitaLab evidence and check every byte against its SHA-256.
2. Rebuild the 12 episodes as reconstructed ReproLab runs and store them.
3. Check the business property on each trace; compare with CitaLab's own oracle.
4. Group model calls whose recorded request is identical, and show their answers.
5. Summarise CitaLab's repeated calls (experiment B).
6. Find the first divergence between the successful and a failed Gemini episode.
7. Reduce each failure to the events the violated property needs.
8. If CitaLab is installed, re-execute the evaluated code against the recorded answers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from examples.citalab_r02.importer import DATA, load_episodes, to_recording
from examples.citalab_r02.scenario import r02
from reprolab import check, reduce_violation, save_run
from reprolab.diff import first_divergence


def _first(rec, name):
    return next((e for e in rec.events if e.name == name), None)


def _decision(rec) -> str:
    """The first interpretation: the context agent's intent, or S1's first proposal."""
    context = _first(rec, "llm.context")
    if context:
        return f"context: {context.outcome['ok'].get('intent')}"
    proposal = _first(rec, "core.proposal")
    return f"single: proposes {proposal.outcome['ok']['operation']}" if proposal else "single: no proposal"


def _request_key(event) -> str:
    return hashlib.sha256(json.dumps(event.request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CitaLab N-R02 investigation")
    p.add_argument("--db", default=str(Path(tempfile.gettempdir()) / "reprolab-citalab-r02.db"))
    p.add_argument("--no-reexecute", action="store_true")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    episodes = load_episodes()
    print(f"1. Evidence: {len(episodes)} episodes from CitaLab, every result line and trace file matches its SHA-256")

    recs = {ep.cell_id: to_recording(ep) for ep in episodes}
    ids = {cell: save_run(args.db, rec) for cell, rec in recs.items()}
    derived = sum(e.reconstructed for rec in recs.values() for e in rec.events)
    total = sum(len(rec.events) for rec in recs.values())
    print(f"2. Rebuilt {len(recs)} runs ({total} events, {derived} with a reconstruction rule) into {args.db}")

    print("\n3. Property 'reschedule-replaces-target' on the trace vs CitaLab's goal check")
    agree = 0
    invariants = list(r02.invariants)
    for cell, rec in recs.items():
        violated = bool(check(rec.events, invariants))
        oracle = rec.extra["citalab"]["oracle_goal"]["pass"]
        agree += violated != oracle
        print(f"   {ids[cell]}  {cell:34} {_decision(rec):28} property {'VIOLATED' if violated else 'holds':8}"
              f"  CitaLab goal {'pass' if oracle else 'FAIL'}")
    print(f"   agreement with CitaLab's oracle: {agree}/{len(recs)}")

    print("\n4. First model call of each episode, grouped by identical recorded request")
    groups: dict[tuple, list] = defaultdict(list)
    for cell, rec in recs.items():
        first = next(e for e in rec.events if e.kind == "llm")
        groups[(first.name, rec.extra["citalab"]["model"], _request_key(first))].append((cell, first))
    for (name, model, key), items in groups.items():
        answers = Counter(json.dumps({k: e.outcome["ok"].get(k) for k in ("intent", "appointment_id")}
                                     if name == "llm.context" else e.outcome["ok"].get("tool"), ensure_ascii=False)
                          for _, e in items)
        print(f"   {name} on {model}, request {key}: {len(items)} identical requests -> "
              + "; ".join(f"{n}x {a}" for a, n in answers.items()))

    print("\n5. CitaLab's repeated calls of the context agent on the same first message (experiment B)")
    rows = [json.loads(line) for line in (DATA / "model-checks-r02.jsonl").read_text(encoding="utf-8").splitlines()]
    counts = Counter((r["provider"], r["variant"], r["intent"]) for r in rows if r["experiment"] == "B")
    for (provider, variant, intent), n in sorted(counts.items()):
        print(f"   {provider:6} prompt {variant!r:18} intent {intent}: {n}")

    print("\n6. First divergence: Gemini M5 (succeeded) vs Gemini H (failed), N-R02 primary")
    d = first_divergence(recs["google:M5:N-R02:primary"].events, recs["google:H:N-R02:primary"].events)
    print(f"   identical for the first {d.position} event(s); then {d.kind}, differing at {', '.join(d.paths)}")

    print("\n7. Reduction of each failure (same invariant, same anchor event)")
    for cell, rec in recs.items():
        if check(rec.events, invariants):
            red = reduce_violation(rec.events, invariants)
            print(f"   {cell:34} {red.original_events:2} -> {len(red.events):2} events: "
                  + " > ".join(e.name for e in red.events))

    if not args.no_reexecute:
        print("\n8. Re-execution of the evaluated CitaLab code against the recorded model answers (offline)")
        try:
            import citalab  # noqa: F401
        except ImportError:
            print("   skipped: CitaLab is not installed in this environment (see docs/investigations/citalab-r02.md)")
        else:
            from examples.citalab_r02.reexecute import COUNTERFACTUAL_ASSUMPTIONS, gemini_h_counterfactual, reexecute
            reproduced = 0
            for ep in episodes:
                r = reexecute(ep)
                reproduced += r.faithful
                print(f"   {'REPRODUCED' if r.faithful else 'DIVERGED':10} {ep.cell_id:34} {r.llm_calls:2} model calls,"
                      f" effects {r.effects}" + (f"; {r.divergence}" if r.divergence else ""))
            print(f"   {reproduced}/{len(episodes)} episodes reproduced: same calls, events, replies and final agenda")
            cf = gemini_h_counterfactual(episodes)
            print("\n9. Counterfactual (hypothesis test, not evidence): Gemini H N-R02 with the context answers of M5")
            print(f"   effects {cf.effects}; turn statuses as recorded: {all(t.status_match for t in cf.turns)}; "
                  f"fallback text for {', '.join(cf.unrecorded_calls)}")
            for a in COUNTERFACTUAL_ASSUMPTIONS:
                print(f"   assumption: {a}")
    print(f"\nExplore: python -m reprolab --db {args.db} list | show <run> | diff <a> <b> | reduce <run>")
    return 0


if __name__ == "__main__":
    sys.exit(main())

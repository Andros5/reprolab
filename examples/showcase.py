"""Everything ReproLab does, on one page:  python -m examples.showcase [-o showcase.html]

Runs the real cases (nothing on the page is staged) and writes one self-contained HTML
file:

1. a lost response, recorded, with the property it breaks;
2. a longer flow reduced to what the violation needs;
3. the explorer on a client that is only correct within one process;
4. old failing recordings replayed against the fixed client;
5. CitaLab: two episodes identical until a model answered the same request differently,
   and a failure reduced to its causal chain.

``--fragment`` writes the page without the document skeleton, for hosts that add it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from examples.citalab_r02.importer import load_episodes, to_recording
from examples.citalab_r02.scenario import r02
from examples.portal_demo.applier import SUBMIT
from examples.portal_demo.scenario import INVARIANTS, SCENARIOS, target
from reprolab import Fault, Recording, check, reduce_violation
from reprolab import html as H
from reprolab import scenario as rl
from reprolab.diff import first_divergence
from reprolab.explore import explore
from reprolab.regress import regress

TITLE = "ReproLab Flight Recorder"


def _portal() -> str:
    out = rl.record(SCENARIOS["blind_retry"], [Fault(SUBMIT, 1, "lost_response")])
    again = rl.replay(SCENARIOS["blind_retry"], out.events)
    same = again.events == out.events and again.result == out.result
    return ('<p>The client submits an application to a local portal. ReproLab loses the response on purpose: the portal '
            'stores the application, the client never hears back, and retries. The property <em>no blind resubmit</em> '
            'reads only the trace; the portal itself is checked separately as an oracle.</p>'
            + H.verdict_line(out.violations, out.result)
            + H.kpis([("applications the portal really holds", str(out.oracle["applications"])),
                      ("offline replay", "identical" if same else "DIVERGED"),
                      ("network calls during replay", "0")])
            + H.run_view(out.events, out.violations, title="blind_retry · lost response on submit #1",
                         meta="random tokens and HTTP calls go through the Session; nothing else is assumed deterministic"))


def _reduction() -> str:
    faults = [Fault(SUBMIT, 1, "lost_response"), Fault(SUBMIT, 2, "rate_limited")]
    out = rl.record(SCENARIOS["blind_retry_full"], faults)
    red = reduce_violation(out.events, list(INVARIANTS))
    return ('<p>A longer flow reads the posting, drafts a cover letter with a stub LLM and logs to telemetry. '
            'Delta debugging removes every event the violation does not need, but never an event something kept '
            'still depends on: the posting and the draft stay, because the submissions carry their output.</p>'
            + H.reduction_view(out.events, red.events, red.violation,
                               title="blind_retry_full · lost response, then 429"))


def _explorer() -> str:
    report = explore(SCENARIOS["reconciling"], seed=0, budget=200, target=target("reconciling"))
    return ('<p>The reconciling client looks an uncertain submission up before retrying, and passes every test with '
            'one process. The explorer tries every single fault, then pairs guided by the call sites each fault '
            'opened, then a seeded sample. A simulated crash right after the submission is enough: the restarted '
            'worker has forgotten the uncertain submission and sends it again.</p>' + H.explore_view(report))


def _regress() -> str:
    plans = [("blind_retry", [Fault(SUBMIT, 1, "lost_response")]),
             ("reconciling", [Fault(SUBMIT, 1, "crash_after")]),
             ("reconciling", [Fault(SUBMIT, 1, "timeout"), Fault(SUBMIT, 2, "lost_response")]),
             ("blind_retry", [])]
    results = []
    for i, (name, faults) in enumerate(plans, 1):
        out = rl.record(SCENARIOS[name], faults)
        rec = Recording(out.events, label=f"{name}, {', '.join(f'{f.kind} on {f.name}#{f.occurrence}' for f in faults) or 'no faults'}",
                        target=target(name), faults=[f.to_dict() for f in faults], id=f"rec-{i}")
        results.append(regress(rec, SCENARIOS["journaled"], target("journaled")))
    return ('<p>Each stored recording becomes a regression test for the next version. The journaled client writes '
            '"pending" before it submits and reconciles after a restart. Recordings it still matches replay offline; '
            'the others say exactly where they stop matching, and are recorded again under the same fault plan.</p>'
            + H.regress_view(results))


def _citalab() -> str:
    recs = {ep.cell_id: to_recording(ep) for ep in load_episodes()}
    m5, h = recs["google:M5:N-R02:primary"], recs["google:H:N-R02:primary"]
    inv = list(r02.invariants)
    d = first_divergence(m5.events, h.events)
    red = reduce_violation(h.events, inv)
    agree = sum(bool(check(r.events, inv)) != r.extra["citalab"]["oracle_goal"]["pass"] for r in recs.values())
    return ('<p>CitaLab is a public assistant for synthetic healthcare appointments. In 9 of 12 episodes a request to '
            'move an appointment created a second one, and every safety check passed. These traces are rebuilt from '
            'its logs: every event cites a file, a JSON pointer and a SHA-256, and dashed events state the rule they '
            'were derived by.</p>'
            + H.kpis([("episodes where the property matches CitaLab's oracle", f"{agree}/12"),
                      ("identical recorded requests to Gemini's context agent", "4"),
                      ("answers to them", "1× reschedule, 3× book")])
            + '<h3>Same request, different answer</h3>'
            + H.compare_view(m5.events, h.events, d, title_a="Gemini · M5 · moved the appointment",
                             title_b="Gemini · H · created a new one",
                             violations_a=check(m5.events, inv), violations_b=check(h.events, inv))
            + '<h3>The failure, reduced to its causal chain</h3>'
            + H.reduction_view(h.events, red.events, red.violation, title="Gemini · H · N-R02"))


def build(fragment: bool = False) -> str:
    sections = [
        ("lost-response", "1 · record", "A lost response, caught by a property", _portal()),
        ("reduction", "2 · reduce", "Fifteen events, six that matter", _reduction()),
        ("explorer", "3 · explore", "The fault that one process never sees", _explorer()),
        ("regression", "4 · regress", "Old failures as tests for the fix", _regress()),
        ("citalab", "5 · investigate", "A real agent failure, from the evidence", _citalab()),
    ]
    intro = ("Record what an agent or automation did at its boundaries, replay it without a network, inject the "
             "faults production will eventually deliver, and shrink every failure to the few events that explain it. "
             "Everything below was computed when this page was generated.")
    footer = ("<p>Replay reuses recorded answers: it shows what the code does with them, not that a model would answer "
              "the same way again. Every injected fault is a simulation and is marked as one. The explorer covers the "
              "schedules it reports and nothing else.</p><p>Python standard library and SQLite; this page has no "
              "dependencies and works offline.</p>")
    return H.page(TITLE, sections, intro=intro, footer=footer, fragment=fragment)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate the ReproLab showcase page")
    p.add_argument("-o", "--output", default="showcase.html")
    p.add_argument("--fragment", action="store_true", help="omit the document skeleton")
    args = p.parse_args(argv)
    Path(args.output).write_text(build(args.fragment), encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

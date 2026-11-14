"""Self-contained HTML views of traces: a flight recorder you can read.

One file, no dependencies, opens offline (fonts fall back to system faces). Visual code:
solid marks were observed, diagonal hatching marks a simulated fault, a dashed outline
marks an event reconstructed from another system's logs, and arcs in the left gutter
are dependencies. Clicking an event shows its full request, outcome and evidence.

Views: a single run, two runs side by side (first divergence marked), a reduction
(kept and dropped events), an exploration report, and a regression table. ``page()``
assembles any of them into a document, or into a fragment for a host that supplies the
document skeleton itself.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Any, Iterable

from reprolab.diff import (
    DIFFERENT_CALL, DIFFERENT_REQUEST, LENGTH, SAME_REQUEST_DIFFERENT_OUTCOME, Divergence, _brief,
)
from reprolab.events import Event
from reprolab.invariants import Violation

ROW = 34  # px per event row; the dependency arcs are laid out on this grid
GUTTER = 64

KIND_GLYPH = {"llm": "L", "http": "H", "tool": "T", "user": "U"}
TYPE_GLYPH = {"clock": "◷", "random": "✱"}

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&"
         "family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap")

CSS = """
/* Layout: a flight-recorder strip per trace, rows on a fixed grid so dependency arcs
   can be drawn in the left gutter; summaries above, detail on demand below. */
:root {
  --ground: #f2f4f7; --surface: #ffffff; --ink: #18202c; --muted: #5a6372; --line: #d8dde4;
  --accent: #2b59c3; --accent-soft: #e4ebfb;
  --bad: #b42318; --bad-soft: #fbe9e7; --warn: #9a5a00; --warn-soft: #fbf0dc;
  --good: #1e7a4b; --good-soft: #e3f3ea; --same: #eef1f5;
  --display: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --text: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --ground: #0f141b; --surface: #161d27; --ink: #e5e9ef; --muted: #9aa4b2; --line: #2a3340;
  --accent: #82a5ff; --accent-soft: #1d2a47;
  --bad: #ff8274; --bad-soft: #3a1d1b; --warn: #e3a547; --warn-soft: #362812;
  --good: #63c58f; --good-soft: #15301f; --same: #1a222d; color-scheme: dark } }
:root[data-theme="dark"] {
  --ground: #0f141b; --surface: #161d27; --ink: #e5e9ef; --muted: #9aa4b2; --line: #2a3340;
  --accent: #82a5ff; --accent-soft: #1d2a47;
  --bad: #ff8274; --bad-soft: #3a1d1b; --warn: #e3a547; --warn-soft: #362812;
  --good: #63c58f; --good-soft: #15301f; --same: #1a222d; color-scheme: dark }
* { box-sizing: border-box }
body { background: var(--ground); color: var(--ink); font: 15px/1.55 var(--text); margin: 0 }
.wrap { max-width: 1180px; margin: 0 auto; padding-block: 28px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 40px }
h1, h2, h3 { font-family: var(--display); font-weight: 600; text-wrap: balance; margin: 0; line-height: 1.15 }
h1 { font-size: clamp(28px, 4.2vw, 44px); letter-spacing: -0.01em }
h2 { font-size: 26px } h3 { font-size: 18px }
p { margin: 0; max-width: 68ch } .muted { color: var(--muted) }
code, .mono { font-family: var(--mono); font-size: 0.92em }
a { color: var(--accent) } a:focus-visible, .ev:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
.eyebrow { font: 500 12px/1 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted) }
header.top { display: grid; gap: 14px }
nav.toc { display: flex; flex-wrap: wrap; gap: 8px }
nav.toc a { font: 500 13px/1 var(--mono); padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px;
  text-decoration: none; color: var(--ink); background: var(--surface) }
section.view { display: grid; gap: 16px; scroll-margin-top: 16px }
.lede { display: grid; gap: 8px }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; color: var(--muted) }
.legend span { display: inline-flex; align-items: center; gap: 6px }
.sw { width: 22px; height: 12px; border-radius: 2px; border: 1px solid var(--line); background: var(--surface) }
.sw.sim { background: repeating-linear-gradient(135deg, var(--warn-soft) 0 4px, transparent 4px 8px); border-color: var(--warn) }
.sw.rec { border: 1.5px dashed var(--muted) }
.sw.bad { background: var(--bad-soft); border-color: var(--bad) }
.sw.arc { border: 0; border-top: 2px solid var(--accent); border-radius: 0; height: 2px; background: none }
.kpis { display: flex; flex-wrap: wrap; gap: 12px }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; min-width: 132px;
  display: grid; gap: 2px }
.kpi b { font: 600 24px/1.1 var(--display); font-variant-numeric: tabular-nums }
.kpi span { font-size: 12px; color: var(--muted) }
.strips { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)) }
.strip { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; min-width: 0; display: grid }
.strip > .head { padding: 12px 14px; border-bottom: 1px solid var(--line); display: grid; gap: 4px }
.strip > .head .title { font: 600 15px/1.3 var(--display) }
.strip > .head .meta { font: 12px/1.4 var(--mono); color: var(--muted); overflow-wrap: anywhere }
.rows { position: relative; overflow-x: auto }
.rows svg.arcs { position: absolute; left: 0; top: 0; pointer-events: none }
.arcs path { fill: none; stroke: var(--accent); stroke-opacity: 0.35; stroke-width: 1.4 }
.arcs path.hot { stroke-opacity: 1; stroke-width: 2.2 }
.ev { height: 34px; display: grid; grid-template-columns: 40px 24px 190px minmax(0, 1fr) 176px; align-items: center;
  gap: 8px; padding-left: 64px; padding-right: 10px; border-top: 1px solid transparent; cursor: pointer; position: relative;
  font-size: 13px; white-space: nowrap; min-width: 520px }
.ev:hover { background: var(--accent-soft) }
.ev.sel { background: var(--accent-soft); box-shadow: inset 3px 0 0 var(--accent) }
.ev .seq { font: 12px var(--mono); color: var(--muted); text-align: right; font-variant-numeric: tabular-nums }
.ev .g { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 4px; border: 1px solid var(--line);
  font: 600 11px var(--mono); background: var(--surface) }
.ev .name { font: 500 13px var(--mono); overflow: hidden; text-overflow: ellipsis }
.ev .sum { color: var(--muted); overflow: hidden; text-overflow: ellipsis; font: 12px var(--mono) }
.ev .tags { display: flex; gap: 4px; justify-content: flex-end; overflow: hidden }
.tag { font: 600 10px/1 var(--mono); letter-spacing: 0.04em; text-transform: uppercase; padding: 4px 6px; border-radius: 4px;
  border: 1px solid var(--line); color: var(--muted); background: var(--surface) }
.tag.sim { color: var(--warn); border-color: var(--warn);
  background: repeating-linear-gradient(135deg, var(--warn-soft) 0 4px, var(--surface) 4px 8px) }
.tag.bad { color: var(--bad); border-color: var(--bad); background: var(--bad-soft) }
.tag.rec { border-style: dashed }
.ev.fault .g { border-color: var(--warn); background: repeating-linear-gradient(135deg, var(--warn-soft) 0 3px, var(--surface) 3px 6px) }
.ev.violation { background: var(--bad-soft) } .ev.violation .g { border-color: var(--bad); color: var(--bad) }
.ev.rec .g { border-style: dashed; border-color: var(--muted) }
.ev.same { background: var(--same) } .ev.same .name, .ev.same .sum { opacity: 0.75 }
.ev.dropped { opacity: 0.38 } .ev.dropped .name { text-decoration: line-through }
.ev.diverge { box-shadow: inset 0 2px 0 var(--accent) }
.ev.empty { cursor: default; color: var(--muted); font-style: italic }
.ev.empty:hover { background: none }
.split { font: 600 12px/1.3 var(--mono); color: var(--accent); padding: 6px 14px 6px 64px; border-top: 2px solid var(--accent); }
.inspector { border-top: 1px solid var(--line); padding: 12px 14px; display: grid; gap: 8px; min-width: 0 }
.inspector .t { font: 600 13px var(--mono) }
.inspector pre { margin: 0; font: 12px/1.5 var(--mono); background: var(--ground); border-radius: 6px; padding: 10px;
  max-height: 260px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere }
.inspector .grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)) }
.verdict { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 14px }
.pill { font: 600 11px/1 var(--mono); letter-spacing: 0.05em; text-transform: uppercase; padding: 6px 8px; border-radius: 999px;
  border: 1px solid var(--line); background: var(--surface) }
.pill.good { color: var(--good); border-color: var(--good); background: var(--good-soft) }
.pill.bad { color: var(--bad); border-color: var(--bad); background: var(--bad-soft) }
.pill.warn { color: var(--warn); border-color: var(--warn); background: var(--warn-soft) }
.pill.info { color: var(--accent); border-color: var(--accent); background: var(--accent-soft) }
.callout { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; display: grid; gap: 8px }
.callout table { border-collapse: collapse; font: 12px var(--mono); width: 100% }
.callout td, .callout th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere }
.cards { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 250px), 1fr)) }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; display: grid; gap: 10px; align-content: start; min-width: 0 }
.card .sig { font: 600 15px/1.35 var(--display) }
.chips { display: flex; flex-wrap: wrap; gap: 6px }
.chip { font: 12px var(--mono); padding: 4px 8px; border-radius: 4px; border: 1px solid var(--warn); color: var(--ink);
  background: repeating-linear-gradient(135deg, var(--warn-soft) 0 4px, var(--surface) 4px 8px) }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; font-size: 13px }
.facts dt { color: var(--muted) } .facts dd { margin: 0; font-variant-numeric: tabular-nums; min-width: 0; overflow-wrap: anywhere }
.bars { display: grid; gap: 10px }
.bar { display: grid; grid-template-columns: 150px 1fr 120px; gap: 10px; align-items: center; font-size: 13px }
.bar .track { height: 10px; background: var(--same); border-radius: 5px; overflow: hidden; border: 1px solid var(--line) }
.bar .fill { height: 100%; background: var(--accent) }
.bar .n { font: 12px var(--mono); color: var(--muted); font-variant-numeric: tabular-nums; text-align: right }
.table { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 10px }
.table table { border-collapse: collapse; width: 100%; min-width: 640px; font-size: 13px }
.table th { font: 600 11px/1 var(--mono); letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line) }
.table td { padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top }
.table tr:last-child td { border-bottom: 0 }
.match { display: grid; gap: 4px; min-width: 120px }
.match .track { height: 6px; background: var(--bad-soft); border-radius: 3px; overflow: hidden }
.match .fill { height: 100%; background: var(--good) }
footer { font-size: 13px; color: var(--muted); display: grid; gap: 6px }
@media (max-width: 640px) { .bar { grid-template-columns: 1fr; gap: 4px } .bar .n { text-align: left } }
@media (prefers-reduced-motion: no-preference) { .ev { transition: background-color 120ms } }
"""

JS = """
(() => {
  const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  const show = (strip, seq) => {
    const data = JSON.parse(strip.querySelector('script[type="application/json"]').textContent);
    const e = data.find(x => x.seq === seq); if (!e) return;
    strip.querySelectorAll('.ev.sel').forEach(n => n.classList.remove('sel'));
    const row = strip.querySelector(`.ev[data-seq="${seq}"]`); if (row) row.classList.add('sel');
    strip.querySelectorAll('svg.arcs path').forEach(p => p.classList.toggle('hot', p.dataset.to == seq || p.dataset.from == seq));
    const ins = strip.querySelector('.inspector');
    const block = (label, v) => `<div><div class="eyebrow">${label}</div><pre>${esc(JSON.stringify(v, null, 2))}</pre></div>`;
    ins.innerHTML = `<div class="t">#${e.seq} ${esc(e.type)} ${esc(e.name)}${e.kind ? ' · ' + esc(e.kind) : ''}</div>` +
      (e.note ? `<div class="muted">${esc(e.note)}</div>` : '') +
      `<div class="grid">${block('request', e.request)}${block('outcome', e.outcome)}</div>` +
      (e.fault ? block('fault (simulated)', e.fault) : '') +
      (e.deps.length ? `<div class="muted mono">depends on ${e.deps.map(d => '#' + d).join(' ')}</div>` : '') +
      (e.evidence ? block(e.evidence.rule ? 'evidence (reconstructed)' : 'evidence (verbatim)', e.evidence) : '');
  };
  document.querySelectorAll('.strip').forEach(strip => {
    strip.querySelectorAll('.ev[data-seq]').forEach(row => {
      const go = () => show(strip, Number(row.dataset.seq));
      row.addEventListener('click', go);
      row.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(); } });
    });
    const start = strip.dataset.start; if (start) show(strip, Number(start));
  });
})();
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


@dataclass
class Row:
    """One line of a strip: an event, or an empty slot that keeps two strips aligned."""
    event: Event | None
    classes: tuple[str, ...] = ()
    note: str = ""


def _summary(e: Event) -> str:
    if e.type != "call":
        return f"= {_brief(e.outcome.get('ok'), 28)}"
    if e.ok:
        return f"{_brief(e.request, 24)} → {_brief(e.outcome['ok'], 30)}"
    err = e.error or {}
    return f"{_brief(e.request, 24)} → {err.get('type')} (effect {err.get('effect')})"


def _glyph(e: Event) -> str:
    return KIND_GLYPH.get(e.kind) or TYPE_GLYPH.get(e.type, "·")


def _arcs(rows: list[Row]) -> str:
    position = {r.event.seq: i for i, r in enumerate(rows) if r.event is not None}
    paths = []
    for i, r in enumerate(rows):
        if r.event is None:
            continue
        for d in r.event.deps:
            if d not in position:
                continue
            y1, y2 = position[d] * ROW + ROW / 2, i * ROW + ROW / 2
            reach = min(GUTTER - 8, 10 + (y2 - y1) / ROW * 6)
            x = GUTTER - 4
            paths.append(f'<path data-from="{d}" data-to="{r.event.seq}" '
                         f'd="M{x},{y1:.1f} C{x - reach:.1f},{y1:.1f} {x - reach:.1f},{y2:.1f} {x},{y2:.1f}"/>')
    height = max(1, len(rows)) * ROW
    return f'<svg class="arcs" width="{GUTTER}" height="{height}" viewBox="0 0 {GUTTER} {height}" aria-hidden="true">' \
           + "".join(paths) + "</svg>"


def _row(r: Row, violations: dict[int, str]) -> str:
    e = r.event
    if e is None:
        return f'<div class="ev empty {" ".join(r.classes)}"><span></span><span></span><span>{esc(r.note or "—")}</span></div>'
    classes = list(r.classes)
    tags = []
    if e.fault:
        classes.append("fault")
        tags.append(f'<span class="tag sim" title="simulated fault">{esc(e.fault["kind"])}</span>')
    if e.reconstructed:
        classes.append("rec")
        tags.append('<span class="tag rec" title="derived by a stated rule">derived</span>')
    if e.seq in violations:
        classes.append("violation")
        tags.append(f'<span class="tag bad" title="{esc(violations[e.seq])}">violation</span>')
    if not e.ok and e.type == "call" and not e.fault:
        tags.append(f'<span class="tag">{esc((e.error or {}).get("type"))}</span>')
    return (f'<div class="ev {" ".join(classes)}" data-seq="{e.seq}" tabindex="0" role="button" '
            f'aria-label="event {e.seq} {esc(e.name)}" title="{esc(e.describe())}">'
            f'<span class="seq">#{e.seq}</span><span class="g">{esc(_glyph(e))}</span>'
            f'<span class="name">{esc(e.name)}</span><span class="sum">{esc(_summary(e))}</span>'
            f'<span class="tags">{"".join(tags)}</span></div>')


def _payload(rows: list[Row]) -> str:
    data = []
    for r in rows:
        if r.event is None:
            continue
        d = r.event.to_dict()
        d["note"] = r.note
        data.append(d)
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def strip(title: str, rows: list[Row], *, meta: str = "", violations: Iterable[Violation] = (),
          start: int | None = None, split_at: int | None = None, split_label: str = "") -> str:
    """A trace strip. ``split_at`` draws the divergence line above that row index."""
    flagged = {v.seq: str(v) for v in violations}
    if start is None:
        start = next(iter(flagged), None) or next((r.event.seq for r in rows if r.event is not None), None)
    body = []
    for i, r in enumerate(rows):
        if split_at is not None and i == split_at:
            body.append(f'<div class="split">{esc(split_label)}</div>')
        body.append(_row(r, flagged))
    # The arcs are laid out on the row grid; a split line shifts the rows below it.
    arcs = _arcs(rows) if split_at is None else ""
    return (f'<div class="strip" data-start="{start or ""}">'
            f'<div class="head"><div class="title">{esc(title)}</div>'
            + (f'<div class="meta">{esc(meta)}</div>' if meta else "") + "</div>"
            f'<div class="rows">{arcs}{"".join(body)}</div>'
            f'<div class="inspector"><div class="muted">Select an event to see its request, outcome and evidence.</div></div>'
            f'<script type="application/json">{_payload(rows)}</script></div>')


def legend() -> str:
    return ('<div class="legend" aria-label="legend">'
            '<span><i class="sw"></i>observed</span>'
            '<span><i class="sw sim"></i>simulated fault</span>'
            '<span><i class="sw rec"></i>reconstructed from logs</span>'
            '<span><i class="sw bad"></i>property violated</span>'
            '<span><i class="sw arc"></i>depends on</span></div>')


def verdict_line(violations: list[Violation], result: Any = None) -> str:
    pill = '<span class="pill bad">property violated</span>' if violations else '<span class="pill good">property holds</span>'
    text = "".join(f'<span class="mono">{esc(v)}</span>' for v in violations[:2])
    res = f'<span class="muted">result {esc(json.dumps(result, ensure_ascii=False))}</span>' if result is not None else ""
    return f'<div class="verdict">{pill}{text}{res}</div>'


# -- views ------------------------------------------------------------------------------

def run_view(events: list[Event], violations: list[Violation], *, title: str, meta: str = "") -> str:
    return strip(title, [Row(e) for e in events], meta=meta, violations=violations)


def compare_view(a: list[Event], b: list[Event], divergence: Divergence | None, *, title_a: str, title_b: str,
                 violations_a: Iterable[Violation] = (), violations_b: Iterable[Violation] = ()) -> str:
    """Two traces aligned by position; rows before the first divergence are marked identical."""
    n = max(len(a), len(b))
    cut = divergence.position if divergence else n
    label = {DIFFERENT_CALL: "first divergence: a different call",
             DIFFERENT_REQUEST: "first divergence: same call, different request",
             SAME_REQUEST_DIFFERENT_OUTCOME: "first divergence: same request, different answer",
             LENGTH: "first divergence: one trace ends"}.get(divergence.kind if divergence else "", "")

    def rows(events: list[Event]) -> list[Row]:
        out = []
        for i in range(n):
            e = events[i] if i < len(events) else None
            cls = ("same",) if i < cut else (("diverge",) if i == cut else ())
            out.append(Row(e, cls, "" if e else "trace ends"))
        return out

    start_a = a[cut].seq if divergence and cut < len(a) else None
    start_b = b[cut].seq if divergence and cut < len(b) else None
    note = ""
    if divergence and divergence.paths:
        items = "".join(f"<tr><td>{esc(p)}</td><td>{esc(_brief(x, 60))}</td><td>{esc(_brief(y, 60))}</td></tr>"
                        for p, (x, y) in zip(divergence.paths, divergence.values))
        note = (f'<div class="callout"><div class="eyebrow">what differs at position {cut + 1}</div>'
                f'<table><tr><th>path</th><th>A</th><th>B</th></tr>{items}</table></div>')
    summary = (f'<div class="verdict"><span class="pill info">identical for {cut} event{"s" if cut != 1 else ""}</span>'
               f'<span class="muted">{esc(label or "no divergence: the traces are identical")}</span></div>')
    return (summary + note + '<div class="strips">'
            + strip(title_a, rows(a), violations=violations_a, start=start_a, split_at=cut if divergence else None,
                    split_label=label)
            + strip(title_b, rows(b), violations=violations_b, start=start_b, split_at=cut if divergence else None,
                    split_label=label)
            + "</div>")


def reduction_view(original: list[Event], kept: list[Event], violation: Violation, *, title: str) -> str:
    keep = {e.seq for e in kept}
    rows = [Row(e, () if e.seq in keep else ("dropped",)) for e in original]
    return ('<div class="verdict"><span class="pill info">'
            f'{len(original)} → {len(kept)} events</span><span class="muted">same property, same anchor event '
            f'#{violation.seq}; faded rows were removed</span></div>'
            + strip(title, rows, violations=[violation], start=violation.seq,
                    meta="kept rows are what the violation needs, with every event they depend on"))


def kpis(items: list[tuple[str, str]]) -> str:
    return '<div class="kpis">' + "".join(f'<div class="kpi"><b>{esc(v)}</b><span>{esc(k)}</span></div>'
                                          for k, v in items) + "</div>"


def explore_view(report) -> str:  # reprolab.explore.Report
    from reprolab.explore import ORACLE_ONLY, PROPERTY, UNHANDLED, fmt
    cats = {PROPERTY: 0, UNHANDLED: 0, ORACLE_ONLY: 0}
    for c in report.counterexamples:
        cats[c.category] += 1
    head = kpis([("schedules run", str(report.runs)), ("runs per second", f"{report.runs / report.seconds:.0f}"
                 if report.seconds else "-"), ("property violations", str(cats[PROPERTY])),
                 ("unhandled exceptions", str(cats[UNHANDLED])), ("oracle-only failures", str(cats[ORACLE_ONLY]))])
    bars = []
    for size in sorted(report.space):
        done, total = report.explored.get(size, 0), report.space[size]
        pct = 100 * done / total if total else 0
        bars.append(f'<div class="bar"><span>schedules of {size} fault{"s" if size > 1 else ""}</span>'
                    f'<span class="track" role="img" aria-label="{done} of {total}"><span class="fill" style="width:{pct:.1f}%;display:block"></span></span>'
                    f'<span class="n">{done} / {total}</span></div>')
    coverage = (f'<div class="callout"><div class="eyebrow">coverage of the fault space over the {len(report.sites)} '
                f'call sites reached</div><div class="bars">{"".join(bars)}</div>'
                f'<p class="muted">{"Space exhausted." if report.exhausted else "Budget spent before the space was exhausted."} '
                'Findings are reproducible counterexamples; a clean result would not show the code is correct.</p></div>')
    cards = []
    pill = {PROPERTY: "bad", UNHANDLED: "warn", ORACLE_ONLY: "info"}
    for c in report.counterexamples:
        chips = "".join(f'<span class="chip">{esc(f"{f.name}#{f.occurrence} {f.kind}")}</span>' for f in c.minimal) \
            or '<span class="muted">no fault needed</span>'
        trace = (f"<dt>trace</dt><dd>{c.trace_events} → {c.reduced_events} events</dd>"
                 if c.reduced_events is not None else "")
        cards.append(f'<div class="card"><div><span class="pill {pill[c.category]}">{esc(c.category)}</span></div>'
                     f'<div class="sig">{esc(c.signature)}</div><div class="muted">{esc(c.message)}</div>'
                     f'<div><div class="eyebrow">minimal fault schedule</div><div class="chips">{chips}</div></div>'
                     f'<dl class="facts"><dt>first found</dt><dd>run {c.first_run} ({c.first_seconds:.2f}s)</dd>'
                     f'<dt>runs hitting it</dt><dd>{c.hits}</dd><dt>first schedule</dt><dd class="mono">{esc(fmt(c.schedule))}</dd>'
                     f'<dt>reduction</dt><dd>{len(c.schedule)} → {len(c.minimal)} faults, {c.reexecutions} re-executions</dd>'
                     f'{trace}</dl></div>')
    strips = ""
    shown = [c for c in report.counterexamples if c.category == PROPERTY and c.events]
    if shown:
        c = shown[0]
        strips = ('<h3>The first property counterexample, minimal run</h3>'
                  + strip(c.signature, [Row(e) for e in c.events], violations=c.violations,
                          meta=f"faults: {fmt(c.minimal)}"))
    return head + coverage + f'<div class="cards">{"".join(cards)}</div>' + strips


def regress_view(results: list) -> str:  # list[reprolab.regress.RegressionResult]
    from reprolab.regress import COMPATIBLE, FIXED, REGRESSED, STILL_FAILING, STILL_PASSING
    tone = {FIXED: "good", STILL_PASSING: "info", STILL_FAILING: "bad", REGRESSED: "bad"}
    rows = []
    for r in results:
        total = max(1, len(r.old_events))
        pct = 100 * r.reproduced / total
        compat = ("compatible offline" if r.compatibility == COMPATIBLE else
                  f"incompatible from #{r.divergence_seq}" if r.divergence_seq else r.compatibility)
        faults = ", ".join(r.faults_planned) or "none"
        rows.append(f'<tr><td class="mono">{esc(r.run_id or "-")}</td><td>{esc(r.label)}</td>'
                    f'<td><span class="pill {tone.get(r.verdict, "")}">{esc(r.verdict)}</span></td>'
                    f'<td><div class="match"><span>{esc(compat)}</span><span class="track"><span class="fill" '
                    f'style="width:{pct:.0f}%;display:block"></span></span><span class="muted mono">{r.reproduced}/{total} '
                    f'recorded events matched</span></div></td>'
                    f'<td class="mono">{esc(faults)}</td></tr>')
    table = ('<div class="table"><table><thead><tr><th>run</th><th>recording</th><th>verdict</th>'
             '<th>compatibility with the new code</th><th>fault plan</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table></div>")
    detail = ""
    for r in results:
        if r.rerecorded and r.first_difference is not None:
            detail = ("<h3>Before and after, same fault plan</h3>"
                      + compare_view(r.old_events, r.new_events, r.first_difference,
                                     title_a=f"old code · {r.label}", title_b=f"new code · {r.new_target}",
                                     violations_a=r.old_violation_objects, violations_b=r.new_violation_objects))
            break
    return table + detail


def page(title: str, sections: list[tuple[str, str, str, str]], *, intro: str = "", footer: str = "",
         fragment: bool = False) -> str:
    """``sections``: (anchor, eyebrow, heading, html). ``fragment`` omits the document
    skeleton for hosts that supply it."""
    toc = "".join(f'<a href="#{esc(a)}">{esc(h)}</a>' for a, _, h, _ in sections) if len(sections) > 1 else ""
    body = (f'<div class="wrap"><header class="top"><div class="eyebrow">ReproLab</div><h1>{esc(title)}</h1>'
            + (f"<p>{intro}</p>" if intro else "") + legend()
            + (f'<nav class="toc" aria-label="sections">{toc}</nav>' if toc else "") + "</header>"
            + "".join(f'<section class="view" id="{esc(a)}"><div class="lede"><div class="eyebrow">{esc(e)}</div>'
                      f"<h2>{esc(h)}</h2></div>{content}</section>" for a, e, h, content in sections)
            + (f"<footer>{footer}</footer>" if footer else "") + "</div>")
    head = (f'<title>{esc(title)}</title><meta name="claude:viewport-fit-sides" content="cover">'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="{FONTS}">'
            f"<style>{CSS}</style>")
    if fragment:
        return f"{head}\n{body}\n<script>{JS}</script>\n"
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f"{head}</head><body>{body}<script>{JS}</script></body></html>\n")

import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { Scene } from "../components/Frame";
import { Card, Strip } from "../components/Strip";
import { appearAt } from "../components/Trace";
import { D } from "../data";
import { C, F, clamp, easeInOut, easeOut } from "../theme";

export const Reduce: React.FC = () => {
  const frame = useCurrentFrame();
  const ev = D.reduction.events;
  const dropped = ev.filter((e) => !e.kept).map((e) => e.seq);
  const dropStart = (seq: number) => 110 + dropped.indexOf(seq) * 9;
  const collapse = interpolate(frame, [205, 245], [0, 1], { ...clamp, easing: easeInOut });
  const removed = dropped.filter((s) => frame >= dropStart(s) + 6).length;
  const count = D.reduction.before - removed;
  const arcs = interpolate(frame, [60, 95], [0, 1], { ...clamp, easing: easeOut });
  return (
    <Scene chapter={2} captions={[
      { from: 6, to: 118, text: "A longer run: the agent reads the posting, drafts a letter with an LLM, logs to telemetry, and hits two faults." },
      { from: 122, to: 296, text: "Reduction removes what the failure doesn't need, but never an event that something kept depends on." },
    ]}>
      <Strip title="blind_retry_full · lost response, then 429" events={ev} h={34} gap={3} w={1080} arcs={arcs}
        style={{ left: 0, top: 0 }} nameWidth={300} fontScale={0.82}
        heights={(e) => (e.kept ? 1 : 1 - collapse)}
        arcVisible={(seq) => (ev.find((x) => x.seq === seq)?.kept ? 1 : 1 - collapse)}
        state={(e, i) => {
          const gone = e.kept ? 0 : interpolate(frame, [dropStart(e.seq), dropStart(e.seq) + 10], [0, 1], clamp);
          return { appear: appearAt(frame, 4 + i * 3, 10), dim: gone, strike: gone > 0.5,
            highlight: e.violation && frame > 100 ? "bad" : e.kept && frame > 250 ? "accent" : null };
        }} />
      <div style={{ position: "absolute", left: 1190, top: 0, width: 538, display: "grid", gap: 6 }}>
        <div style={{ fontFamily: F.mono, fontSize: 22, letterSpacing: 3, color: C.muted, textTransform: "uppercase" }}>events</div>
        <div style={{ fontFamily: F.cond, fontWeight: 700, fontSize: 210, lineHeight: 0.95, color: count === D.reduction.after ? C.accent : C.ink,
          fontVariantNumeric: "tabular-nums" }}>{count}</div>
        <div style={{ fontFamily: F.mono, fontSize: 24, color: C.muted }}>of {D.reduction.before} recorded</div>
      </div>
      <Card title="Delta debugging" p={appearAt(frame, 150, 16)} style={{ left: 1190, top: 330, width: 538 }}>
        <div style={{ fontSize: 26, lineHeight: 1.45 }}>
          Same property, same step <span style={{ fontFamily: F.mono, color: C.bad }}>#{D.reduction.anchor}</span>.
          {" "}{D.reduction.tests} candidates tested. The posting and the draft stay: the submissions carry their output.
        </div>
      </Card>
    </Scene>
  );
};

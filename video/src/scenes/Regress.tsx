import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Scene } from "../components/Frame";
import { Tag } from "../components/Trace";
import { D } from "../data";
import { C, F, clamp, easeOut } from "../theme";

const STEP = 7; // frames per recorded event checked

const RegressRow: React.FC<{ i: number; y: number }> = ({ i, y }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const r = D.regress.rows[i];
  const start = 30 + i * 52;
  const enter = interpolate(frame, [start - 14, start], [0, 1], { ...clamp, easing: easeOut });
  const incompatible = r.compatibility === "incompatible";
  const checked = Math.floor(interpolate(frame, [start, start + r.total * STEP], [0, r.total], clamp));
  const reached = frame >= start + (incompatible ? r.matched + 1 : r.total) * STEP;
  const verdict = spring({ frame: frame - (start + r.total * STEP + 10), fps, config: { damping: 14, stiffness: 160 } });
  const fixed = r.verdict === "fixed";
  return (
    <div style={{ position: "absolute", left: 0, top: y, width: 1728, height: 128, display: "grid",
      gridTemplateColumns: "520px 760px 1fr", alignItems: "center", gap: 28, opacity: enter,
      translate: `${(1 - enter) * 40}px 0px`, borderBottom: `1.5px solid ${C.line}` }}>
      <div style={{ display: "grid", gap: 10 }}>
        <div style={{ fontFamily: F.mono, fontWeight: 500, fontSize: 26 }}>{r.label}</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {r.faults.length ? r.faults.map((f) => <Tag key={f} tone="warn" size={15}>{f}</Tag>)
            : <span style={{ fontFamily: F.mono, fontSize: 18, color: C.muted }}>no faults</span>}
        </div>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", gap: 8 }}>
          {Array.from({ length: r.total }, (_, k) => {
            const isDiv = incompatible && k === r.matched;
            const on = k < checked;
            const ok = !isDiv && (k < r.matched || !incompatible);
            return (
              <div key={k} style={{ width: 52, height: 40, borderRadius: 7, boxSizing: "border-box", display: "grid", placeItems: "center",
                fontFamily: F.mono, fontSize: 17, color: on ? C.ink : C.dim,
                border: `2px solid ${on ? (isDiv ? C.bad : ok ? C.good : C.dim) : C.line}`,
                background: on ? (isDiv ? C.badSoft : ok ? C.goodSoft : "transparent") : "transparent" }}>
                #{k + 1}
              </div>
            );
          })}
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 19, color: incompatible ? C.bad : C.good, opacity: reached ? 1 : 0 }}>
          {incompatible
            ? `incompatible from #${r.divergence_seq} · re-recorded under the same faults`
            : "compatible · replayed offline against the new code"}
        </div>
      </div>
      <div style={{ justifySelf: "end", fontFamily: F.mono, fontWeight: 600, fontSize: 26, textTransform: "uppercase",
        letterSpacing: 1.5, padding: "12px 20px", borderRadius: 999, color: fixed ? C.good : C.accent,
        border: `3px solid ${fixed ? C.good : C.accent}`, background: fixed ? C.goodSoft : C.accentSoft,
        opacity: Math.max(0, verdict), scale: `${1.2 - 0.2 * Math.max(0, verdict)}` }}>
        {r.verdict}
      </div>
    </div>
  );
};

export const Regress: React.FC = () => {
  const frame = useCurrentFrame();
  const head = interpolate(frame, [0, 16], [0, 1], { ...clamp, easing: easeOut });
  return (
    <Scene chapter={4} captions={[
      { from: 6, to: 152, text: "Stored failures become regression tests for the fix. A recording the new code still matches replays offline." },
      { from: 156, to: 326, text: "The others say exactly where they stop matching, and are recorded again under the same faults. Verdict: fixed." },
    ]}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 20, opacity: head }}>
        <span style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 46 }}>reprolab regress</span>
        <span style={{ fontFamily: F.mono, fontSize: 24, color: C.muted }}>4 stored recordings → the journaled client</span>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 80, display: "grid", gridTemplateColumns: "520px 760px 1fr", gap: 28,
        fontFamily: F.mono, fontSize: 18, letterSpacing: 2, color: C.dim, textTransform: "uppercase", opacity: head }}>
        <span>recording</span><span>recorded events, checked against the new code</span><span style={{ justifySelf: "end" }}>verdict</span>
      </div>
      <RegressRow i={0} y={118} />
      <RegressRow i={1} y={256} />
      <RegressRow i={2} y={394} />
      <RegressRow i={3} y={532} />
    </Scene>
  );
};

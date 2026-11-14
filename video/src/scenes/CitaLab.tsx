import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Scene } from "../components/Frame";
import { Card, Stamp, Strip } from "../components/Strip";
import { Ev, appearAt, glyph } from "../components/Trace";
import { D } from "../data";
import { C, F, clamp } from "../theme";

const PART_B = 170;
const PART_C = 390;

const Headline: React.FC = () => {
  const frame = useCurrentFrame();
  const out = interpolate(frame, [PART_B - 16, PART_B], [1, 0], clamp);
  const p = appearAt(frame, 6, 18);
  return (
    <div style={{ position: "absolute", left: 0, top: 30, display: "grid", gap: 24, opacity: Math.min(p, out) }}>
      <div style={{ fontFamily: F.mono, fontSize: 24, letterSpacing: 4, color: C.muted, textTransform: "uppercase" }}>
        CitaLab · a public assistant for synthetic healthcare appointments
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 30 }}>
        <span style={{ fontFamily: F.cond, fontWeight: 700, fontSize: 230, lineHeight: 0.9, color: C.bad }}>
          {D.citalab.failures} <span style={{ color: C.ink, fontSize: 120 }}>of {D.citalab.episodes}</span>
        </span>
      </div>
      <div style={{ fontSize: 44, maxWidth: 1300, lineHeight: 1.3, opacity: appearAt(frame, 40, 16) }}>
        requests to <b>move</b> an appointment ended with a <b style={{ color: C.bad }}>new</b> one.
      </div>
      <div style={{ display: "flex", gap: 16, opacity: appearAt(frame, 80, 14) }}>
        {["confirmation before every write", "no third-party changes", "no invented effects"].map((t) => (
          <span key={t} style={{ fontFamily: F.mono, fontSize: 22, color: C.good, border: `2px solid ${C.good}`,
            background: C.goodSoft, borderRadius: 999, padding: "10px 18px" }}>✓ {t}</span>
        ))}
      </div>
    </div>
  );
};

const Compare: React.FC = () => {
  const frame = useCurrentFrame() - PART_B;
  const vis = interpolate(frame, [0, 14, PART_C - PART_B - 16, PART_C - PART_B], [0, 1, 1, 0], clamp);
  if (vis <= 0) return null;
  const pos = D.citalab.divergence.position;
  const rows = 6;
  const diverged = frame > 78;
  const state = (_e: Ev, i: number) => ({
    appear: appearAt(frame, 8 + i * 7, 10),
    same: i < pos,
    highlight: diverged && i === pos ? ("accent" as const) : null,
    dim: diverged && i > pos ? 0.6 : 0,
  });
  const vals = D.citalab.divergence.values;
  const fmt = (v: unknown) => (v === null ? "null" : JSON.stringify(v));
  const answers = D.citalab.answers;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: vis }}>
      <Strip title="Gemini · M5 · moved the appointment" events={D.citalab.m5.slice(0, rows)} h={46} gap={5} w={800}
        arcs={0} state={state} style={{ left: 0, top: 0 }} nameWidth={250} fontScale={0.82} showSummary={false} />
      <Strip title="Gemini · H · booked a new one" events={D.citalab.h.slice(0, rows)} h={46} gap={5} w={800}
        arcs={0} state={state} style={{ left: 900, top: 0 }} nameWidth={250} fontScale={0.82} showSummary={false} />
      <div style={{ position: "absolute", left: 832, top: 82 + 14, width: 64, display: "grid", gap: 5 }}>
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} style={{ height: 46, display: "grid", placeItems: "center", fontFamily: F.mono, fontWeight: 600,
            fontSize: 30, color: i < pos ? C.good : i === pos ? C.accent : C.dim, opacity: appearAt(frame, 8 + i * 7, 10) }}>
            {i < pos ? "=" : i === pos && diverged ? "≠" : ""}
          </div>
        ))}
      </div>
      <Card title={`first divergence · position ${pos + 1} · same request, different answer`} p={appearAt(frame, 88, 14)}
        tone={C.accent} style={{ left: 0, top: 440, width: 1728, padding: "18px 24px" }}>
        <div style={{ display: "flex", gap: 60, alignItems: "center", flexWrap: "wrap" }}>
          {vals.map(([path, a, b]) => (
            <div key={path} style={{ fontFamily: F.mono, fontSize: 26 }}>
              <span style={{ color: C.muted }}>{path.replace("/outcome/ok/", "")}: </span>
              <span style={{ color: C.good }}>{fmt(a)}</span>
              <span style={{ color: C.muted }}> vs </span>
              <span style={{ color: C.bad }}>{fmt(b)}</span>
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto", opacity: appearAt(frame, 104, 14) }}>
            <span style={{ fontFamily: F.mono, fontSize: 22, color: C.muted, marginRight: 8 }}>
              {D.citalab.identical_requests} byte-identical requests →
            </span>
            {answers.map((a, k) => (
              <span key={k} style={{ fontFamily: F.mono, fontSize: 20, padding: "8px 12px", borderRadius: 8,
                border: `2px solid ${a === "book" ? C.bad : C.good}`, background: a === "book" ? C.badSoft : C.goodSoft }}>{a}</span>
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
};

const Chain: React.FC = () => {
  const frame = useCurrentFrame() - PART_C;
  const { fps } = useVideoConfig();
  if (frame < 0) return null;
  const kept = D.citalab.reduction.filter((e) => e.kept);
  const stamp = spring({ frame: frame - 92, fps, config: { damping: 14, stiffness: 150 } });
  const label = (e: Ev) => e.intent ? `${e.name} · ${e.intent}` : e.operation ? `${e.name} · ${e.operation}` : e.name;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 18, opacity: appearAt(frame, 0, 12) }}>
        <span style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 46 }}>The failure, reduced to its causal chain</span>
        <span style={{ fontFamily: F.mono, fontSize: 26, color: C.accent }}>{D.citalab.reduced_before} → {D.citalab.reduced_after} events</span>
      </div>
      <div style={{ position: "absolute", left: 0, top: 96, width: 1728, display: "flex", flexWrap: "wrap", gap: "22px 0px" }}>
        {kept.map((e, i) => {
          const p = appearAt(frame, 10 + i * 7, 10);
          const bad = (e.intent === "book") || (e.operation === "book");
          return (
            <div key={e.seq} style={{ display: "flex", alignItems: "center", opacity: p, translate: `${(1 - p) * 20}px 0px` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderRadius: 12, background: C.surface,
                border: e.reconstructed ? `2px dashed ${C.muted}` : `2px solid ${bad ? C.bad : C.line}`,
                boxShadow: bad ? `0 0 24px ${C.badSoft}` : undefined }}>
                <span style={{ fontFamily: F.mono, fontWeight: 600, fontSize: 20, color: C.muted }}>{glyph(e)}</span>
                <span style={{ fontFamily: F.mono, fontSize: 22, color: bad ? C.bad : C.ink }}>{label(e)}</span>
              </div>
              {i < kept.length - 1 ? <span style={{ fontFamily: F.mono, fontSize: 28, color: C.accent, margin: "0 14px" }}>→</span> : null}
            </div>
          );
        })}
      </div>
      <Stamp tone="good" p={Math.max(0, stamp)} style={{ left: 260, top: 400 }}>
        evaluated code re-executed on the recorded answers · {D.citalab.reexecuted ?? "?"} / {D.citalab.episodes} identical
      </Stamp>
    </div>
  );
};

export const CitaLab: React.FC = () => (
  <Scene chapter={5} captions={[
    { from: 6, to: PART_B - 4, text: "A real case. In 9 of 12 episodes, an assistant asked to move an appointment booked a new one, and every safety check passed." },
    { from: PART_B + 4, to: PART_C - 4, text: "Traces rebuilt from its logs, each event citing its source. Two episodes match exactly until the model gets the same request and answers differently." },
    { from: PART_C + 4, to: 536, text: "Re-running the evaluated code on the recorded answers reproduces all 12 episodes. The cause is the model's interpretation, not the code." },
  ]}>
    <Headline />
    <Compare />
    <Chain />
  </Scene>
);

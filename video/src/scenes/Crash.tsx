import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Scene } from "../components/Frame";
import { hatch } from "../components/Trace";
import { C, F, clamp, easeInOut, easeOut } from "../theme";

type Step = { at: number; text: string; tone?: string };

const Lane: React.FC<{ y: number; name: string; verdict: "bad" | "good"; journal: boolean; steps: Step[];
  apps: number; appsAt: number }> = ({ y, name, verdict, journal, steps, apps, appsAt }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const crash = interpolate(frame, [52, 60], [0, 1], clamp);
  const restart = interpolate(frame, [86, 100], [0, 1], { ...clamp, easing: easeOut });
  const broken = crash > 0 && restart < 1;
  const shake = broken ? Math.sin(frame * 2.2) * 6 * (1 - restart) : 0;
  const memory = frame < 52 ? 1 : 0; // the in-process memory is gone after the crash
  const tone = verdict === "bad" ? C.bad : C.good;
  const result = spring({ frame: frame - appsAt, fps, config: { damping: 15 } });
  const packet = (from: number, to: number, label: string, back = false) => {
    const p = interpolate(frame, [from, to], [0, 1], { ...clamp, easing: easeInOut });
    if (p <= 0 || p >= 1) return null;
    const x = back ? 1060 - p * 450 : 610 + p * 450;
    return (
      <div style={{ position: "absolute", left: x, top: 84, translate: "-50% -50%", fontFamily: F.mono, fontSize: 20,
        padding: "8px 14px", borderRadius: 8, border: `2px solid ${C.accent}`, background: C.accentSoft, whiteSpace: "nowrap" }}>
        {label}
      </div>
    );
  };
  return (
    <div style={{ position: "absolute", left: 0, top: y, width: 1728, height: 300 }}>
      <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 36, marginBottom: 10 }}>{name}</div>
      {/* worker */}
      <div style={{ position: "absolute", left: 0, top: 54, width: 560, height: 220, borderRadius: 16, background: C.surface,
        border: `2px solid ${broken ? C.warn : C.line}`, translate: `${shake}px 0px`, padding: 22, boxSizing: "border-box",
        display: "grid", gap: 10, alignContent: "start", ...(broken ? hatch(frame, C.warnSoft, 12) : {}) }}>
        <div style={{ fontFamily: F.mono, fontSize: 19, color: C.muted, textTransform: "uppercase", letterSpacing: 2 }}>
          worker {frame >= 100 ? "· restarted" : ""}
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ fontFamily: F.mono, fontSize: 20, color: C.muted, width: 120 }}>memory</span>
          <span style={{ fontFamily: F.mono, fontSize: 20, padding: "6px 12px", borderRadius: 6, border: `1.5px solid ${C.line}`,
            opacity: memory ? 1 : 0.35 }}>{memory ? "submitting job-42" : "empty"}</span>
        </div>
        {journal ? (
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span style={{ fontFamily: F.mono, fontSize: 20, color: C.muted, width: 120 }}>journal</span>
            <span style={{ fontFamily: F.mono, fontSize: 20, padding: "6px 12px", borderRadius: 6, border: `1.5px solid ${C.accent}`,
              background: frame > 30 ? C.accentSoft : "transparent", color: frame > 30 ? C.ink : C.dim }}>
              {frame > 160 ? "done" : frame > 30 ? "pending · job-42" : "—"}
            </span>
          </div>
        ) : null}
        {broken ? (
          <div style={{ fontFamily: F.mono, fontWeight: 600, fontSize: 22, color: C.warn }}>crash after submit (simulated)</div>
        ) : null}
      </div>
      {/* steps */}
      <div style={{ position: "absolute", left: 600, top: 120, width: 470, display: "grid", gap: 8 }}>
        {steps.map((s) => (
          <div key={s.at} style={{ fontFamily: F.mono, fontSize: 21, color: s.tone ?? C.ink,
            opacity: interpolate(frame, [s.at, s.at + 10], [0, 1], clamp) }}>{s.text}</div>
        ))}
      </div>
      {packet(14, 44, "submit #1")}
      {journal ? packet(112, 140, "find job-42") : packet(112, 140, "submit #2")}
      {/* portal */}
      <div style={{ position: "absolute", left: 1100, top: 54, width: 628, height: 220, borderRadius: 16, background: C.surface,
        border: `2px solid ${frame > appsAt ? tone : C.line}`, padding: 22, boxSizing: "border-box", display: "grid", alignContent: "start", gap: 8 }}>
        <div style={{ fontFamily: F.mono, fontSize: 19, color: C.muted, textTransform: "uppercase", letterSpacing: 2 }}>portal</div>
        <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 56, color: frame > appsAt ? tone : C.ink }}>
          {frame < 44 ? 0 : frame > appsAt ? apps : 1} application{(frame > appsAt ? apps : 1) === 1 ? "" : "s"}
        </div>
        <div style={{ fontFamily: F.mono, fontWeight: 600, fontSize: 24, color: tone, opacity: Math.max(0, result),
          scale: `${0.9 + 0.1 * Math.max(0, result)}` }}>
          {verdict === "bad" ? "✗ no blind resubmit violated" : "✓ property holds"}
        </div>
      </div>
    </div>
  );
};

export const Crash: React.FC = () => (
  <Scene chapter={3} captions={[
    { from: 6, to: 132, text: "After the crash, the restarted worker has lost its memory of the uncertain submission, so it sends it again." },
    { from: 136, to: 266, text: "The fixed client writes “pending” to a durable journal first, and checks the portal after a restart." },
  ]}>
    <Lane y={0} name="reconciling · correct within one process" verdict="bad" journal={false} apps={2} appsAt={146}
      steps={[{ at: 100, text: "restart: nothing to reconcile" }, { at: 112, text: "→ submits again", tone: C.bad }]} />
    <Lane y={340} name="journaled · the fix" verdict="good" journal apps={1} appsAt={156}
      steps={[{ at: 100, text: "restart: journal says pending" }, { at: 112, text: "→ looks it up first" },
        { at: 146, text: "← found #1 · nothing to resend", tone: C.good }]} />
  </Scene>
);

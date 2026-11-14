import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { Scene } from "../components/Frame";
import { hatch } from "../components/Trace";
import { C, F, clamp, easeInOut, easeOut } from "../theme";

const Box: React.FC<{ x: number; title: string; children?: React.ReactNode; tone?: string }> = ({ x, title, children, tone }) => (
  <div style={{ position: "absolute", left: x, top: 110, width: 430, height: 420, borderRadius: 18, background: C.surface,
    border: `2px solid ${tone ?? C.line}`, padding: 34, boxSizing: "border-box", display: "grid", alignContent: "start", gap: 22 }}>
    <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 52 }}>{title}</div>
    {children}
  </div>
);

const Packet: React.FC<{ label: string; x: number; y: number; opacity: number; lost?: number }> = ({ label, x, y, opacity, lost = 0 }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: x, top: y, translate: "-50% -50%", opacity,
      fontFamily: F.mono, fontSize: 24, padding: "14px 20px", borderRadius: 10, whiteSpace: "nowrap",
      background: lost > 0 ? undefined : C.accentSoft, border: `2px solid ${lost > 0 ? C.warn : C.accent}`,
      color: C.ink, scale: `${1 - lost * 0.15}`, ...(lost > 0 ? hatch(frame, C.warnSoft, 10) : {}) }}>
      {label}
    </div>
  );
};

export const Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const L = 230, R = 1240, laneA = 260, laneB = 400; // agent box right edge ≈ 560, portal box left ≈ 1240
  const p1 = interpolate(frame, [12, 52], [0, 1], { ...clamp, easing: easeInOut });
  const stored1 = interpolate(frame, [50, 62], [0, 1], { ...clamp, easing: easeOut });
  const p2 = interpolate(frame, [66, 100], [0, 1], { ...clamp, easing: easeInOut });
  const lost = interpolate(frame, [92, 104], [0, 1], clamp);
  const retry = interpolate(frame, [118, 132], [0, 1], { ...clamp, easing: easeOut });
  const p3 = interpolate(frame, [134, 172], [0, 1], { ...clamp, easing: easeInOut });
  const stored2 = interpolate(frame, [170, 184], [0, 1], { ...clamp, easing: easeOut });
  const startX = 600, endX = 1200;
  return (
    <Scene captions={[
      { from: 6, to: 118, text: "An agent submits a job application. The portal stores it, but the response never arrives." },
      { from: 122, to: 236, text: "The agent can't tell that it worked, so it tries again. Now the portal holds two applications." },
    ]}>
      <div style={{ position: "absolute", left: 0, top: 0, fontFamily: F.mono, fontSize: 24, letterSpacing: 4, color: C.muted,
        textTransform: "uppercase" }}>The failure nobody sees in the happy path</div>
      <Box x={L - 100} title="Agent">
        <div style={{ fontFamily: F.mono, fontSize: 24, color: C.muted }}>submit(application)</div>
        <div style={{ fontFamily: F.mono, fontSize: 26, color: C.warn, opacity: retry }}>no answer… retry</div>
      </Box>
      <Box x={R} title="Job portal" tone={stored2 > 0.5 ? C.bad : undefined}>
        <div style={{ fontFamily: F.mono, fontSize: 24, color: C.good, opacity: stored1 }}>✓ stored application #1</div>
        <div style={{ fontFamily: F.mono, fontSize: 24, color: C.bad, opacity: stored2 }}>✓ stored application #2</div>
        <div style={{ marginTop: 18, fontFamily: F.cond, fontWeight: 600, fontSize: 40, opacity: stored1,
          color: stored2 > 0.5 ? C.bad : C.ink }}>
          applications: {stored2 > 0.5 ? 2 : 1}
        </div>
      </Box>
      {/* lanes */}
      <div style={{ position: "absolute", left: startX - 40, width: endX - startX + 80, top: laneA, borderTop: `2px dashed ${C.line}` }} />
      <div style={{ position: "absolute", left: startX - 40, width: endX - startX + 80, top: laneB, borderTop: `2px dashed ${C.line}` }} />
      <Packet label="POST /applications" x={startX + (endX - startX) * p1} y={laneA} opacity={p1 > 0 && p1 < 1 ? 1 : 0} />
      <Packet label="201 created" x={endX - (endX - startX) * 0.55 * p2} y={laneB} opacity={p2 > 0 ? 1 - lost * 0.25 : 0} lost={lost} />
      <div style={{ position: "absolute", left: endX - (endX - startX) * 0.55, top: laneB + 46, translate: "-50% 0",
        fontFamily: F.mono, fontSize: 24, color: C.warn, opacity: lost }}>response lost (simulated)</div>
      <Packet label="POST /applications" x={startX + (endX - startX) * p3} y={laneA} opacity={p3 > 0 && p3 < 1 ? 1 : 0} />
    </Scene>
  );
};

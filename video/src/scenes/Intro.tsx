import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Captions } from "../components/Frame";
import { hatch } from "../components/Trace";
import { C, F, clamp, easeOut } from "../theme";

// A strip of trace ticks scrolls past; one tick is a simulated fault, one a violation.
const TICKS = Array.from({ length: 34 }, (_, i) => i);

export const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const wipe = interpolate(frame, [8, 46], [100, 0], { ...clamp, easing: easeOut });
  const tag = interpolate(frame, [40, 70], [0, 1], { ...clamp, easing: easeOut });
  const tape = interpolate(frame, [0, 150], [0, -420]);
  return (
    <AbsoluteFill style={{ background: C.ground, overflow: "hidden", color: C.ink, fontFamily: F.sans }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.line} 1px, transparent 1px)`, backgroundSize: "32px 32px",
        opacity: 0.3 }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 640, height: 64, display: "flex", gap: 22,
        translate: `${tape}px 0px`, opacity: interpolate(frame, [0, 20], [0, 1], clamp) }}>
        {TICKS.map((i) => {
          const fault = i === 13;
          const bad = i === 15;
          return (
            <div key={i} style={{ width: 48, height: 48, borderRadius: 9, flexShrink: 0, background: C.surface,
              border: `2px solid ${fault ? C.warn : bad ? C.bad : C.line}`,
              boxShadow: bad ? `0 0 28px ${C.badSoft}` : undefined,
              ...(fault ? hatch(frame, C.warnSoft, 9) : {}) }} />
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 120, top: 250, display: "grid", gap: 26 }}>
        <div style={{ fontFamily: F.mono, fontSize: 26, letterSpacing: 6, color: C.muted, textTransform: "uppercase",
          opacity: tag }}>A flight recorder for agent workflows</div>
        <div style={{ fontFamily: F.cond, fontWeight: 700, fontSize: 210, lineHeight: 0.9, letterSpacing: -4, color: C.ink,
          clipPath: `inset(0 ${wipe}% 0 0)` }}>ReproLab</div>
        <div style={{ fontFamily: F.sans, fontSize: 46, color: C.muted, opacity: tag, translate: `0px ${(1 - tag) * 20}px` }}>
          Record, replay and reduce the failures of agents and automations.
        </div>
      </div>
      <Captions captions={[{ from: 72, to: 150, text: "Every trace, number and verdict in this video comes from a real run of the code." }]} />
    </AbsoluteFill>
  );
};

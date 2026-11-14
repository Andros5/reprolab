import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Captions } from "../components/Frame";
import { C, F, clamp, easeOut } from "../theme";

const COMMANDS = ["record", "replay", "reduce", "diff", "explore", "regress", "html"];

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const wipe = interpolate(frame, [4, 36], [100, 0], { ...clamp, easing: easeOut });
  return (
    <AbsoluteFill style={{ background: C.ground, overflow: "hidden", color: C.ink, fontFamily: F.sans }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.line} 1px, transparent 1px)`, backgroundSize: "32px 32px", opacity: 0.3 }} />
      <div style={{ position: "absolute", left: 120, top: 210, display: "grid", gap: 34 }}>
        <div style={{ fontFamily: F.cond, fontWeight: 700, fontSize: 190, lineHeight: 0.9, letterSpacing: -4,
          clipPath: `inset(0 ${wipe}% 0 0)` }}>ReproLab</div>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          {COMMANDS.map((c, i) => {
            const p = interpolate(frame, [30 + i * 5, 42 + i * 5], [0, 1], { ...clamp, easing: easeOut });
            return (
              <span key={c} style={{ fontFamily: F.mono, fontSize: 30, padding: "12px 20px", borderRadius: 10,
                border: `2px solid ${C.line}`, background: C.surface, opacity: p, translate: `0px ${(1 - p) * 16}px` }}>
                reprolab {c}
              </span>
            );
          })}
        </div>
        <div style={{ fontSize: 40, color: C.muted, opacity: interpolate(frame, [72, 90], [0, 1], clamp) }}>
          Python standard library and SQLite. No external services.
        </div>
      </div>
      {/* CC BY 4.0 credit for the music (trimmed, faded and levelled: see video/sound/prepare.py) */}
      <div style={{ position: "absolute", left: 120, top: 790, fontFamily: F.mono, fontSize: 22, color: C.muted,
        opacity: interpolate(frame, [80, 98], [0, 1], clamp) }}>
        Music: “Ethereal” by Amarent · CC BY 4.0 · freemusicarchive.org · trimmed, faded and levelled
      </div>
      <Captions captions={[{ from: 60, to: 178, text: "Replay reuses recorded answers. Injected faults are simulations. A clean exploration is not a proof of correctness." }]} />
    </AbsoluteFill>
  );
};

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Scene } from "../components/Frame";
import { Card, Stamp, Strip } from "../components/Strip";
import { appearAt } from "../components/Trace";
import { D } from "../data";
import { C, F, clamp, easeInOut } from "../theme";

export const Replay: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ev = D.portal.events;
  const rowH = 84, gap = 10, top = 20 + 96; // strip header ≈ 96px
  const head = interpolate(frame, [36, 136], [0, ev.length], { ...clamp, easing: easeInOut });
  const done = spring({ frame: frame - 146, fps, config: { damping: 15, stiffness: 150 } });
  const plug = appearAt(frame, 8, 14);
  return (
    <Scene chapter={1} captions={[
      { from: 6, to: 104, text: "Replay runs the same code with the network switched off. Every call is answered from the recording." },
      { from: 108, to: 206, text: "Same trace, same verdict. Replay reuses recorded answers; it doesn't claim a service would answer the same way twice." },
    ]}>
      <Strip title="blind_retry · replayed offline" meta="network disabled · answers served from the recording" events={ev} h={rowH}
        w={1060} gap={gap} arcs={1} style={{ left: 0, top: 20 }} nameWidth={250}
        state={(e, i) => ({ appear: 1, highlight: e.violation && head > i + 0.5 ? "bad" : null,
          check: interpolate(head, [i + 0.4, i + 1], [0, 1], clamp) })} />
      {/* playhead */}
      <div style={{ position: "absolute", left: 14, width: 1080, top: top + 14 + head * (rowH + gap) - 3, height: 3,
        background: C.accent, boxShadow: `0 0 18px ${C.accent}`, opacity: frame > 30 && frame < 140 ? 1 : 0 }} />
      <Card title="Network" p={plug} tone={C.accent} style={{ left: 1150, top: 20, width: 578 }}>
        <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 52 }}>off</div>
        <div style={{ fontSize: 24, color: C.muted }}>Any socket connection raises an error during replay.</div>
      </Card>
      <Card title="Result" p={appearAt(frame, 140, 14)} tone={C.good} style={{ left: 1150, top: 300, width: 578 }}>
        <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 52, color: C.good }}>
          {D.portal.replay_identical ? "identical" : "diverged"}
        </div>
        <div style={{ fontSize: 24, color: C.muted }}>4 of 4 events reproduced · same violation at #4</div>
      </Card>
      <Stamp tone="good" p={Math.max(0, done)} style={{ left: 40, top: 566 }}>0 network calls</Stamp>
    </Scene>
  );
};

import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Scene } from "../components/Frame";
import { Card, Stamp, Strip } from "../components/Strip";
import { appearAt } from "../components/Trace";
import { D } from "../data";
import { C, F, clamp, easeOut } from "../theme";

export const Record: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ev = D.portal.events;
  const arcs = interpolate(frame, [128, 160], [0, 1], { ...clamp, easing: easeOut });
  const violated = frame >= 168;
  const stamp = spring({ frame: frame - 176, fps, config: { damping: 14, stiffness: 160 } });
  return (
    <Scene chapter={0} captions={[
      { from: 6, to: 140, text: "ReproLab records every call at the workflow's boundaries. The lost response is a simulated fault, and is marked as one." },
      { from: 144, to: 296, text: "A business property reads only the trace: never resubmit while the outcome is uncertain. Event #4 breaks it." },
    ]}>
      <Strip title="blind_retry · recorded trace" meta="calls and random tokens go through the Session" events={ev} h={84}
        w={1060} gap={10} arcs={arcs} style={{ left: 0, top: 20 }} nameWidth={250}
        state={(e, i) => ({ appear: appearAt(frame, 18 + i * 26, 14),
          highlight: violated && e.violation ? "bad" : null })} />
      <Card title="The property" p={appearAt(frame, 140, 16)} style={{ left: 1150, top: 20, width: 578 }}>
        <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 40, lineHeight: 1.15 }}>No blind resubmit</div>
        <div style={{ fontSize: 26, color: C.muted, lineHeight: 1.4 }}>
          After an outcome with unknown effect, look the application up before submitting again.
        </div>
      </Card>
      <Card title="The oracle · real portal state" p={appearAt(frame, 205, 16)} tone={C.bad}
        style={{ left: 1150, top: 330, width: 578 }}>
        <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 64, color: C.bad }}>{D.portal.applications} applications</div>
        <div style={{ fontSize: 24, color: C.muted }}>for one job. Read separately, never replayed.</div>
      </Card>
      <Stamp tone="bad" p={Math.max(0, stamp)} style={{ left: 40, top: 566 }}>violated at #4 · no blind resubmit</Stamp>
    </Scene>
  );
};

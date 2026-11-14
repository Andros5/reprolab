import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Scene } from "../components/Frame";
import { Card } from "../components/Strip";
import { Tag, hatch } from "../components/Trace";
import { D } from "../data";
import { C, F, clamp, easeOut } from "../theme";

const COLS = 20;
const CELL = 36;
const GAP = 7;

export const Explore: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ex = D.explore;
  const total = ex.outcomes.length;
  const ran = Math.floor(interpolate(frame, [24, 264], [0, total], { ...clamp, easing: easeOut }));
  const singles = ex.explored["1"];
  const singleDone = Math.min(ran, singles);
  const pairDone = Math.max(0, ran - singles);
  const prop = ex.findings.find((f) => f.category === "property")!;
  const counts = { property: 0, unhandled: 0, "oracle-only": 0, clean: 0 } as Record<string, number>;
  ex.outcomes.slice(0, ran).forEach((o) => { counts[o] += 1; });
  const pop = spring({ frame: frame - 285, fps, config: { damping: 16, stiffness: 140 } });
  const firstProp = ex.outcomes.indexOf("property");
  const ring = interpolate(frame, [24 + (firstProp / total) * 240, 24 + (firstProp / total) * 240 + 26], [0, 1], clamp);
  const color = (o: string) => ({ property: C.bad, unhandled: C.warn, "oracle-only": C.accent, clean: C.dim })[o] ?? C.dim;
  return (
    <Scene chapter={3} captions={[
      { from: 6, to: 150, text: "Which faults break a client that reconciles before retrying? The explorer runs 200 seeded fault schedules against a real local portal." },
      { from: 154, to: 282, text: "Every single fault first, then pairs on the paths each fault opened, then a seeded sample." },
      { from: 286, to: 416, text: "Found: one crash, right after the submission. Minimal counterexample: 1 fault, 4 events." },
    ]}>
      <div style={{ position: "absolute", left: 0, top: 0, display: "grid", gap: 18 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
          <span style={{ fontFamily: F.cond, fontWeight: 700, fontSize: 64, fontVariantNumeric: "tabular-nums" }}>{ran}</span>
          <span style={{ fontFamily: F.mono, fontSize: 24, color: C.muted }}>/ {total} fault schedules · seed 0</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${COLS}, ${CELL}px)`, gap: GAP }}>
          {ex.outcomes.map((o, i) => {
            const on = i < ran;
            const c = color(o);
            return (
              <div key={i} style={{ width: CELL, height: CELL, borderRadius: 7, boxSizing: "border-box",
                background: !on ? "transparent" : o === "clean" ? C.surface2 : o === "property" ? C.badSoft : C.surface,
                border: `2px solid ${on ? c : C.line}`, opacity: on ? 1 : 0.45,
                ...(on && o === "unhandled" ? hatch(frame, C.warnSoft, 8) : {}),
                boxShadow: i === firstProp ? `0 0 0 ${ring * 8}px rgba(255,125,112,${0.5 * (1 - ring) + 0.15})` : undefined }} />
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 22, fontFamily: F.mono, fontSize: 20, color: C.muted }}>
          {[["property violated", C.bad, counts.property], ["unhandled exception", C.warn, counts.unhandled],
            ["oracle only", C.accent, counts["oracle-only"]], ["clean", C.dim, counts.clean]].map(([label, c, n]) => (
            <span key={label as string} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 16, height: 16, borderRadius: 4, border: `2px solid ${c}` }} />
              {label} <b style={{ color: C.ink, fontVariantNumeric: "tabular-nums" }}>{n}</b>
            </span>
          ))}
        </div>
      </div>
      <div style={{ position: "absolute", left: 940, top: 0, width: 788, display: "grid", gap: 22 }}>
        {[["single faults", singleDone, ex.space["1"]], ["pairs of faults", pairDone, ex.space["2"]]].map(([label, done, space]) => (
          <div key={label as string} style={{ display: "grid", gap: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontFamily: F.mono, fontSize: 22 }}>
              <span>{label}</span><span style={{ color: C.muted, fontVariantNumeric: "tabular-nums" }}>{done} / {space}</span>
            </div>
            <div style={{ height: 16, borderRadius: 8, background: C.surface2, border: `1.5px solid ${C.line}`, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${(100 * (done as number)) / (space as number)}%`, background: C.accent }} />
            </div>
          </div>
        ))}
        <div style={{ fontFamily: F.mono, fontSize: 19, color: C.muted, lineHeight: 1.5 }}>
          Call sites reached: {ex.sites.join(" · ")}
        </div>
      </div>
      <Card title="Counterexample · minimal" p={Math.max(0, pop)} tone={C.bad} style={{ left: 940, top: 290, width: 788 }}>
        <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 38 }}>{prop.signature}</div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {prop.minimal.map((m) => <Tag key={m} tone="warn" size={20}>{m}</Tag>)}
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 22, color: C.muted }}>
          first found at run {prop.first_run} · trace {prop.trace} → {prop.reduced} events · {prop.hits} runs hit it
        </div>
      </Card>
    </Scene>
  );
};

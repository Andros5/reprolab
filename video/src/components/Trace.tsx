import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, F, clamp, easeOut } from "../theme";

export type Ev = {
  seq: number; type: string; kind: string; name: string; summary: string; fault: string | null;
  deps: number[]; violation: boolean; reconstructed: boolean; kept?: boolean; intent?: string | null;
  operation?: string | null;
};

const GLYPH: Record<string, string> = { llm: "L", http: "H", tool: "T", user: "U" };
export const glyph = (e: Ev) => GLYPH[e.kind] ?? (e.type === "clock" ? "◷" : e.type === "random" ? "✱" : "·");

/** Moving diagonal stripes: the mark of a simulated fault. */
export const hatch = (frame: number, color = C.warnSoft, gap = 8) => ({
  backgroundImage: `repeating-linear-gradient(135deg, ${color} 0 ${gap / 2}px, transparent ${gap / 2}px ${gap}px)`,
  backgroundSize: `${gap * 2}px ${gap * 2}px`,
  backgroundPosition: `${(frame * 0.6) % (gap * 2)}px 0px`,
});

export const Tag: React.FC<{ tone: "warn" | "bad" | "good" | "info" | "muted"; children: React.ReactNode;
  size?: number; style?: React.CSSProperties }> = ({ tone, children, size = 17, style }) => {
  const frame = useCurrentFrame();
  const color = { warn: C.warn, bad: C.bad, good: C.good, info: C.accent, muted: C.muted }[tone];
  const soft = { warn: C.warnSoft, bad: C.badSoft, good: C.goodSoft, info: C.accentSoft, muted: "transparent" }[tone];
  return (
    <span style={{ fontFamily: F.mono, fontWeight: 600, fontSize: size, letterSpacing: 1, textTransform: "uppercase",
      color, border: `1.5px solid ${color}`, borderRadius: 6, padding: `${size * 0.32}px ${size * 0.55}px`,
      whiteSpace: "nowrap", background: tone === "warn" ? undefined : soft,
      ...(tone === "warn" ? hatch(frame) : {}), ...style }}>
      {children}
    </span>
  );
};

export type RowState = {
  appear: number; // 0..1
  dim?: number; // 0..1, fades the row (dropped by a reduction)
  strike?: boolean;
  highlight?: "bad" | "accent" | "good" | null;
  same?: boolean;
  check?: number; // 0..1, a reproduced tick
};

export const Row: React.FC<{ e: Ev; h: number; w: number; state: RowState; showSummary?: boolean;
  nameWidth?: number; fontScale?: number }> = ({ e, h, w, state, showSummary = true, nameWidth = 300, fontScale = 1 }) => {
  const frame = useCurrentFrame();
  const fs = (n: number) => n * fontScale;
  const hl = state.highlight;
  const bg = hl === "bad" ? C.badSoft : hl === "accent" ? C.accentSoft : hl === "good" ? C.goodSoft
    : state.same ? "rgba(255,255,255,0.025)" : "transparent";
  return (
    <div style={{ height: h, width: w, display: "flex", alignItems: "center", gap: 16, paddingLeft: 90, paddingRight: 18,
      background: bg, borderRadius: 8, opacity: state.appear * (1 - (state.dim ?? 0) * 0.78),
      translate: `${(1 - state.appear) * 60}px 0px`, position: "relative", boxSizing: "border-box",
      boxShadow: hl === "bad" ? `inset 4px 0 0 ${C.bad}` : hl === "accent" ? `inset 4px 0 0 ${C.accent}` : undefined }}>
      <span style={{ fontFamily: F.mono, fontSize: fs(18), color: C.dim, width: 44, textAlign: "right" }}>#{e.seq}</span>
      <span style={{ width: fs(36), height: fs(36), borderRadius: 7, display: "grid", placeItems: "center", flexShrink: 0,
        fontFamily: F.mono, fontWeight: 600, fontSize: fs(18), color: e.violation && hl === "bad" ? C.bad : C.ink,
        border: e.reconstructed ? `2px dashed ${C.muted}` : `1.5px solid ${e.fault ? C.warn : e.violation && hl === "bad" ? C.bad : C.line}`,
        background: C.surface, ...(e.fault ? hatch(frame, C.warnSoft, 7) : {}) }}>
        {glyph(e)}
      </span>
      <span style={{ fontFamily: F.mono, fontWeight: 500, fontSize: fs(22), width: nameWidth, flexShrink: 0, overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap", textDecoration: state.strike ? "line-through" : undefined,
        color: C.ink }}>{e.name}</span>
      {showSummary ? (
        <span style={{ fontFamily: F.mono, fontSize: fs(18), color: C.muted, flex: 1, minWidth: 0, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.summary}</span>
      ) : <span style={{ flex: 1 }} />}
      <span style={{ display: "flex", gap: 8 }}>
        {e.fault ? <Tag tone="warn" size={fs(15)}>{e.fault.replace("_", " ")}</Tag> : null}
        {e.reconstructed ? <Tag tone="muted" size={fs(15)} style={{ borderStyle: "dashed" }}>derived</Tag> : null}
        {e.violation && hl === "bad" ? <Tag tone="bad" size={fs(15)}>violation</Tag> : null}
        {state.check !== undefined && state.check > 0 ? (
          <span style={{ fontFamily: F.mono, fontSize: fs(20), color: C.good, opacity: state.check,
            scale: `${0.6 + 0.4 * state.check}` }}>✓ same</span>
        ) : null}
      </span>
    </div>
  );
};

/** Dependency arcs in the left gutter, drawn progressively. */
export const Arcs: React.FC<{ events: Ev[]; positions: Record<number, number>; h: number; progress: number;
  visible?: (seq: number) => number; x?: number }> = ({ events, positions, h, progress, visible, x = 70 }) => {
  const paths: React.ReactNode[] = [];
  for (const e of events) {
    for (const d of e.deps) {
      if (!(d in positions) || !(e.seq in positions)) continue;
      const y1 = positions[d] + h / 2;
      const y2 = positions[e.seq] + h / 2;
      const reach = Math.min(62, 14 + ((y2 - y1) / h) * 9);
      const op = visible ? Math.min(visible(d), visible(e.seq)) : 1;
      paths.push(
        <path key={`${d}-${e.seq}`} d={`M${x},${y1} C${x - reach},${y1} ${x - reach},${y2} ${x},${y2}`} fill="none"
          stroke={C.accent} strokeWidth={2.4} strokeOpacity={0.75 * op} pathLength={1} strokeDasharray="1 1"
          strokeDashoffset={1 - progress} strokeLinecap="round" />,
      );
    }
  }
  return (
    <svg style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none" }} width={1} height={1}>
      {paths}
    </svg>
  );
};

export const appearAt = (frame: number, start: number, dur = 12) =>
  interpolate(frame, [start, start + dur], [0, 1], { ...clamp, easing: easeOut });

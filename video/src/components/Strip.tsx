import React from "react";
import { Arcs, Ev, Row, RowState } from "./Trace";
import { C, F } from "../theme";

/** A recorder strip: a titled panel of event rows on a fixed grid, with dependency arcs.
 *  ``heights`` lets a row collapse (a reduction); arcs follow the rows. */
export const Strip: React.FC<{
  title: string; meta?: string; events: Ev[]; h: number; w: number; gap?: number;
  state: (e: Ev, i: number) => RowState; arcs: number; heights?: (e: Ev, i: number) => number;
  arcVisible?: (seq: number) => number; style?: React.CSSProperties; nameWidth?: number; fontScale?: number;
  showSummary?: boolean; titleOpacity?: number; children?: React.ReactNode;
}> = ({ title, meta, events, h, w, gap = 6, state, arcs, heights, arcVisible, style, nameWidth, fontScale, showSummary,
  titleOpacity = 1, children }) => {
  const positions: Record<number, number> = {};
  let y = 0;
  const ys = events.map((e, i) => {
    const rowH = heights ? heights(e, i) : 1;
    positions[e.seq] = y;
    const at = y;
    y += (h + gap) * rowH;
    return at;
  });
  return (
    <div style={{ position: "absolute", background: C.surface, border: `1.5px solid ${C.line}`, borderRadius: 16,
      width: w + 28, boxSizing: "border-box", ...style }}>
      <div style={{ padding: "18px 22px", borderBottom: `1.5px solid ${C.line}`, display: "grid", gap: 6, opacity: titleOpacity }}>
        <div style={{ fontFamily: F.cond, fontWeight: 600, fontSize: 30 }}>{title}</div>
        {meta ? <div style={{ fontFamily: F.mono, fontSize: 18, color: C.muted }}>{meta}</div> : null}
      </div>
      <div style={{ position: "relative", margin: 14, height: y }}>
        <Arcs events={events} positions={positions} h={h} progress={arcs} visible={arcVisible} />
        {events.map((e, i) => {
          const rowH = heights ? heights(e, i) : 1;
          return (
            <div key={e.seq} style={{ position: "absolute", top: ys[i], left: 0, height: h * rowH, overflow: "hidden" }}>
              <Row e={e} h={h} w={w} state={state(e, i)} nameWidth={nameWidth} fontScale={fontScale} showSummary={showSummary} />
            </div>
          );
        })}
        {children}
      </div>
    </div>
  );
};

export const Stamp: React.FC<{ tone: "bad" | "good" | "info"; children: React.ReactNode; p: number; style?: React.CSSProperties }> = ({
  tone, children, p, style }) => {
  const color = tone === "bad" ? C.bad : tone === "good" ? C.good : C.accent;
  const soft = tone === "bad" ? C.badSoft : tone === "good" ? C.goodSoft : C.accentSoft;
  return (
    <div style={{ position: "absolute", fontFamily: F.mono, fontWeight: 600, fontSize: 26, letterSpacing: 1.5,
      textTransform: "uppercase", color, background: soft, border: `3px solid ${color}`, borderRadius: 12,
      padding: "14px 22px", opacity: p, scale: `${1.25 - 0.25 * p}`, rotate: `${-2 * p}deg`, whiteSpace: "nowrap",
      ...style }}>
      {children}
    </div>
  );
};

export const Card: React.FC<{ title: string; p: number; tone?: string; children: React.ReactNode; style?: React.CSSProperties }> = ({
  title, p, tone, children, style }) => (
  <div style={{ position: "absolute", background: C.surface, border: `1.5px solid ${tone ?? C.line}`, borderRadius: 16,
    padding: "22px 26px", display: "grid", gap: 12, opacity: p, translate: `0px ${(1 - p) * 24}px`, boxSizing: "border-box",
    ...style }}>
    <div style={{ fontFamily: F.mono, fontSize: 19, letterSpacing: 2, textTransform: "uppercase", color: C.muted }}>{title}</div>
    {children}
  </div>
);

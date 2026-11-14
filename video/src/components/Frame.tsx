import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { BAND_TOP, C, F, STAGE, clamp, easeOut } from "../theme";

export type Caption = { from: number; to: number; text: string };

export const CHAPTERS = ["Record", "Replay", "Reduce", "Explore", "Regress", "Investigate", "Measure"];

const ChapterBar: React.FC<{ index: number }> = ({ index }) => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, 18], [0, 1], { ...clamp, easing: easeOut });
  return (
    <div style={{ position: "absolute", top: 56, left: STAGE.left, right: STAGE.right, display: "flex",
      alignItems: "center", gap: 28, opacity: enter }}>
      <div style={{ fontFamily: F.mono, fontSize: 22, letterSpacing: 3, color: C.muted, textTransform: "uppercase" }}>
        ReproLab
      </div>
      <div style={{ flex: 1, display: "flex", gap: 10 }}>
        {CHAPTERS.map((name, i) => (
          <div key={name} style={{ flex: 1, display: "grid", gap: 8 }}>
            <div style={{ height: 4, borderRadius: 2, background: i < index ? C.accent : i === index ? C.ink : C.line,
              opacity: i === index ? 1 : i < index ? 0.55 : 1 }} />
            <div style={{ fontFamily: F.mono, fontSize: 17, letterSpacing: 1.5, textTransform: "uppercase",
              color: i === index ? C.ink : C.dim }}>
              {String(i + 1).padStart(2, "0")} {name}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const CaptionLine: React.FC<{ caption: Caption }> = ({ caption }) => {
  const frame = useCurrentFrame();
  const inP = interpolate(frame, [caption.from, caption.from + 14], [0, 1], { ...clamp, easing: easeOut });
  const outP = interpolate(frame, [caption.to - 10, caption.to], [1, 0], clamp);
  if (frame < caption.from || frame > caption.to) return null;
  return (
    <div style={{ position: "absolute", left: STAGE.left, right: STAGE.right, top: BAND_TOP + 36,
      fontFamily: F.sans, fontWeight: 500, fontSize: 44, lineHeight: 1.32, color: C.ink, maxWidth: 1640,
      opacity: Math.min(inP, outP), translate: `0px ${(1 - inP) * 16}px`, textWrap: "balance" }}>
      {caption.text}
    </div>
  );
};

export const Captions: React.FC<{ captions: Caption[] }> = ({ captions }) => (
  <>
    <div style={{ position: "absolute", left: 0, right: 0, top: BAND_TOP, bottom: 0,
      background: `linear-gradient(180deg, ${C.ground2} 0%, ${C.ground} 100%)`, borderTop: `1px solid ${C.line}` }} />
    {captions.map((c) => <CaptionLine key={c.from} caption={c} />)}
  </>
);

/** A chapter scene: grid ground, the chapter bar, a stage for content, a caption band. */
export const Scene: React.FC<{ chapter?: number; captions?: Caption[]; children: React.ReactNode }> = ({
  chapter, captions = [], children,
}) => {
  const { width } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: C.ground, fontFamily: F.sans, color: C.ink, overflow: "hidden" }}>
      <AbsoluteFill style={{
        backgroundImage: `radial-gradient(${C.line} 1px, transparent 1px)`, backgroundSize: "32px 32px",
        opacity: 0.35, maskImage: "linear-gradient(180deg, black 0%, black 70%, transparent 82%)",
      }} />
      {chapter !== undefined ? <ChapterBar index={chapter} /> : null}
      <div style={{ position: "absolute", left: STAGE.left, top: STAGE.top, width: width - STAGE.left - STAGE.right,
        height: BAND_TOP - STAGE.top - 28 }}>
        {children}
      </div>
      <Captions captions={captions} />
    </AbsoluteFill>
  );
};

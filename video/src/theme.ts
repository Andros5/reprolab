import { Easing } from "remotion";
import { loadFont as loadSans } from "@remotion/google-fonts/IBMPlexSans";
import { loadFont as loadMono } from "@remotion/google-fonts/IBMPlexMono";
import { loadFont as loadCond } from "@remotion/google-fonts/IBMPlexSansCondensed";

// The same visual code as the HTML flight recorder: solid = observed, hatched =
// simulated fault, dashed = reconstructed, arcs = dependencies.
export const C = {
  ground: "#0a0f15",
  ground2: "#0e151e",
  surface: "#131b26",
  surface2: "#192330",
  line: "#253142",
  ink: "#e8edf4",
  muted: "#8b97a9",
  dim: "#56627a",
  accent: "#86a8ff",
  accentSoft: "rgba(134,168,255,0.14)",
  warn: "#e8aa4d",
  warnSoft: "rgba(232,170,77,0.18)",
  bad: "#ff7d70",
  badSoft: "rgba(255,125,112,0.16)",
  good: "#66c892",
  goodSoft: "rgba(102,200,146,0.15)",
};

export const F = {
  sans: loadSans("normal", { weights: ["400", "500", "600"], subsets: ["latin"] }).fontFamily,
  mono: loadMono("normal", { weights: ["400", "500", "600"], subsets: ["latin"] }).fontFamily,
  cond: loadCond("normal", { weights: ["500", "600", "700"], subsets: ["latin"] }).fontFamily,
};

// Layout: content lives above y=850; the caption band below it is reserved for text,
// so explanations never cover what the viewer has to see.
export const STAGE = { left: 96, right: 96, top: 150, bottom: 230 };
export const BAND_TOP = 872;

export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

import React from "react";
import { Audio } from "@remotion/media";
import { staticFile } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { CitaLab } from "./scenes/CitaLab";
import { Crash } from "./scenes/Crash";
import { Explore } from "./scenes/Explore";
import { Intro } from "./scenes/Intro";
import { Metrics } from "./scenes/Metrics";
import { Outro } from "./scenes/Outro";
import { Problem } from "./scenes/Problem";
import { Record } from "./scenes/Record";
import { Reduce } from "./scenes/Reduce";
import { Regress } from "./scenes/Regress";
import { Replay } from "./scenes/Replay";

export const SCENES = [150, 240, 300, 210, 300, 420, 270, 330, 540, 240, 180];
export const FADE = 14;
export const TOTAL = SCENES.reduce((a, b) => a + b, 0) - FADE * (SCENES.length - 1);

const t = () => <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: FADE })} />;

export const ReproLabVideo: React.FC = () => (
  <>
  {/* Synthesized from the same data as the picture: video/sound/score.py */}
  <Audio name="Score" src={staticFile("score.wav")} />
  <TransitionSeries>
    <TransitionSeries.Sequence name="Intro" durationInFrames={150}><Intro /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="The problem" durationInFrames={240}><Problem /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Record" durationInFrames={300}><Record /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Replay" durationInFrames={210}><Replay /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Reduce" durationInFrames={300}><Reduce /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Explore" durationInFrames={420}><Explore /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Crash and restart" durationInFrames={270}><Crash /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Regress" durationInFrames={330}><Regress /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="CitaLab" durationInFrames={540}><CitaLab /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Metrics" durationInFrames={240}><Metrics /></TransitionSeries.Sequence>
    {t()}
    <TransitionSeries.Sequence name="Outro" durationInFrames={180}><Outro /></TransitionSeries.Sequence>
  </TransitionSeries>
  </>
);

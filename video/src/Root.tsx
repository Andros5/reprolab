import React from "react";
import { Composition } from "remotion";
import { ReproLabVideo, TOTAL } from "./Video";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="ReproLab"
    component={ReproLabVideo}
    durationInFrames={TOTAL}
    fps={30}
    width={1920}
    height={1080}
  />
);

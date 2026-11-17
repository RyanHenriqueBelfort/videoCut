import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { ShortClip } from "./ShortClip";
import { defaultProps, ShortClipProps } from "./types";

const FPS = 30;

const calculateMetadata: CalculateMetadataFunction<ShortClipProps> = ({ props }) => ({
  durationInFrames: Math.max(1, Math.ceil((props.duration + (props.hook?.duration ?? 0)) * FPS)),
});

export const RemotionRoot: React.FC = () => (
  <Composition
    id="ShortClip"
    component={ShortClip}
    width={1080}
    height={1920}
    fps={FPS}
    durationInFrames={300}
    defaultProps={defaultProps}
    calculateMetadata={calculateMetadata}
  />
);

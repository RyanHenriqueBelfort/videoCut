import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Montserrat";
import { Captions } from "./Captions";
import { CropPoint, Hook, ShortClipProps } from "./types";

const { fontFamily } = loadFont("normal", { weights: ["800", "900"], subsets: ["latin", "latin-ext"] });

export const ShortClip: React.FC<ShortClipProps> = (p) => {
  const { fps } = useVideoConfig();
  const hookFrames = p.hook ? Math.round(p.hook.duration * fps) : 0;
  const clipFrames = Math.max(1, Math.round(p.duration * fps));

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {p.hook ? (
        <Sequence durationInFrames={hookFrames} name="Gancho">
          <HookIntro hook={p.hook} fontFamily={fontFamily} />
        </Sequence>
      ) : null}
      <Sequence from={hookFrames} durationInFrames={clipFrames} name="Corte">
        <ReframedVideo {...p} />
        <Captions words={p.words} style={p.captionStyle} fontFamily={fontFamily} />
        {p.audio ? <Audio src={staticFile(p.audio)} /> : null}
      </Sequence>
    </AbsoluteFill>
  );
};

const cropAt = (crop: CropPoint[], t: number): number => {
  if (crop.length === 0) return 0.5;
  if (crop.length === 1) return crop[0].x;
  return interpolate(
    t,
    crop.map((c) => c.t),
    crop.map((c) => c.x),
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
};

const ReframedVideo: React.FC<ShortClipProps> = (p) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const volume = p.audio ? p.originalVolume : 1;
  const src = staticFile(p.video);

  const scaledW = (p.srcWidth * height) / p.srcHeight;

  // Fonte já vertical/estreita: encaixa na largura com fundo desfocado.
  if (scaledW <= width) {
    const fitH = (p.srcHeight * width) / p.srcWidth;
    return (
      <AbsoluteFill>
        <OffthreadVideo
          src={src}
          muted
          style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(40px) brightness(0.5)" }}
        />
        <OffthreadVideo
          src={src}
          volume={volume}
          style={{ position: "absolute", width, height: fitH, top: (height - fitH) / 2 }}
        />
      </AbsoluteFill>
    );
  }

  const cx = cropAt(p.crop, frame / fps);
  const left = Math.min(0, Math.max(width - scaledW, width / 2 - cx * scaledW));
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <OffthreadVideo
        src={src}
        volume={volume}
        style={{ position: "absolute", height, width: scaledW, left, top: 0, maxWidth: "none" }}
      />
    </AbsoluteFill>
  );
};

const HookIntro: React.FC<{ hook: Hook; fontFamily: string }> = ({ hook, fontFamily }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 12, stiffness: 160 } });
  const zoom = interpolate(frame, [0, hook.duration * fps], [1.05, 1.15]);

  return (
    <AbsoluteFill>
      {hook.image ? (
        <Img
          src={staticFile(hook.image)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${zoom})`,
            filter: "blur(18px) brightness(0.45)",
          }}
        />
      ) : null}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: 80 }}>
        <div
          style={{
            fontFamily,
            fontWeight: 900,
            fontSize: 96,
            lineHeight: 1.1,
            color: "white",
            textAlign: "center",
            textTransform: "uppercase",
            transform: `scale(${pop})`,
            WebkitTextStroke: "6px black",
            paintOrder: "stroke fill",
            textShadow: "0 10px 40px rgba(0,0,0,0.6)",
          }}
        >
          {hook.text}
        </div>
      </AbsoluteFill>
      {hook.audio ? <Audio src={staticFile(hook.audio)} /> : null}
    </AbsoluteFill>
  );
};

import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { CaptionStyle, Word } from "./types";

type Page = { start: number; end: number; words: Word[] };

const buildPages = (words: Word[], perPage: number): Page[] => {
  const pages: Page[] = [];
  let cur: Word[] = [];
  const flush = () => {
    if (cur.length) pages.push({ start: cur[0].start, end: cur[cur.length - 1].end, words: cur });
    cur = [];
  };
  words.forEach((w, i) => {
    const prev = words[i - 1];
    if (cur.length && (cur.length >= perPage || (prev && w.start - prev.end > 0.6))) flush();
    cur.push(w);
    if (/[.!?…]$/.test(w.word)) flush();
  });
  flush();
  // Mantém cada página na tela até a próxima começar (evita piscar entre palavras).
  return pages.map((p, i) => ({
    ...p,
    end: i + 1 < pages.length ? Math.min(pages[i + 1].start, p.end + 0.5) : p.end + 0.5,
  }));
};

export const Captions: React.FC<{ words: Word[]; style: CaptionStyle; fontFamily: string }> = ({
  words,
  style,
  fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const t = frame / fps;
  const pages = useMemo(() => buildPages(words, style.wordsPerPage), [words, style.wordsPerPage]);
  const page = pages.find((p) => t >= p.start && t < p.end);
  if (!page) return null;

  const enter = interpolate(t - page.start, [0, 0.12], [0.85, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ alignItems: "center" }}>
      <div
        style={{
          position: "absolute",
          top: height * style.position,
          transform: `translateY(-50%) scale(${enter})`,
          width: "88%",
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "0 22px",
          fontFamily,
          fontWeight: 900,
          fontSize: style.fontSize,
          lineHeight: 1.15,
          textAlign: "center",
          textTransform: style.uppercase ? "uppercase" : "none",
        }}
      >
        {page.words.map((w, i) => {
          const active = t >= w.start && t < (page.words[i + 1]?.start ?? page.end);
          const pop = active ? interpolate(t - w.start, [0, 0.08, 0.16], [1, 1.12, 1.06], { extrapolateRight: "clamp" }) : 1;
          return (
            <span
              key={i}
              style={{
                color: active ? style.highlight : style.color,
                display: "inline-block",
                transform: `scale(${pop})`,
                WebkitTextStroke: "10px black",
                paintOrder: "stroke fill",
                textShadow: "0 6px 18px rgba(0,0,0,0.55)",
              }}
            >
              {w.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

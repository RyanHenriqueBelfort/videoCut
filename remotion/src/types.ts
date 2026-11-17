export type Word = { start: number; end: number; word: string };
export type CropPoint = { t: number; x: number };

export type CaptionStyle = {
  color: string;
  highlight: string;
  position: number; // 0 = topo, 1 = base
  wordsPerPage: number;
  uppercase: boolean;
  fontSize: number;
};

export type Hook = {
  text: string;
  audio: string | null; // arquivo no public-dir (narração do VoiceStudio)
  image: string | null; // frame de fundo
  duration: number;
};

export type ShortClipProps = {
  video: string;
  srcWidth: number;
  srcHeight: number;
  duration: number;
  words: Word[];
  crop: CropPoint[];
  captionStyle: CaptionStyle;
  hook: Hook | null;
  audio: string | null; // trilha substituta (dublagem)
  originalVolume: number;
  title: string;
};

export const defaultProps: ShortClipProps = {
  video: "clip.mp4",
  srcWidth: 1920,
  srcHeight: 1080,
  duration: 10,
  words: [],
  crop: [{ t: 0, x: 0.5 }],
  captionStyle: {
    color: "#FFFFFF",
    highlight: "#FFE11A",
    position: 0.72,
    wordsPerPage: 3,
    uppercase: true,
    fontSize: 84,
  },
  hook: null,
  audio: null,
  originalVolume: 1,
  title: "",
};

"""Prepara cada corte (vídeo recortado, enquadramento, legendas, áudios) e renderiza com Remotion."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .config import Settings
from .highlights import clip_segments, clip_words
from .jobs import Job
from .media import cut_clip, grab_frame, run_streaming, wav_duration
from .progress import report
from .reframe import compute_crop_track

DEFAULT_STYLE = {
    "color": "#FFFFFF",
    "highlight": "#FFE11A",
    "position": 0.72,       # altura da legenda (0 = topo, 1 = base)
    "wordsPerPage": 3,
    "uppercase": True,
    "fontSize": 84,
}


def get_clip(job: Job, index: int) -> dict:
    for c in job.highlights():
        if c["index"] == index:
            return c
    raise KeyError(f"Corte {index} não existe no job {job.id}")


RENDER_FIELDS = {"start", "end", "title", "hook", "use_hook", "caption_style", "dub"}


def update_clip(job: Job, index: int, **changes: Any) -> dict:
    clips = job.highlights()
    for c in clips:
        if c["index"] == index:
            timing_changed = any(k in changes and changes[k] is not None and changes[k] != c.get(k)
                                 for k in ("start", "end"))
            visual_changed = any(k in changes and changes[k] is not None and changes[k] != c.get(k)
                                 for k in RENDER_FIELDS)
            c.update({k: v for k, v in changes.items() if v is not None})
            if visual_changed and c.get("output"):
                c["dirty"] = True  # o MP4 renderizado está desatualizado
            if timing_changed:
                c.pop("prepared", None)
                # força recorte/reenquadramento na próxima renderização
                for f in ("clip.mp4", "thumb.jpg"):
                    (job.clip_dir(index) / "public" / f).unlink(missing_ok=True)
                (job.clip_dir(index) / "crop.json").unlink(missing_ok=True)
            job.save_highlights(clips)
            return c
    raise KeyError(f"Corte {index} não existe")


def delete_clip(job: Job, index: int) -> None:
    import shutil as _sh
    job.save_highlights([c for c in job.highlights() if c["index"] != index])
    _sh.rmtree(job.dir / "clips" / f"{index:02d}", ignore_errors=True)


def add_manual_clip(job: Job, start: float, end: float, title: str = "", hook: str = "") -> dict:
    from .highlights import save_agent_clips
    clips = save_agent_clips(job, [{"start": start, "end": end, "title": title or "Corte manual",
                                    "hook": hook or title, "reason": "manual", "score": 0}],
                             snap=True, replace=False)
    return max(clips, key=lambda c: c["index"])


def prepare_clip(job: Job, index: int) -> Path:
    clip = get_clip(job, index)
    d = job.clip_dir(index)
    pub = d / "public"
    video = pub / "clip.mp4"
    if not video.exists():
        report(f"Corte {index}: recortando", 0.02)
        print(f"[corte {index}] recortando {clip['start']:.1f}s - {clip['end']:.1f}s", flush=True)
        cut_clip(job.video_path, clip["start"], clip["end"], video)
    if not (pub / "thumb.jpg").exists():
        grab_frame(video, 0.1, pub / "thumb.jpg")
    crop_file = d / "crop.json"
    if not crop_file.exists():
        report(f"Corte {index}: enquadrando rosto (9:16)", 0.06)
        print(f"[corte {index}] calculando enquadramento 9:16...", flush=True)
        crop_file.write_text(json.dumps(compute_crop_track(job.video_path, clip["start"], clip["end"])), encoding="utf-8")
    write_srt(clip_words(job, clip), d / "legendas.srt")
    return d


def build_props(job: Job, index: int) -> dict:
    clip = get_clip(job, index)
    d = job.clip_dir(index)
    meta = job.meta
    words = clip_words(job, clip)
    props: dict[str, Any] = {
        "video": "clip.mp4",
        "srcWidth": meta["width"],
        "srcHeight": meta["height"],
        "duration": round(clip["end"] - clip["start"], 3),
        "words": words,
        "crop": json.loads((d / "crop.json").read_text(encoding="utf-8")),
        "captionStyle": {**DEFAULT_STYLE, **clip.get("caption_style", {})},
        "hook": None,
        "audio": None,
        "originalVolume": 1,
        "title": clip["title"],
    }
    hook_wav = d / "public" / "hook.wav"
    if clip.get("use_hook") and hook_wav.exists():
        props["hook"] = {"text": clip["hook"], "audio": "hook.wav", "image": "thumb.jpg",
                         "duration": round(wav_duration(hook_wav) + 0.4, 3)}
    elif clip.get("use_hook"):
        props["hook"] = {"text": clip["hook"], "audio": None, "image": "thumb.jpg", "duration": 2.5}
    dub = clip.get("dub")
    if dub and (d / "public" / "dub.wav").exists():
        props["audio"] = "dub.wav"
        props["originalVolume"] = dub.get("original_volume", 0.08)
        props["words"] = json.loads((d / "dub_words.json").read_text(encoding="utf-8"))
    return props


def render_clip(job: Job, index: int, settings: Settings) -> Path:
    d = prepare_clip(job, index)
    props = build_props(job, index)
    props_file = d / "props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

    clip = get_clip(job, index)
    out = d / f"{index:02d}_{_safe(clip['title'])}.mp4"
    npx = shutil.which("npx.cmd") or shutil.which("npx")  # no Windows o "npx" sem extensão é script bash
    if not npx:
        raise RuntimeError("Node.js/npx não encontrado no PATH.")
    if not (settings.remotion_dir / "node_modules").exists():
        raise RuntimeError(f"Rode `npm install` em {settings.remotion_dir} antes de renderizar.")
    cmd = [npx, "remotion", "render", "src/index.ts", "ShortClip", str(out),
           f"--props={props_file}", f"--public-dir={d / 'public'}", "--codec=h264", "--crf=20"]
    print(f"[corte {index}] renderizando com Remotion -> {out.name}", flush=True)
    report(f"Corte {index}: renderizando", 0.1)

    def on_line(line: str) -> None:
        m = _RENDER_RE.search(line)
        if m:
            done, total = int(m.group(2)), int(m.group(3))
            base, span = (0.1, 0.8) if m.group(1) == "Rendered" else (0.9, 0.1)
            report(None, base + span * done / max(total, 1))

    # Saída transmitida via print(): no servidor MCP vai para stderr e não corrompe o protocolo.
    code, tail = run_streaming(cmd, on_line=on_line, cwd=settings.remotion_dir, echo=False)
    if code != 0:
        raise RuntimeError(f"Remotion falhou (código {code}):\n{tail[-1500:]}")
    # Remove renders antigos com outro título.
    for old in d.glob(f"{index:02d}_*.mp4"):
        if old != out:
            old.unlink(missing_ok=True)
    update_clip(job, index, output=str(out))
    clips = job.highlights()
    for c in clips:
        if c["index"] == index:
            c["dirty"] = False
    job.save_highlights(clips)
    report(f"Corte {index} pronto", 1.0)
    print(f"[corte {index}] pronto: {out}", flush=True)
    return out


_RENDER_RE = re.compile(r"(Rendered|Encoded)\s+(\d+)/(\d+)")


def _safe(text: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in " -_" else "" for ch in text)
    return "_".join(keep.split())[:50] or "corte"


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(words: list[dict], out: Path, per_line: int = 6) -> Path:
    lines, n = [], 1
    for i in range(0, len(words), per_line):
        chunk = words[i:i + per_line]
        lines += [str(n), f"{_srt_time(chunk[0]['start'])} --> {_srt_time(chunk[-1]['end'])}",
                  " ".join(w["word"] for w in chunk), ""]
        n += 1
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def segments_for_dub(job: Job, index: int) -> list[dict]:
    return clip_segments(job, get_clip(job, index))

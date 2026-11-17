"""Utilitários de FFmpeg (binário embutido via imageio-ffmpeg, sem instalação no sistema)."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import cv2
import imageio_ffmpeg


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(*args: str) -> None:
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {' '.join(cmd)}\n{proc.stderr}")


def run_streaming(cmd: list[str], on_line=None, cwd: Path | None = None, input_text: str | None = None,
                  echo: bool = True) -> tuple[int, str]:
    """Roda um processo lendo stdout+stderr linha a linha (quebras \\n ou \\r).

    Cada linha é impressa via print() (vai para o log da tarefa na interface, ou para
    stderr no servidor MCP) e passada a on_line. Retorna (código, últimas linhas).
    """
    import collections
    import os

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "FORCE_COLOR": "0"}
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL)
    if input_text is not None:
        proc.stdin.write(input_text.encode("utf-8"))
        proc.stdin.close()
    tail: collections.deque[str] = collections.deque(maxlen=40)
    buf = b""
    last_echo = ""
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        parts = buf.replace(b"\r", b"\n").split(b"\n")
        buf = parts.pop()
        for raw in parts:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            tail.append(line)
            if on_line:
                on_line(line)
            if echo and line != last_echo:
                print(line, flush=True)
                last_echo = line
    if buf.strip():
        tail.append(buf.decode("utf-8", errors="replace"))
    return proc.wait(), "\n".join(tail)


def probe_video(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        return {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(fps),
            "duration": float(frames / fps) if fps else 0.0,
        }
    finally:
        cap.release()


def extract_audio(video: Path, out_wav: Path, start: float | None = None, end: float | None = None) -> Path:
    args: list[str] = []
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    run_ffmpeg(*args, "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_wav))
    return out_wav


def cut_clip(video: Path, start: float, end: float, out: Path) -> Path:
    """Corte com reencode (preciso no frame, sem depender de keyframes)."""
    run_ffmpeg(
        "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{end - start:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
    )
    return out


def grab_frame(video: Path, at: float, out: Path) -> Path:
    run_ffmpeg("-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out))
    return out


def audio_to_video(audio: Path, out: Path) -> Path:
    """Para entradas só de áudio (.mp3 etc.): gera um vídeo vertical com forma de onda."""
    run_ffmpeg(
        "-i", str(audio), "-filter_complex",
        "[0:a]showwaves=s=1080x600:mode=cline:colors=white,format=yuv420p,"
        "pad=1080:1920:0:660:color=0x111111[v]",
        "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k", str(out),
    )
    return out


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())

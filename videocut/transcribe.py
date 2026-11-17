"""Transcrição com timestamps por palavra.

Backends:
  - faster-whisper (padrão, local). Roda em subprocesso: se a GPU/CUDA falhar
    (DLL ausente, arquitetura nova etc.) cai automaticamente para CPU.
  - voicestudio: usa o endpoint OpenAI-compatível do VoiceStudio (WhisperX).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

from .config import Settings
from .jobs import Job
from .media import run_streaming
from .progress import report


def transcribe_job(job: Job, settings: Settings, force: bool = False) -> dict:
    if job.transcript_path.exists() and not force:
        return job.transcript()
    report("Transcrevendo...", 0.0)
    if settings.transcriber == "voicestudio":
        data = _voicestudio(job.audio_path, settings)
    else:
        data = _faster_whisper(job.audio_path, job.transcript_path, settings, job.meta.get("duration") or 0)
    job.write("transcript.json", data)
    report("Transcrição pronta", 1.0)
    return data


# --------------------------------------------------------------------------- faster-whisper
_SEG_LINE = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s")


def _faster_whisper(audio: Path, out: Path, settings: Settings, duration: float) -> dict:
    devices = ["cuda", "cpu"] if settings.whisper_device == "auto" else [settings.whisper_device]
    errors = []

    def on_line(line: str) -> None:
        m = _SEG_LINE.match(line)
        if m and duration:
            report(None, float(m.group(1)) / duration)

    for device in devices:
        cmd = [sys.executable, "-m", "videocut.transcribe", str(audio), str(out),
               "--model", settings.whisper_model, "--device", device]
        if settings.language:
            cmd += ["--language", settings.language]
        print(f"[transcrição] faster-whisper {settings.whisper_model} em {device}...", flush=True)
        report(f"Transcrevendo ({'GPU' if device == 'cuda' else 'CPU'})...", 0.0)
        out.unlink(missing_ok=True)
        code, tail = run_streaming(cmd, on_line=on_line)
        if code == 0 and out.exists():
            return json.loads(out.read_text(encoding="utf-8"))
        errors.append(f"{device}: {tail[-1500:]}")
        print(f"[transcrição] falhou em {device}, tentando próximo dispositivo...", flush=True)
    raise RuntimeError("Transcrição falhou:\n" + "\n".join(errors))


def _add_nvidia_dll_dirs() -> None:
    """No Windows, expõe as DLLs dos pacotes pip nvidia-cublas/cudnn ao CTranslate2."""
    import os
    import site

    if os.name != "nt":
        return
    for base in site.getsitepackages():
        for bin_dir in Path(base, "nvidia").glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir};{os.environ['PATH']}"


def _worker(audio: str, out: str, model: str, device: str, language: str | None) -> None:
    import os

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if device == "cuda":
        _add_nvidia_dll_dirs()
    from faster_whisper import WhisperModel

    import wave

    import numpy as np

    # Lê o WAV 16 kHz mono que o ingest gerou (evita o decodificador PyAV do faster-whisper,
    # que quebra com versões novas do `av`).
    with wave.open(audio, "rb") as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

    compute = "float16" if device == "cuda" else "int8"
    wm = WhisperModel(model, device=device, compute_type=compute)
    segments, info = wm.transcribe(
        samples, language=language, word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    data = {"language": info.language, "duration": info.duration, "segments": []}
    for seg in segments:
        data["segments"].append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": [
                {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
                for w in (seg.words or []) if w.word.strip()
            ],
        })
        print(f"  {seg.start:7.1f}s  {seg.text.strip()[:80]}", file=sys.stderr, flush=True)
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- VoiceStudio
def _voicestudio(audio: Path, settings: Settings) -> dict:
    url = settings.voicestudio_url.rstrip("/") + "/v1/audio/transcriptions"
    with audio.open("rb") as fh:
        files = {"file": (audio.name, fh, "audio/wav")}
        data = [("model", "whisper-1"), ("response_format", "verbose_json"),
                ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
        if settings.language:
            data.append(("language", settings.language))
        r = httpx.post(url, files=files, data=data, timeout=None)
    r.raise_for_status()
    raw = r.json()
    words = [{"start": w["start"], "end": w["end"], "word": w["word"].strip()} for w in raw.get("words", [])]
    segments = []
    for s in raw.get("segments", []):
        segments.append({
            "start": s["start"], "end": s["end"], "text": s["text"].strip(),
            "words": s.get("words") or [w for w in words if s["start"] <= w["start"] < s["end"]],
        })
    if not segments:
        raise RuntimeError(f"VoiceStudio não retornou segmentos: {str(raw)[:300]}")
    return {"language": raw.get("language"), "duration": raw.get("duration"), "segments": segments}


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("out")
    p.add_argument("--model", default="large-v3-turbo")
    p.add_argument("--device", default="cuda")
    p.add_argument("--language", default=None)
    a = p.parse_args()
    _worker(a.audio, a.out, a.model, a.device, a.language)

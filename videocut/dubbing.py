"""Dublagem de um corte: traduz (Ollama) e fala com a voz clonada do original (VoiceStudio)."""
from __future__ import annotations

from pathlib import Path

from .config import Settings
from .llm import chat_json
from .media import extract_audio, run_ffmpeg, wav_duration
from .voicestudio import VoiceStudio

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        }
    },
    "required": ["items"],
}


def translate_segments(segments: list[dict], target: str, settings: Settings) -> list[str]:
    lines = "\n".join(f"{i}: {s['text']}" for i, s in enumerate(segments))
    resp = chat_json(
        settings,
        "Você é um tradutor profissional de dublagem. Traduza de forma natural e falada, "
        "mantendo um tamanho parecido com o original para caber no mesmo tempo.",
        f"Traduza cada linha para {target}. Mantenha os ids.\n\n{lines}",
        TRANSLATE_SCHEMA,
        temperature=0.2,
    )
    by_id = {int(it["id"]): it["text"].strip() for it in resp.get("items", [])}
    return [by_id.get(i, s["text"]) for i, s in enumerate(segments)]


def dub_clip(clip_dir: Path, clip_video: Path, segments: list[dict], target_lang: str,
             tts_language: str | None, settings: Settings, voice_profile: str | None = None) -> tuple[Path, list[dict]]:
    """Retorna (arquivo de áudio dublado, palavras para legenda com tempos relativos)."""
    vs = VoiceStudio(settings)
    work = clip_dir / "dub"
    work.mkdir(exist_ok=True)

    # 1) Voz: clona a do falante usando ~15s do próprio corte.
    if not voice_profile:
        ref = extract_audio(clip_video, work / "ref.wav", start=segments[0]["start"],
                            end=min(segments[0]["start"] + 15, segments[-1]["end"]))
        ref_text = " ".join(s["text"] for s in segments if s["start"] < segments[0]["start"] + 15)
        voice_profile = vs.clone_voice(ref, name=f"videocut-{clip_dir.parent.parent.name}", ref_text=ref_text)

    # 2) Tradução.
    translated = translate_segments(segments, target_lang, settings)

    # 3) TTS por segmento, ajustando velocidade para caber no espaço original.
    parts: list[tuple[Path, float]] = []
    words: list[dict] = []
    for i, (seg, text) in enumerate(zip(segments, translated)):
        raw = vs.generate_speech(text, work / f"seg{i:03d}_raw.wav", profile_id=voice_profile, language=tts_language)
        norm = work / f"seg{i:03d}.wav"
        run_ffmpeg("-i", str(raw), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(norm))
        dur = wav_duration(norm)
        next_start = segments[i + 1]["start"] if i + 1 < len(segments) else seg["end"] + 1.5
        slot = max(0.3, next_start - seg["start"])
        if dur > slot:
            tempo = min(dur / slot, 1.5)
            fitted = work / f"seg{i:03d}_fit.wav"
            run_ffmpeg("-i", str(norm), "-filter:a", f"atempo={tempo:.3f}", str(fitted))
            norm, dur = fitted, dur / tempo
        parts.append((norm, seg["start"]))

        # Legenda: distribui as palavras traduzidas uniformemente pela fala gerada.
        tokens = text.split()
        for j, tok in enumerate(tokens):
            ws = seg["start"] + dur * j / len(tokens)
            words.append({"start": round(ws, 3), "end": round(ws + dur / len(tokens), 3), "word": tok})

    # 4) Monta a trilha final posicionando cada trecho no seu tempo.
    out = clip_dir / "public" / "dub.wav"
    inputs: list[str] = []
    filters: list[str] = []
    for k, (p, at) in enumerate(parts):
        inputs += ["-i", str(p)]
        ms = int(at * 1000)
        filters.append(f"[{k}:a]adelay={ms}|{ms}[d{k}]")
    mix = "".join(f"[d{k}]" for k in range(len(parts)))
    filters.append(f"{mix}amix=inputs={len(parts)}:normalize=0[out]")
    run_ffmpeg(*inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-c:a", "pcm_s16le", str(out))
    return out, words

"""Orquestra as etapas. Cada etapa grava em disco e é reaproveitada (cache) se já existir."""
from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .davinci import send_to_davinci
from .dubbing import dub_clip as _dub
from .highlights import find_highlights
from .ingest import ingest
from .jobs import Job
from .progress import report
from .render import get_clip, prepare_clip, render_clip, segments_for_dub, update_clip
from .transcribe import transcribe_job
from .voicestudio import VoiceStudio


def select_clips(job: Job, settings: Settings, max_clips: int = 5, instructions: str = "",
                 replace: bool = True) -> list[dict]:
    if settings.selector == "ollama":
        return find_highlights(job, settings, max_clips=max_clips, force=True)
    from .claude_select import select_with_claude
    return select_with_claude(job, settings, max_clips=max_clips, instructions=instructions, replace=replace)


def analyze(source: str, settings: Settings, max_clips: int = 5, force: bool = False,
            auto_select: bool | None = None, instructions: str = "") -> Job:
    """Baixa, transcreve e (se o seletor for 'claude' ou 'ollama') escolhe os cortes.
    No modo 'agent' quem escolhe é o Claude conversando (MCP / skill /cortar)."""
    report("Baixando / abrindo o vídeo...", 0.0)
    job = ingest(source, settings)
    print(f"[job] {job.id}  ({job.meta.get('title')})", flush=True)
    transcribe_job(job, settings, force=force)
    should_select = auto_select if auto_select is not None else settings.selector in ("claude", "ollama")
    if should_select and (force or not job.highlights()):
        select_clips(job, settings, max_clips=max_clips, instructions=instructions)
    return job


def add_hook_narration(job: Job, index: int, settings: Settings, text: str | None = None,
                       profile_id: str | None = None, language: str | None = None) -> Path:
    clip = get_clip(job, index)
    text = text or clip["hook"]
    language = language or job.transcript().get("language")  # ex.: "pt" -> pt-BR no VoiceStudio
    out = job.clip_dir(index) / "public" / "hook.wav"
    print(f"[corte {index}] narrando gancho no VoiceStudio: {text!r}", flush=True)
    VoiceStudio(settings).generate_speech(text, out, profile_id=profile_id, language=language)
    update_clip(job, index, hook=text, use_hook=True)
    return out


def dub(job: Job, index: int, settings: Settings, target_lang: str, tts_language: str | None = None,
        profile_id: str | None = None, original_volume: float = 0.08) -> Path:
    d = prepare_clip(job, index)
    print(f"[corte {index}] dublando para {target_lang}...", flush=True)
    wav, words = _dub(d, d / "public" / "clip.mp4", segments_for_dub(job, index), target_lang,
                      tts_language, settings, voice_profile=profile_id)
    (d / "dub_words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    update_clip(job, index, dub={"language": target_lang, "original_volume": original_volume})
    return wav


def run_all(source: str, settings: Settings, max_clips: int = 5, hook: bool = False,
            dub_to: str | None = None, tts_language: str | None = None, davinci: bool = False,
            render: bool = True) -> Job:
    job = analyze(source, settings, max_clips=max_clips)
    if not job.highlights():
        print(f"\nTranscrição pronta (job {job.id}). Nenhum corte escolhido ainda: no modo 'agent' "
              f"peça ao Claude Code `/cortar {job.id}` ou defina VIDEOCUT_SELECTOR=ollama.")
        return job
    for clip in job.highlights():
        i = clip["index"]
        print(f"\n=== Corte {i}: {clip['title']}  [{clip['start']:.0f}s-{clip['end']:.0f}s, nota {clip['score']}]")
        if hook:
            try:
                add_hook_narration(job, i, settings, language=tts_language)
            except Exception as e:  # narração é opcional; segue sem ela
                print(f"[corte {i}] sem narração: {e}")
                update_clip(job, i, use_hook=True)
        if dub_to:
            dub(job, i, settings, dub_to, tts_language)
        if render:
            out = render_clip(job, i, settings)
            print(f"[corte {i}] pronto: {out}")
    if davinci:
        print(json.dumps(send_to_davinci(job, settings), ensure_ascii=False, indent=2))
    return job

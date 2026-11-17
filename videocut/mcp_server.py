"""Servidor MCP do VideoCut.

Permite que um agente de IA (Claude Code, Claude Desktop, ou qualquer cliente MCP)
opere o sistema inteiro: analisar vídeos, revisar/ajustar cortes, narrar ganchos,
dublar, renderizar e mandar para o DaVinci Resolve.

Os logs vão para stderr para não corromper o protocolo stdio.
"""
from __future__ import annotations

import contextlib
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from .config import get_settings
from .jobs import Job, list_jobs

mcp = MCPServer(
    "videocut",
    instructions=(
        "Sistema de cortes de vídeo. Fluxo: analyze_video (baixa e transcreve) -> você lê a transcrição e "
        "escolhe os cortes -> save_clips -> ajustes com edit_clip -> narrate_hook/dub_clip (opcional) -> "
        "render -> send_to_davinci. Quem escolhe os cortes é você, seguindo o guia editorial que "
        "analyze_video devolve."
    ),
)
S = get_settings()
INLINE_TRANSCRIPT_CHARS = 60_000


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(sys.stderr):
        yield


@mcp.tool()
def analyze_video(source: str, force: bool = False) -> dict:
    """Baixa (link do YouTube) ou abre (caminho local) um vídeo e transcreve com tempo de cada palavra.
    Retorna job_id, duração, o guia editorial e a transcrição numerada ('[L12 03:21-03:27] texto').
    Se o vídeo for longo, a transcrição vem vazia: leia em partes com read_transcript.
    Depois escolha os cortes e chame save_clips."""
    from .highlights import EDITORIAL_GUIDE, transcript_lines
    from .pipeline import analyze
    with _quiet():
        job = analyze(source, S, force=force, auto_select=False)
    lines = transcript_lines(job)
    inline = len(lines) <= INLINE_TRANSCRIPT_CHARS
    return {
        "job_id": job.id,
        "title": job.meta.get("title"),
        "duration_sec": round(job.meta.get("duration") or 0, 1),
        "language": job.transcript().get("language"),
        "segments": len(job.transcript()["segments"]),
        "clip_length_sec": [S.min_clip_sec, S.max_clip_sec],
        "editorial_guide": EDITORIAL_GUIDE,
        "existing_clips": job.highlights(),
        "transcript": lines if inline else "",
        "note": None if inline else "Transcrição longa: use read_transcript(job_id, start, end) em janelas de ~10 min.",
    }


@mcp.tool()
def save_clips(job_id: str, clips: list[dict[str, Any]], replace: bool = True, snap: bool = True) -> list[dict]:
    """Salva os cortes escolhidos. Cada item: {start_line, end_line} (números L da transcrição, preferível)
    OU {start, end} em segundos; mais title (máx. 60 caracteres), hook (frase de abertura, máx. 15 palavras),
    reason, score (1-100) e opcional use_hook (abre o vídeo com o gancho na tela).
    snap=True ajusta tempos em segundos para começar/terminar em frases inteiras.
    replace=False adiciona aos cortes existentes em vez de substituir."""
    from .highlights import save_agent_clips
    return save_agent_clips(Job(S, job_id), clips, snap=snap, replace=replace)


@mcp.tool()
def list_videos() -> list[dict]:
    """Lista os jobs já processados."""
    return list_jobs(S)


@mcp.tool()
def get_clips(job_id: str) -> list[dict]:
    """Lista os cortes de um job."""
    return Job(S, job_id).highlights()


@mcp.tool()
def read_transcript(job_id: str, start: float = 0, end: float | None = None) -> str:
    """Trecho da transcrição entre start e end (segundos), no formato '[L12 03:21-03:27] texto'."""
    from .highlights import transcript_lines
    return transcript_lines(Job(S, job_id), start, end)


@mcp.tool()
def edit_clip(job_id: str, index: int, start: float | None = None, end: float | None = None,
              title: str | None = None, hook: str | None = None, use_hook: bool | None = None,
              caption_style: dict[str, Any] | None = None) -> dict:
    """Ajusta um corte: tempos, título, texto do gancho, se usa abertura com gancho e estilo da legenda
    (caption_style: color, highlight, position 0-1, wordsPerPage, uppercase, fontSize)."""
    from .render import update_clip
    return update_clip(Job(S, job_id), index, start=start, end=end, title=title, hook=hook,
                       use_hook=use_hook, caption_style=caption_style)


@mcp.tool()
def narrate_hook(job_id: str, index: int, text: str | None = None, voice_profile: str | None = None,
                 language: str | None = None) -> str:
    """Gera a narração do gancho com o VoiceStudio e ativa a abertura no corte."""
    from .pipeline import add_hook_narration
    with _quiet():
        return str(add_hook_narration(Job(S, job_id), index, S, text=text, profile_id=voice_profile, language=language))


@mcp.tool()
def dub_clip(job_id: str, index: int, target_language: str, tts_language: str | None = None,
             voice_profile: str | None = None) -> str:
    """Traduz e dubla um corte com a voz original clonada (VoiceStudio). target_language ex.: 'inglês'."""
    from .pipeline import dub
    with _quiet():
        return str(dub(Job(S, job_id), index, S, target_language, tts_language, profile_id=voice_profile))


@mcp.tool()
def render(job_id: str, index: int) -> str:
    """Renderiza um corte vertical 9:16 com legendas animadas (Remotion). Retorna o caminho do MP4."""
    from .render import render_clip
    with _quiet():
        return str(render_clip(Job(S, job_id), index, S))


@mcp.tool()
def send_to_davinci(job_id: str, indices: list[int] | None = None) -> dict:
    """Cria timelines no DaVinci Resolve (versão final + trecho bruto vertical) para os cortes."""
    from .davinci import send_to_davinci as _send
    return _send(Job(S, job_id), S, indices)


@mcp.tool()
def voicestudio_voices() -> Any:
    """Lista as vozes disponíveis no VoiceStudio."""
    from .voicestudio import VoiceStudio
    return VoiceStudio(S).list_voices()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

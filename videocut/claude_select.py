"""Seleção de cortes com o Claude Code em modo não interativo (`claude -p`).

Usa a assinatura do Claude Code já logada na máquina (sem chave de API):
o binário vem do PATH, de VIDEOCUT_CLAUDE_BIN ou da extensão do VS Code.
A chamada roda isolada: sem ferramentas, sem MCP e sem salvar sessão.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import Settings
from .highlights import SCHEMA, SYSTEM, _dedupe, _fmt, _to_times
from .jobs import Job
from .progress import report


class ClaudeNotFound(RuntimeError):
    pass


def _version_key(path: str) -> tuple:
    m = re.search(r"claude-code-([\d.]+)", path)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def find_claude() -> str | None:
    env = os.environ.get("VIDEOCUT_CLAUDE_BIN")
    if env and Path(env).exists():
        return env
    names = ("claude.exe", "claude.cmd") if os.name == "nt" else ("claude",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    home = Path.home()
    candidates = [str(home / ".local" / "bin" / "claude.exe")]
    for ext_dir in (".vscode", ".vscode-insiders", ".cursor", ".windsurf"):
        candidates += sorted(
            glob.glob(str(home / ext_dir / "extensions" / "anthropic.claude-code-*" / "resources"
                          / "native-binary" / "claude*.exe")),
            key=_version_key, reverse=True,
        )
    return next((c for c in candidates if Path(c).exists()), None)


PROMPT = """Abaixo está a transcrição completa de um vídeo{title}.
Cada linha: [L<número> mm:ss] texto.

{lines}

Escolha os {k} MELHORES cortes do vídeo inteiro (não só do começo).
Cada corte deve durar entre {min_s:.0f} e {max_s:.0f} segundos e não pode sobrepor outro.
{extra}
Para cada corte informe start_line e end_line (inclusive), title (máx. 60 caracteres),
hook (frase de abertura, máx. 15 palavras), reason (por que prende a atenção) e score (1 a 100).
Títulos e ganchos no idioma da transcrição."""


def select_with_claude(job: Job, settings: Settings, max_clips: int = 5, instructions: str = "",
                       replace: bool = True) -> list[dict]:
    exe = find_claude()
    if not exe:
        raise ClaudeNotFound(
            "Claude Code não encontrado. Instale a extensão do VS Code ou o CLI "
            "(https://claude.com/claude-code) ou defina VIDEOCUT_CLAUDE_BIN no .env."
        )
    segments = job.transcript()["segments"]
    if not segments:
        raise RuntimeError("Transcrição vazia: nada para cortar.")

    lines = "\n".join(f"[L{i} {_fmt(s['start'])}] {s['text']}" for i, s in enumerate(segments))
    title = job.meta.get("title")
    prompt = PROMPT.format(
        title=f' chamado "{title}"' if title else "", lines=lines, k=max_clips,
        min_s=settings.min_clip_sec, max_s=settings.max_clip_sec,
        extra=f"Instruções do usuário: {instructions.strip()}\n" if instructions.strip() else "",
    )
    cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
           "--tools", "", "--strict-mcp-config", "--no-session-persistence",
           "--system-prompt", SYSTEM.replace("Responda apenas com JSON no formato pedido.", "").strip()]
    if settings.claude_model:
        cmd += ["--model", settings.claude_model]

    report("Claude está escolhendo os cortes...", 0.1)
    print(f"[claude] analisando {len(segments)} frases com {Path(exe).name}...", flush=True)
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=900, cwd=tempfile.gettempdir())
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Claude Code falhou (código {proc.returncode}): {(proc.stderr or proc.stdout)[-800:]}")
    if data.get("is_error") or proc.returncode != 0:
        raise RuntimeError(f"Claude Code retornou erro: {data.get('result') or data.get('api_error_status')}")

    result = data.get("structured_output") or json.loads(data.get("result") or "{}")
    candidates = []
    for c in result.get("clips", []):
        clip = _to_times(c, segments, 0, len(segments) - 1, settings)
        if clip:
            candidates.append(clip)
    clips = _dedupe(sorted(candidates, key=lambda c: -c["score"]))[:max_clips]

    from .highlights import save_agent_clips
    saved = save_agent_clips(job, clips, replace=replace)
    print(f"[claude] {len(saved)} cortes salvos.", flush=True)
    report("Cortes escolhidos", 1.0)
    return saved

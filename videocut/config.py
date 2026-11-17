from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    workdir: Path = field(default_factory=lambda: Path(_env("VIDEOCUT_WORKDIR", str(ROOT / "jobs"))))
    remotion_dir: Path = ROOT / "remotion"

    # Transcrição
    transcriber: str = field(default_factory=lambda: _env("VIDEOCUT_TRANSCRIBER", "faster-whisper"))  # ou "voicestudio"
    whisper_model: str = field(default_factory=lambda: _env("VIDEOCUT_WHISPER_MODEL", "large-v3-turbo"))
    whisper_device: str = field(default_factory=lambda: _env("VIDEOCUT_WHISPER_DEVICE", "auto"))  # auto|cuda|cpu
    language: str | None = field(default_factory=lambda: _env("VIDEOCUT_LANGUAGE"))  # None = detectar

    # Quem escolhe os cortes:
    #   "claude" = Claude Code em modo não interativo (usa sua assinatura, sem chave de API)
    #   "agent"  = ninguém automaticamente; o Claude escolhe conversando (MCP / skill /cortar)
    #   "ollama" = LLM local
    selector: str = field(default_factory=lambda: _env("VIDEOCUT_SELECTOR", "claude"))
    claude_model: str | None = field(default_factory=lambda: _env("VIDEOCUT_CLAUDE_MODEL"))  # vazio = padrão da conta

    # Interface gráfica
    ui_port: int = field(default_factory=lambda: int(_env("VIDEOCUT_UI_PORT", "8765")))

    # LLM local (opcional)
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: _env("VIDEOCUT_LLM", "qwen2.5:14b"))
    ollama_ctx: int = field(default_factory=lambda: int(_env("VIDEOCUT_LLM_CTX", "16384")))

    # Cortes
    min_clip_sec: float = field(default_factory=lambda: float(_env("VIDEOCUT_MIN_CLIP", "20")))
    max_clip_sec: float = field(default_factory=lambda: float(_env("VIDEOCUT_MAX_CLIP", "75")))

    # VoiceStudio
    voicestudio_url: str = field(default_factory=lambda: _env("VOICESTUDIO_URL", "http://127.0.0.1:3900"))
    voicestudio_profile: str | None = field(default_factory=lambda: _env("VOICESTUDIO_PROFILE"))

    def __post_init__(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()

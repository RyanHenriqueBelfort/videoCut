"""Cada vídeo processado vira um "job" em jobs/<id>/ com arquivos JSON por etapa."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import Settings


class Job:
    def __init__(self, settings: Settings, job_id: str):
        self.settings = settings
        self.id = job_id
        self.dir = settings.workdir / job_id
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- arquivos -------------------------------------------------------
    @property
    def meta_path(self) -> Path:
        return self.dir / "job.json"

    @property
    def transcript_path(self) -> Path:
        return self.dir / "transcript.json"

    @property
    def highlights_path(self) -> Path:
        return self.dir / "highlights.json"

    @property
    def audio_path(self) -> Path:
        return self.dir / "audio.wav"

    def clip_dir(self, index: int) -> Path:
        d = self.dir / "clips" / f"{index:02d}"
        (d / "public").mkdir(parents=True, exist_ok=True)
        return d

    # --- JSON -----------------------------------------------------------
    def read(self, name: str) -> Any:
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def write(self, name: str, data: Any) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @property
    def meta(self) -> dict:
        return self.read("job.json") if self.meta_path.exists() else {}

    def update_meta(self, **fields: Any) -> dict:
        meta = self.meta
        meta.update(fields)
        self.write("job.json", meta)
        return meta

    @property
    def video_path(self) -> Path:
        return Path(self.meta["video"])

    def transcript(self) -> dict:
        return self.read("transcript.json")

    def highlights(self) -> list[dict]:
        return self.read("highlights.json") if self.highlights_path.exists() else []

    def save_highlights(self, clips: list[dict]) -> None:
        self.write("highlights.json", clips)

    def reset_clips(self) -> None:
        """Apaga os arquivos dos cortes anteriores (os índices serão reaproveitados)."""
        import shutil
        shutil.rmtree(self.dir / "clips", ignore_errors=True)


def slugify(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^\w\-]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return text[:max_len].strip("-") or "video"


def job_id_for(source: str, title: str | None = None) -> str:
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
    return f"{slugify(title or Path(source).stem)}-{digest}"


def list_jobs(settings: Settings) -> list[dict]:
    out = []
    for meta in sorted(settings.workdir.glob("*/job.json")):
        data = json.loads(meta.read_text(encoding="utf-8"))
        hl = meta.parent / "highlights.json"
        data["clips"] = len(json.loads(hl.read_text(encoding="utf-8"))) if hl.exists() else 0
        out.append(data)
    return out

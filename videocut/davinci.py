"""Envio dos cortes para o DaVinci Resolve.

- Studio: conecta direto e cria as timelines na hora.
- Gratuito: grava um manifesto na fila e você roda Workspace > Scripts > VideoCut
  dentro do DaVinci (scripts internos funcionam na versão gratuita).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import ROOT, Settings
from .jobs import Job
from . import resolve_bridge

MENU_SCRIPT = '''# Gerado pelo VideoCut. Workspace > Scripts > Utility > VideoCut
import sys
from pathlib import Path
sys.path.insert(0, r"{root}")
from videocut.resolve_bridge import import_queue

def _resolve():
    g = globals()
    if g.get("resolve"):
        return g["resolve"]
    if g.get("bmd"):
        return g["bmd"].scriptapp("Resolve")
    return g["app"].GetResolve()

criados = import_queue(_resolve(), Path(r"{queue}"))
print("VideoCut: timelines criadas:", criados if criados else "nenhuma (fila vazia)")
'''


def queue_dir(settings: Settings) -> Path:
    d = settings.workdir / "_davinci_queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def menu_script_path() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Utility" / "VideoCut.py"


def install_menu_script(settings: Settings) -> Path:
    path = menu_script_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MENU_SCRIPT.format(root=ROOT, queue=queue_dir(settings)), encoding="utf-8")
    return path


def build_manifest(job: Job, indices: list[int] | None = None) -> dict:
    meta = job.meta
    clips = []
    for c in job.highlights():
        if indices and c["index"] not in indices:
            continue
        srt = job.clip_dir(c["index"]) / "legendas.srt"
        clips.append({**c, "srt": str(srt) if srt.exists() else None})
    return {
        "project": "VideoCut",
        "job_id": job.id,
        "source_video": str(Path(meta["video"]).resolve()),
        "fps": meta.get("fps"),
        "clips": clips,
    }


def send_to_davinci(job: Job, settings: Settings, indices: list[int] | None = None) -> dict:
    manifest = build_manifest(job, indices)
    resolve = resolve_bridge.connect_external()
    if resolve is not None:
        created = resolve_bridge.import_manifest(resolve, manifest)
        return {"mode": "direto (Studio)", "timelines": created}

    path = queue_dir(settings) / f"{job.id}_{int(time.time())}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    script = install_menu_script(settings)
    return {
        "mode": "fila (DaVinci gratuito)",
        "manifest": str(path),
        "instrucoes": "No DaVinci Resolve: Workspace > Scripts > VideoCut",
        "script": str(script),
    }

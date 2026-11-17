"""Ponte com o DaVinci Resolve. SÓ usa a biblioteca padrão.

Este arquivo roda em dois lugares:
  1. Dentro do DaVinci (Workspace > Scripts > VideoCut), funciona na versão GRATUITA.
  2. Fora do DaVinci, pelo videocut/MCP, só funciona no DaVinci Resolve Studio.

Ele lê manifestos JSON da fila (jobs/_davinci_queue) e cria, para cada corte:
  - timeline "VC NN Título (final)": o vídeo já editado pelo Remotion;
  - timeline "VC NN Título (bruto)": o trecho original, 1080x1920, para você reeditar.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

LIB_CANDIDATES = [
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    r"D:\fusionscript.dll",
    r"D:\DaVinci Resolve\fusionscript.dll",
]


def connect_external(lib_path: str | None = None):
    """Conecta de fora do Resolve (requer Studio). Retorna None se não conseguir."""
    api = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                       "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting")
    lib = lib_path or os.environ.get("RESOLVE_SCRIPT_LIB") or next(
        (c for c in LIB_CANDIDATES if os.path.exists(c)), LIB_CANDIDATES[0])
    os.environ["RESOLVE_SCRIPT_API"] = api
    os.environ["RESOLVE_SCRIPT_LIB"] = lib
    modules = os.path.join(api, "Modules")
    if modules not in sys.path:
        sys.path.append(modules)
    try:
        import DaVinciResolveScript as dvr  # type: ignore
        return dvr.scriptapp("Resolve")
    except Exception:
        return None


def import_queue(resolve, queue_dir: Path) -> list[str]:
    done_dir = queue_dir / "importados"
    done_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for manifest in sorted(queue_dir.glob("*.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        created += import_manifest(resolve, data)
        shutil.move(str(manifest), str(done_dir / manifest.name))
    return created


def import_manifest(resolve, data: dict) -> list[str]:
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None or (data.get("project") and project.GetName() != data["project"]):
        project = pm.LoadProject(data["project"]) or pm.CreateProject(data["project"]) or pm.GetCurrentProject()
    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()
    folder = media_pool.AddSubFolder(root, data["job_id"][:60]) or root
    media_pool.SetCurrentFolder(folder)

    source_item = None
    if data.get("source_video"):
        imported = media_pool.ImportMedia([data["source_video"]]) or []
        source_item = imported[0] if imported else None

    created = []
    for clip in data["clips"]:
        base = f"VC {clip['index']:02d} {clip['title'][:40]}"

        if clip.get("output") and os.path.exists(clip["output"]):
            items = media_pool.ImportMedia([clip["output"]]) or []
            if items:
                tl = media_pool.CreateEmptyTimeline(base + " (final)")
                if tl:
                    _vertical(tl)
                    project.SetCurrentTimeline(tl)
                    media_pool.AppendToTimeline(items)
                    created.append(tl.GetName())

        if source_item is not None:
            fps = float(source_item.GetClipProperty("FPS") or data.get("fps") or 30)
            tl = media_pool.CreateEmptyTimeline(base + " (bruto)")
            if tl:
                _vertical(tl)
                project.SetCurrentTimeline(tl)
                media_pool.AppendToTimeline([{
                    "mediaPoolItem": source_item,
                    "startFrame": int(clip["start"] * fps),
                    "endFrame": int(clip["end"] * fps),
                }])
                if clip.get("srt") and os.path.exists(clip["srt"]):
                    try:
                        tl.ImportIntoTimeline(clip["srt"], {})
                    except Exception:
                        pass
                tl.AddMarker(0, "Yellow", clip["title"][:60], clip.get("reason", ""), 1, "")
                created.append(tl.GetName())
    return created


def _vertical(timeline) -> None:
    timeline.SetSetting("useCustomSettings", "1")
    timeline.SetSetting("timelineResolutionWidth", "1080")
    timeline.SetSetting("timelineResolutionHeight", "1920")
    timeline.SetSetting("timelineOutputResolutionWidth", "1080")
    timeline.SetSetting("timelineOutputResolutionHeight", "1920")

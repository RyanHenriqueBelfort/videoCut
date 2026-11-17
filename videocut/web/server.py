"""Servidor da interface gráfica (FastAPI). Rode com `videocut ui`."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import get_settings
from ..jobs import Job, list_jobs
from .tasks import TaskManager

STATIC = Path(__file__).parent / "static"
S = get_settings()
TM = TaskManager()
app = FastAPI(title="VideoCut")


# ------------------------------------------------------------------ helpers
def _job(job_id: str) -> Job:
    if "/" in job_id or "\\" in job_id or job_id.startswith(".") or not (S.workdir / job_id / "job.json").exists():
        raise HTTPException(404, f"Vídeo '{job_id}' não encontrado")
    return Job(S, job_id)


def _media_url(job: Job, path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        rel = p.resolve().relative_to(job.dir.resolve()).as_posix()
    except ValueError:
        return None
    return f"/media/{job.id}/{rel}?v={int(p.stat().st_mtime)}"


def _clip_view(job: Job, c: dict) -> dict:
    d = job.dir / "clips" / f"{c['index']:02d}"
    out = dict(c)
    out["output_url"] = _media_url(job, c.get("output"))
    out["hook_audio_url"] = _media_url(job, d / "public" / "hook.wav")
    out["has_dub"] = (d / "public" / "dub.wav").exists()
    out["duration"] = round(c["end"] - c["start"], 2)
    return out


def _job_view(job: Job, full: bool = True) -> dict:
    meta = job.meta
    view = {
        "id": job.id,
        "title": meta.get("title") or job.id,
        "source": meta.get("source"),
        "duration": meta.get("duration"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "audio_only": meta.get("audio_only", False),
        "transcribed": job.transcript_path.exists(),
        "thumb": f"/api/jobs/{job.id}/frame?t={round((meta.get('duration') or 10) * 0.1, 1)}",
        "busy": bool(TM.active_for(job.id)),
    }
    clips = job.highlights()
    view["clip_count"] = len(clips)
    if full:
        view["clips"] = [_clip_view(job, c) for c in clips]
        view["language"] = job.transcript().get("language") if view["transcribed"] else None
    return view


def _open_in_explorer(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ------------------------------------------------------------------ status
@app.get("/api/status")
def status() -> dict:
    from ..claude_select import find_claude
    from ..davinci import menu_script_path, queue_dir

    vs_ok = False
    try:
        vs_ok = httpx.get(S.voicestudio_url.rstrip("/") + "/.well-known/voicestudio-speech", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        pass
    claude = find_claude()
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    return {
        "selector": S.selector,
        "claude": {"ok": bool(claude), "path": claude, "model": S.claude_model or "padrão da conta"},
        "whisper": {"model": S.whisper_model, "device": S.whisper_device},
        "voicestudio": {"ok": vs_ok, "url": S.voicestudio_url},
        "remotion": {"ok": bool(npx) and (S.remotion_dir / "node_modules").exists()},
        "davinci": {"ok": menu_script_path().exists(),
                    "pending": len(list(queue_dir(S).glob("*.json")))},
        "clip_range": [S.min_clip_sec, S.max_clip_sec],
    }


# ------------------------------------------------------------------ vídeos
class NewJob(BaseModel):
    source: str
    max_clips: int = 5
    instructions: str = ""


def _start_analysis(source: str, max_clips: int, instructions: str) -> dict:
    from ..pipeline import analyze

    def run():
        job = analyze(source, S, max_clips=max_clips, instructions=instructions)
        return {"job_id": job.id, "clips": len(job.highlights())}

    label = source if len(source) < 70 else "…" + source[-67:]
    task = TM.submit("analyze", f"Processar {label}", run)
    return {"task": task.to_dict()}


@app.post("/api/jobs")
def create_job(body: NewJob) -> dict:
    src = body.source.strip().strip('"')
    if not src:
        raise HTTPException(400, "Informe um link ou caminho de arquivo")
    if not src.lower().startswith(("http://", "https://")) and not Path(src).exists():
        raise HTTPException(400, f"Arquivo não encontrado: {src}")
    return _start_analysis(src, body.max_clips, body.instructions)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), max_clips: int = Form(5), instructions: str = Form("")) -> dict:
    up = S.workdir / "_uploads"
    up.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "video.mp4").name
    dest = up / name
    with dest.open("wb") as fh:
        while chunk := await file.read(8 * 1024 * 1024):
            fh.write(chunk)
    return _start_analysis(str(dest), max_clips, instructions)


@app.get("/api/jobs")
def jobs() -> list[dict]:
    out = []
    for meta in list_jobs(S):
        try:
            out.append(_job_view(Job(S, meta["id"]), full=False))
        except Exception:  # noqa: BLE001 - job corrompido não derruba a lista
            continue
    return sorted(out, key=lambda j: -(S.workdir / j["id"] / "job.json").stat().st_mtime)


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    return _job_view(_job(job_id))


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job = _job(job_id)
    if TM.active_for(job_id):
        raise HTTPException(409, "Há tarefas rodando para este vídeo")
    shutil.rmtree(job.dir, ignore_errors=True)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/transcript")
def transcript(job_id: str) -> dict:
    job = _job(job_id)
    if not job.transcript_path.exists():
        return {"segments": []}
    t = job.transcript()
    return {"language": t.get("language"),
            "segments": [{"i": i, "start": s["start"], "end": s["end"], "text": s["text"]}
                         for i, s in enumerate(t["segments"])]}


@app.get("/api/jobs/{job_id}/source")
def source_video(job_id: str) -> FileResponse:
    job = _job(job_id)
    if not job.video_path.exists():
        raise HTTPException(404, "Vídeo original não encontrado")
    return FileResponse(job.video_path)


@app.get("/api/jobs/{job_id}/frame")
def frame(job_id: str, t: float = 0) -> FileResponse:
    from ..media import grab_frame

    job = _job(job_id)
    cache = job.dir / "frames"
    cache.mkdir(exist_ok=True)
    out = cache / f"{t:.1f}.jpg"
    if not out.exists():
        try:
            grab_frame(job.video_path, max(0.0, t), out)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"Não foi possível extrair o quadro: {e}")
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


@app.post("/api/jobs/{job_id}/open")
def open_folder(job_id: str, clip: int | None = None) -> dict:
    job = _job(job_id)
    path = job.dir / "clips" / f"{clip:02d}" if clip else job.dir
    _open_in_explorer(path if path.exists() else job.dir)
    return {"ok": True}


class SelectBody(BaseModel):
    max_clips: int = 5
    instructions: str = ""
    replace: bool = True


@app.post("/api/jobs/{job_id}/select")
def select(job_id: str, body: SelectBody) -> dict:
    from ..pipeline import select_clips

    job = _job(job_id)
    if not job.transcript_path.exists():
        raise HTTPException(409, "O vídeo ainda não foi transcrito")
    task = TM.submit("select", "Claude escolhendo cortes", lambda: len(select_clips(
        job, S, max_clips=body.max_clips, instructions=body.instructions, replace=body.replace)),
        job_id=job_id, lane="light")
    return {"task": task.to_dict()}


@app.post("/api/jobs/{job_id}/render")
def render_all(job_id: str) -> dict:
    job = _job(job_id)
    tasks = [_queue_render(job, c["index"]).to_dict() for c in job.highlights()]
    return {"tasks": tasks}


@app.post("/api/jobs/{job_id}/davinci")
def davinci(job_id: str) -> dict:
    from ..davinci import send_to_davinci

    job = _job(job_id)
    task = TM.submit("davinci", "Enviar ao DaVinci", lambda: send_to_davinci(job, S), job_id=job_id, lane="light")
    return {"task": task.to_dict()}


# ------------------------------------------------------------------ cortes
class ClipBody(BaseModel):
    start: float | None = None
    end: float | None = None
    title: str | None = None
    hook: str | None = None
    use_hook: bool | None = None
    caption_style: dict[str, Any] | None = None


@app.post("/api/jobs/{job_id}/clips")
def add_clip(job_id: str, body: ClipBody) -> dict:
    from ..render import add_manual_clip

    job = _job(job_id)
    if body.start is None or body.end is None or body.end <= body.start:
        raise HTTPException(400, "Informe início e fim válidos")
    c = add_manual_clip(job, body.start, body.end, body.title or "", body.hook or "")
    return _clip_view(job, c)


@app.put("/api/jobs/{job_id}/clips/{index}")
def edit_clip(job_id: str, index: int, body: ClipBody) -> dict:
    from ..render import update_clip

    job = _job(job_id)
    changes = body.model_dump(exclude_none=True)
    if "start" in changes or "end" in changes:
        cur = next(c for c in job.highlights() if c["index"] == index)
        start, end = changes.get("start", cur["start"]), changes.get("end", cur["end"])
        if end - start < 1:
            raise HTTPException(400, "O corte precisa ter pelo menos 1 segundo")
        changes["start"], changes["end"] = round(max(0.0, start), 3), round(end, 3)
    try:
        return _clip_view(job, update_clip(job, index, **changes))
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/jobs/{job_id}/clips/{index}")
def remove_clip(job_id: str, index: int) -> dict:
    from ..render import delete_clip

    delete_clip(_job(job_id), index)
    return {"ok": True}


def _queue_render(job: Job, index: int):
    from ..render import render_clip
    return TM.submit("render", f"Renderizar corte {index}", lambda: str(render_clip(job, index, S)),
                     job_id=job.id, clip=index)


@app.post("/api/jobs/{job_id}/clips/{index}/render")
def render_one(job_id: str, index: int) -> dict:
    return {"task": _queue_render(_job(job_id), index).to_dict()}


class HookBody(BaseModel):
    text: str | None = None
    voice: str | None = None
    language: str | None = None
    render: bool = True


@app.post("/api/jobs/{job_id}/clips/{index}/hook")
def hook(job_id: str, index: int, body: HookBody) -> dict:
    from ..pipeline import add_hook_narration

    job = _job(job_id)
    task = TM.submit("hook", f"Narrar gancho do corte {index}",
                     lambda: str(add_hook_narration(job, index, S, text=body.text, profile_id=body.voice or None,
                                                    language=body.language or None)),
                     job_id=job_id, clip=index, lane="light")
    out = {"task": task.to_dict()}
    if body.render:
        out["render"] = _queue_render(job, index).to_dict()
    return out


class DubBody(BaseModel):
    language: str
    tts_language: str | None = None
    voice: str | None = None
    render: bool = True


@app.post("/api/jobs/{job_id}/clips/{index}/dub")
def dub(job_id: str, index: int, body: DubBody) -> dict:
    from ..pipeline import dub as _dub

    job = _job(job_id)
    task = TM.submit("dub", f"Dublar corte {index} ({body.language})",
                     lambda: str(_dub(job, index, S, body.language, body.tts_language, profile_id=body.voice or None)),
                     job_id=job_id, clip=index)
    out = {"task": task.to_dict()}
    if body.render:
        out["render"] = _queue_render(job, index).to_dict()
    return out


@app.delete("/api/jobs/{job_id}/clips/{index}/dub")
def remove_dub(job_id: str, index: int) -> dict:
    job = _job(job_id)
    clips = job.highlights()
    for c in clips:
        if c["index"] == index:
            c.pop("dub", None)
            c["dirty"] = bool(c.get("output"))
    job.save_highlights(clips)
    return {"ok": True}


# ------------------------------------------------------------------ tarefas e VoiceStudio
@app.get("/api/tasks")
def tasks(job_id: str | None = None) -> list[dict]:
    return TM.list(job_id)


@app.get("/api/tasks/{task_id}")
def task(task_id: int) -> dict:
    t = TM.tasks.get(task_id)
    if not t:
        raise HTTPException(404, "Tarefa não encontrada")
    return t.to_dict(with_log=True)


@app.get("/api/voices")
def voices() -> JSONResponse:
    from ..voicestudio import VoiceStudio
    try:
        data = VoiceStudio(S).list_voices()
        items = data if isinstance(data, list) else data.get("voices", [])
        return JSONResponse([{"id": v.get("id"), "name": v.get("name"), "language": v.get("language")}
                             for v in items if isinstance(v, dict)])
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


# ------------------------------------------------------------------ arquivos
@app.get("/media/{job_id}/{path:path}")
def media(job_id: str, path: str) -> FileResponse:
    job = _job(job_id)
    target = (job.dir / path).resolve()
    if not str(target).startswith(str(job.dir.resolve())) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


def run(open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    url = f"http://127.0.0.1:{S.ui_port}"
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"VideoCut rodando em {url}  (Ctrl+C para sair)")
    uvicorn.run(app, host="127.0.0.1", port=S.ui_port, log_level="warning")

"""Entrada: link do YouTube (ou qualquer site suportado pelo yt-dlp) ou arquivo local."""
from __future__ import annotations

import re
from pathlib import Path

from .config import Settings
from .jobs import Job, job_id_for
from .media import audio_to_video, extract_audio, ffmpeg_exe, probe_video

URL_RE = re.compile(r"^https?://", re.I)
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def ingest(source: str, settings: Settings) -> Job:
    if URL_RE.match(source):
        job = _download(source, settings)
    else:
        job = _local(Path(source).expanduser().resolve(), settings)

    if not job.audio_path.exists():
        extract_audio(job.video_path, job.audio_path)
    return job


def _download(url: str, settings: Settings) -> Job:
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    job = Job(settings, job_id_for(info.get("id") or url, info.get("title")))
    if job.meta.get("video") and Path(job.meta["video"]).exists():
        return job

    opts = {
        "outtmpl": str(job.dir / "source.%(ext)s"),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "ffmpeg_location": ffmpeg_exe(),
        "quiet": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    video = next(job.dir.glob("source.*"))
    job.update_meta(id=job.id, source=url, title=info.get("title"), video=str(video), **probe_video(video))
    return job


def _local(path: Path, settings: Settings) -> Job:
    if not path.exists():
        raise FileNotFoundError(path)
    job = Job(settings, job_id_for(str(path), path.stem))
    if job.meta.get("video") and Path(job.meta["video"]).exists():
        return job

    video = path
    audio_only = path.suffix.lower() in AUDIO_EXT
    if audio_only:
        video = audio_to_video(path, job.dir / "source.mp4")
    job.update_meta(
        id=job.id, source=str(path), title=path.stem, video=str(video), audio_only=audio_only, **probe_video(video)
    )
    return job

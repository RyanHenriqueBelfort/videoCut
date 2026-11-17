"""Fila de tarefas em segundo plano para a interface.

Duas filas, cada uma com um worker:
  - "heavy": download, transcrição, render, dublagem (usam GPU/CPU pesado; uma por vez);
  - "light": seleção com Claude, narração do gancho, envio ao DaVinci.

Tudo que o pipeline imprime (print) numa tarefa vai para o log dela, e
`progress.report()` atualiza etapa e porcentagem.
"""
from __future__ import annotations

import io
import itertools
import queue
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from ..progress import set_reporter

_counter = itertools.count(1)


@dataclass
class Task:
    kind: str
    label: str
    job_id: str | None = None
    clip: int | None = None
    lane: str = "heavy"
    id: int = field(default_factory=lambda: next(_counter))
    status: str = "queued"  # queued | running | done | error
    stage: str = "Na fila"
    progress: float | None = None
    log: list[str] = field(default_factory=list)
    error: str | None = None
    result: Any = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None

    def to_dict(self, with_log: bool = False) -> dict:
        d = {k: getattr(self, k) for k in ("id", "kind", "label", "job_id", "clip", "lane", "status",
                                            "stage", "progress", "error", "created", "started", "finished")}
        d["result"] = self.result if isinstance(self.result, (str, int, float, dict, list, type(None))) else str(self.result)
        d["log"] = self.log[-300:] if with_log else self.log[-3:]
        return d


class _ThreadRouter(io.TextIOBase):
    """sys.stdout que manda o que cada thread de tarefa imprime para o log da própria tarefa."""

    def __init__(self, original):
        self.original = original
        self.local = threading.local()

    def write(self, s: str) -> int:
        task: Task | None = getattr(self.local, "task", None)
        if task is None:
            return self.original.write(s)
        buf = getattr(self.local, "buf", "") + s
        *lines, rest = buf.split("\n")
        self.local.buf = rest
        for line in lines:
            if line.strip():
                task.log.append(line.rstrip())
                if len(task.log) > 2000:
                    del task.log[:500]
        return len(s)

    def flush(self) -> None:
        if getattr(self.local, "task", None) is None:
            self.original.flush()

    @property
    def encoding(self):  # type: ignore[override]
        return "utf-8"


class TaskManager:
    def __init__(self) -> None:
        self.tasks: dict[int, Task] = {}
        self.queues = {"heavy": queue.Queue(), "light": queue.Queue()}
        if not isinstance(sys.stdout, _ThreadRouter):
            sys.stdout = _ThreadRouter(sys.stdout)
        self.router: _ThreadRouter = sys.stdout  # type: ignore[assignment]
        for lane, q in self.queues.items():
            threading.Thread(target=self._worker, args=(q,), daemon=True, name=f"videocut-{lane}").start()

    def submit(self, kind: str, label: str, fn: Callable[[], Any], *, job_id: str | None = None,
               clip: int | None = None, lane: str = "heavy") -> Task:
        task = Task(kind=kind, label=label, job_id=job_id, clip=clip, lane=lane)
        self.tasks[task.id] = task
        self.queues[lane].put((task, fn))
        self._prune()
        return task

    def list(self, job_id: str | None = None) -> list[dict]:
        tasks = [t for t in self.tasks.values() if job_id is None or t.job_id == job_id]
        return [t.to_dict() for t in sorted(tasks, key=lambda t: -t.id)]

    def active_for(self, job_id: str) -> list[Task]:
        return [t for t in self.tasks.values() if t.job_id == job_id and t.status in ("queued", "running")]

    def _prune(self, keep: int = 200) -> None:
        done = [t for t in self.tasks.values() if t.status in ("done", "error")]
        for t in sorted(done, key=lambda t: t.id)[:-keep]:
            self.tasks.pop(t.id, None)

    def _worker(self, q: queue.Queue) -> None:
        while True:
            task, fn = q.get()
            task.status, task.started, task.stage = "running", time.time(), "Iniciando..."

            def reporter(stage: str | None, fraction: float | None, task=task) -> None:
                if stage:
                    task.stage = stage
                if fraction is not None:
                    task.progress = fraction

            self.router.local.task = task
            set_reporter(reporter)
            try:
                task.result = fn()
                task.status, task.stage, task.progress = "done", "Concluído", 1.0
            except Exception as e:  # noqa: BLE001 - erro vai para a interface
                task.status, task.error = "error", str(e)
                task.stage = "Erro"
                task.log.extend(traceback.format_exc().splitlines()[-25:])
            finally:
                set_reporter(None)
                self.router.local.task = None
                self.router.local.buf = ""
                task.finished = time.time()
                q.task_done()

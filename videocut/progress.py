"""Progresso das tarefas longas, para a interface mostrar barras e etapas.

O código do pipeline chama `report(...)`; se não houver uma tarefa ativa na
thread atual (CLI, MCP), não faz nada.
"""
from __future__ import annotations

import threading
from typing import Callable

_local = threading.local()

Reporter = Callable[[str | None, float | None], None]


def set_reporter(fn: Reporter | None) -> None:
    _local.reporter = fn


def report(stage: str | None = None, fraction: float | None = None) -> None:
    fn: Reporter | None = getattr(_local, "reporter", None)
    if fn is not None:
        fn(stage, None if fraction is None else max(0.0, min(1.0, fraction)))

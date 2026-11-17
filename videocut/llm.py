"""Cliente mínimo do Ollama com saída JSON estruturada."""
from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings


class LLMError(RuntimeError):
    pass


def chat_json(settings: Settings, system: str, user: str, schema: dict, temperature: float = 0.3) -> Any:
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": schema,
        "options": {"temperature": temperature, "num_ctx": settings.ollama_ctx},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    try:
        r = httpx.post(settings.ollama_url.rstrip("/") + "/api/chat", json=payload, timeout=600)
    except httpx.ConnectError as e:
        raise LLMError(
            f"Ollama não está rodando em {settings.ollama_url}. Instale em https://ollama.com e rode "
            f"`ollama pull {settings.ollama_model}`."
        ) from e
    if r.status_code == 404:
        raise LLMError(f"Modelo '{settings.ollama_model}' não encontrado. Rode `ollama pull {settings.ollama_model}`.")
    r.raise_for_status()
    content = r.json()["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMError(f"Resposta do modelo não é JSON válido: {content[:500]}") from e

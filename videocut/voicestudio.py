"""Cliente do VoiceStudio via servidor MCP dele (http://localhost:3900/mcp/).

O VoiceStudio expõe TTS e clonagem de voz como ferramentas MCP
(generate_speech, clone_voice, list_voices, list_languages, check_health...).
Os nomes dos argumentos são lidos do `tools/list` em tempo de execução, então
o cliente se adapta a mudanças de versão do VoiceStudio.
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx
from mcp import Client

from .config import Settings


class VoiceStudioError(RuntimeError):
    pass


class VoiceStudio:
    def __init__(self, settings: Settings):
        self.base = settings.voicestudio_url.rstrip("/")
        self.default_profile = settings.voicestudio_profile
        self._schemas: dict[str, dict] | None = None

    # ------------------------------------------------------------------ MCP
    async def _session_call(self, fn):
        try:
            async with Client(self.base + "/mcp/", read_timeout_seconds=600) as client:
                return await fn(client)
        except Exception as e:  # erros de conexão chegam embrulhados em ExceptionGroup/MCPError
            if "connect" in repr(e).lower() or isinstance(e, OSError):
                raise VoiceStudioError(
                    f"VoiceStudio não respondeu em {self.base}. Abra o app VoiceStudio e espere a instalação terminar."
                ) from e
            raise

    def tools(self) -> dict[str, dict]:
        if self._schemas is None:
            async def go(c: Client):
                res = await c.list_tools()
                return {t.name: (t.input_schema if hasattr(t, "input_schema") else t.inputSchema) or {}
                        for t in res.tools}
            self._schemas = asyncio.run(self._session_call(go))
        return self._schemas

    def call(self, tool: str, args: dict[str, Any]) -> Any:
        async def go(c: Client):
            return await c.call_tool(tool, args)
        res = asyncio.run(self._session_call(go))
        text = "".join(getattr(c, "text", "") for c in res.content)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"text": text}
        is_error = getattr(res, "is_error", None) or getattr(res, "isError", False)
        if is_error or (isinstance(data, dict) and data.get("error")):
            detail = (data.get("error") if isinstance(data, dict) else None) or text
            if "Licence not accepted" in detail or "License not accepted" in detail:
                detail += "\n-> Abra o VoiceStudio > Model Catalog e aceite a licença do modelo."
            raise VoiceStudioError(f"{tool}: {detail}")
        return data

    def _arg(self, tool: str, *candidates: str, contains: str | None = None) -> str | None:
        props = self.tools().get(tool, {}).get("properties", {})
        for c in candidates:
            if c in props:
                return c
        if contains:
            for name in props:
                if contains in name:
                    return name
        return None

    # ------------------------------------------------------------------ API alto nível
    def health(self) -> Any:
        return self.call("check_health", {})

    def list_voices(self) -> Any:
        return self.call("list_voices", {})

    def list_languages(self) -> Any:
        return self.call("list_languages", {})

    def generate_speech(self, text: str, out: Path, profile_id: str | None = None,
                        language: str | None = None) -> Path:
        args: dict[str, Any] = {self._arg("generate_speech", "text", "input", "prompt") or "text": text}
        profile_id = profile_id or self.default_profile
        if profile_id:
            args[self._arg("generate_speech", "profile_id", "voice_id", "voice") or "profile_id"] = profile_id
        if language:
            args[self._arg("generate_speech", "language", "lang") or "language"] = language
        data = self.call("generate_speech", args)
        return self._save_audio(data, out)

    def clone_voice(self, ref_audio: Path, name: str, ref_text: str | None = None) -> str:
        b64_key = self._arg("clone_voice", "audio_base64", "ref_audio_base64", contains="base64")
        args: dict[str, Any] = {}
        if b64_key:
            args[b64_key] = base64.b64encode(ref_audio.read_bytes()).decode()
        else:
            args[self._arg("clone_voice", "ref_audio_path", contains="path") or "ref_audio_path"] = str(ref_audio)
        name_key = self._arg("clone_voice", "name", "profile_name", "label")
        if name_key:
            args[name_key] = name
        text_key = self._arg("clone_voice", "ref_text", "transcript", "text")
        if text_key and ref_text:
            args[text_key] = ref_text
        data = self.call("clone_voice", args)
        pid = data.get("profile_id") or data.get("id") if isinstance(data, dict) else None
        if not pid:
            raise VoiceStudioError(f"clone_voice não retornou profile_id: {str(data)[:300]}")
        return pid

    def _save_audio(self, data: Any, out: Path) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, dict):
            if data.get("wav_base64") or data.get("audio_base64"):
                out.write_bytes(base64.b64decode(data.get("wav_base64") or data.get("audio_base64")))
                return out
            if data.get("output_path") and Path(data["output_path"]).exists():
                out.write_bytes(Path(data["output_path"]).read_bytes())
                return out
            if data.get("audio_url"):
                url = data["audio_url"]
                url = url if url.startswith("http") else self.base + "/" + url.lstrip("/")
                r = httpx.get(url, timeout=120)
                r.raise_for_status()
                out.write_bytes(r.content)
                return out
        raise VoiceStudioError(f"Resposta de generate_speech sem áudio: {str(data)[:300]}")

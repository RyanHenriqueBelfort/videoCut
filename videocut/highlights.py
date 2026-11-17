"""Seleção dos momentos interessantes com LLM local.

O modelo recebe a transcrição numerada por linha (segmento) e devolve intervalos
de linhas. Usar índices em vez de timestamps deixa a resposta muito mais confiável
em modelos pequenos; os tempos exatos vêm da transcrição.
"""
from __future__ import annotations

from .config import Settings
from .jobs import Job
from .llm import chat_json

SYSTEM = """Você é um editor de vídeos virais para TikTok, Reels e YouTube Shorts.
Sua tarefa é encontrar, numa transcrição, trechos que funcionem SOZINHOS como vídeos curtos.

Um bom corte:
- começa com um gancho forte nos primeiros 3 segundos (pergunta, afirmação polêmica, número, história);
- tem começo, meio e fim: a ideia se completa dentro do trecho, sem depender do resto do vídeo;
- tem emoção, humor, revelação, dica prática, opinião forte ou momento surpreendente;
- NÃO começa no meio de uma frase e NÃO termina antes da conclusão.

Responda apenas com JSON no formato pedido. Títulos e ganchos no idioma da transcrição."""

USER_TMPL = """Transcrição (cada linha: [L<número> mm:ss] texto):

{lines}

Escolha até {k} cortes entre as linhas L{first} e L{last}.
Cada corte deve durar entre {min_s:.0f} e {max_s:.0f} segundos.
Para cada corte informe:
- start_line / end_line: números das linhas de início e fim (inclusive)
- title: título curto e chamativo (máx. 60 caracteres)
- hook: frase curta de gancho para narrar na abertura (máx. 15 palavras)
- reason: por que esse trecho prende a atenção
- score: nota de 1 a 100 do potencial viral"""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "integer"},
                },
                "required": ["start_line", "end_line", "title", "hook", "reason", "score"],
            },
        }
    },
    "required": ["clips"],
}


def _fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def _chunks(segments: list[dict], max_chars: int = 12000, overlap: int = 12):
    start = 0
    while start < len(segments):
        size, end = 0, start
        while end < len(segments) and size < max_chars:
            size += len(segments[end]["text"]) + 16
            end += 1
        yield start, end
        if end >= len(segments):
            break
        start = max(end - overlap, start + 1)


EDITORIAL_GUIDE = SYSTEM.split("\n\n", 1)[1].split("\n\nResponda")[0]


def transcript_lines(job: Job, start: float = 0, end: float | None = None) -> str:
    """Transcrição numerada '[L12 03:21-03:27] texto' (formato usado pelo agente para escolher cortes)."""
    segs = job.transcript()["segments"]
    return "\n".join(
        f"[L{i} {_fmt(s['start'])}-{_fmt(s['end'])}] {s['text']}"
        for i, s in enumerate(segs)
        if s["end"] >= start and (end is None or s["start"] <= end)
    )


def snap_to_segments(segments: list[dict], start: float, end: float) -> tuple[float, float, int, int]:
    """Ajusta início/fim para começar e terminar em frases inteiras da transcrição."""
    s = min(range(len(segments)), key=lambda i: abs(segments[i]["start"] - start))
    e = min(range(s, len(segments)), key=lambda i: abs(segments[i]["end"] - end))
    return (round(max(0.0, segments[s]["start"] - 0.15), 3), round(segments[e]["end"] + 0.35, 3), s, e)


def save_agent_clips(job: Job, clips: list[dict], snap: bool = True, replace: bool = True) -> list[dict]:
    """Salva cortes escolhidos por um agente (Claude via MCP).

    Cada item: start, end (segundos) OU start_line, end_line; title; hook; reason; score.
    """
    segments = job.transcript()["segments"]
    if replace:
        job.reset_clips()
    out = [] if replace else job.highlights()
    next_index = max((c["index"] for c in out), default=0) + 1
    new = []
    for c in clips:
        if "start_line" in c and "end_line" in c and c["start_line"] is not None:
            s, e = int(c["start_line"]), int(c["end_line"])
            start, end = segments[s]["start"] - 0.15, segments[e]["end"] + 0.35
        elif snap:
            start, end, s, e = snap_to_segments(segments, float(c["start"]), float(c["end"]))
        else:
            start, end, s, e = float(c["start"]), float(c["end"]), None, None
        new.append({
            "start": round(max(0.0, start), 3),
            "end": round(end, 3),
            "start_line": s,
            "end_line": e,
            "title": str(c.get("title", "")).strip(),
            "hook": str(c.get("hook") or c.get("title", "")).strip(),
            "reason": str(c.get("reason", "")).strip(),
            "score": int(c.get("score") or 0),
            "use_hook": bool(c.get("use_hook", False)),
        })
    # Índices estáveis: cortes existentes mantêm o número (a pasta clips/NN é deles).
    for c in sorted(new, key=lambda c: c["start"]):
        c["index"] = next_index
        next_index += 1
    out = sorted(out + new, key=lambda c: c["start"])
    job.save_highlights(out)
    return out


def find_highlights(job: Job, settings: Settings, max_clips: int = 5, force: bool = False) -> list[dict]:
    if job.highlights_path.exists() and not force:
        return job.highlights()

    segments = job.transcript()["segments"]
    if not segments:
        raise RuntimeError("Transcrição vazia.")

    candidates: list[dict] = []
    for a, b in _chunks(segments):
        lines = "\n".join(f"[L{i} {_fmt(segments[i]['start'])}] {segments[i]['text']}" for i in range(a, b))
        per_chunk = max(2, min(max_clips, 4))
        print(f"[ia] analisando linhas {a}-{b - 1} com {settings.ollama_model}...", flush=True)
        resp = chat_json(
            settings, SYSTEM,
            USER_TMPL.format(lines=lines, k=per_chunk, first=a, last=b - 1,
                             min_s=settings.min_clip_sec, max_s=settings.max_clip_sec),
            SCHEMA,
        )
        for c in resp.get("clips", []):
            clip = _to_times(c, segments, a, b - 1, settings)
            if clip:
                candidates.append(clip)

    clips = _dedupe(sorted(candidates, key=lambda c: -c["score"]))[:max_clips]
    clips.sort(key=lambda c: c["start"])
    job.reset_clips()
    for i, c in enumerate(clips, 1):
        c["index"] = i
    job.save_highlights(clips)
    return clips


def _to_times(c: dict, segments: list[dict], lo: int, hi: int, settings: Settings) -> dict | None:
    s = max(lo, min(hi, int(c["start_line"])))
    e = max(s, min(hi, int(c["end_line"])))

    # Estende o fim até atingir a duração mínima; encolhe se passar da máxima.
    while e < len(segments) - 1 and segments[e]["end"] - segments[s]["start"] < settings.min_clip_sec:
        e += 1
    while e > s and segments[e]["end"] - segments[s]["start"] > settings.max_clip_sec:
        e -= 1
    # Prefere terminar numa frase completa.
    for k in range(e, max(s, e - 3), -1):
        if segments[k]["text"].rstrip().endswith((".", "!", "?", "…")):
            if segments[k]["end"] - segments[s]["start"] >= settings.min_clip_sec * 0.8:
                e = k
            break

    start, end = segments[s]["start"], segments[e]["end"]
    if end - start < settings.min_clip_sec * 0.6:
        return None
    return {
        "start": round(max(0.0, start - 0.15), 3),
        "end": round(end + 0.35, 3),
        "start_line": s,
        "end_line": e,
        "title": c["title"].strip(),
        "hook": c["hook"].strip(),
        "reason": c["reason"].strip(),
        "score": int(c["score"]),
    }


def _dedupe(clips: list[dict], max_overlap: float = 0.3) -> list[dict]:
    kept: list[dict] = []
    for c in clips:
        ok = True
        for k in kept:
            inter = min(c["end"], k["end"]) - max(c["start"], k["start"])
            if inter > 0 and inter / min(c["end"] - c["start"], k["end"] - k["start"]) > max_overlap:
                ok = False
                break
        if ok:
            kept.append(c)
    return kept


def clip_words(job: Job, clip: dict) -> list[dict]:
    """Palavras do corte com tempos relativos ao início do corte."""
    out = []
    for seg in job.transcript()["segments"]:
        if seg["end"] < clip["start"] or seg["start"] > clip["end"]:
            continue
        for w in seg["words"]:
            if clip["start"] <= w["start"] < clip["end"]:
                out.append({
                    "start": round(w["start"] - clip["start"], 3),
                    "end": round(min(w["end"], clip["end"]) - clip["start"], 3),
                    "word": w["word"],
                })
    return out


def clip_segments(job: Job, clip: dict) -> list[dict]:
    """Segmentos do corte com tempos relativos (usado na dublagem)."""
    out = []
    for seg in job.transcript()["segments"]:
        if seg["end"] <= clip["start"] or seg["start"] >= clip["end"]:
            continue
        out.append({
            "start": round(max(seg["start"], clip["start"]) - clip["start"], 3),
            "end": round(min(seg["end"], clip["end"]) - clip["start"], 3),
            "text": seg["text"],
        })
    return out

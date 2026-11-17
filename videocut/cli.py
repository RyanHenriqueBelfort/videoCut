from __future__ import annotations

import argparse
import json
import sys

from .config import get_settings
from .jobs import Job, list_jobs


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="videocut", description="Cortes automáticos com IA local")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("run", help="Pipeline completo: baixar, transcrever, escolher cortes e renderizar")
    a.add_argument("source", help="Link do YouTube ou caminho de arquivo (mp4, mov, mkv, mp3...)")
    a.add_argument("-n", "--clips", type=int, default=5)
    a.add_argument("--hook", action="store_true", help="Abertura com gancho narrado pelo VoiceStudio")
    a.add_argument("--dub", metavar="IDIOMA", help="Dublar os cortes (ex.: 'inglês', 'espanhol')")
    a.add_argument("--tts-language", help="Código/nome de idioma para o VoiceStudio (ex.: en, pt, es)")
    a.add_argument("--davinci", action="store_true", help="Enviar timelines para o DaVinci Resolve")
    a.add_argument("--no-render", action="store_true")

    a = sub.add_parser("analyze", help="Só transcreve e escolhe os cortes (sem renderizar)")
    a.add_argument("source")
    a.add_argument("-n", "--clips", type=int, default=5)
    a.add_argument("--force", action="store_true", help="Refazer transcrição e seleção")

    a = sub.add_parser("render", help="Renderizar cortes de um job")
    a.add_argument("job")
    a.add_argument("indices", nargs="*", type=int)

    a = sub.add_parser("hook", help="Gerar narração de gancho para um corte")
    a.add_argument("job")
    a.add_argument("index", type=int)
    a.add_argument("--text")
    a.add_argument("--voice", help="profile_id do VoiceStudio")
    a.add_argument("--tts-language")

    a = sub.add_parser("dub", help="Dublar um corte")
    a.add_argument("job")
    a.add_argument("index", type=int)
    a.add_argument("language", help="Idioma de destino, ex.: 'inglês'")
    a.add_argument("--tts-language")
    a.add_argument("--voice", help="profile_id do VoiceStudio (senão clona a voz original)")

    a = sub.add_parser("davinci", help="Enviar cortes de um job para o DaVinci Resolve")
    a.add_argument("job")
    a.add_argument("indices", nargs="*", type=int)

    a = sub.add_parser("ui", help="Abrir a interface gráfica no navegador")
    a.add_argument("--no-browser", action="store_true")

    sub.add_parser("jobs", help="Listar jobs")
    a = sub.add_parser("clips", help="Listar cortes de um job")
    a.add_argument("job")
    sub.add_parser("install-davinci", help="Instalar o script no menu do DaVinci")
    sub.add_parser("voicestudio", help="Testar conexão e listar ferramentas do VoiceStudio")

    args = p.parse_args(argv)
    s = get_settings()

    if args.cmd == "run":
        from .pipeline import run_all
        run_all(args.source, s, max_clips=args.clips, hook=args.hook, dub_to=args.dub,
                tts_language=args.tts_language, davinci=args.davinci, render=not args.no_render)
    elif args.cmd == "analyze":
        from .pipeline import analyze
        job = analyze(args.source, s, max_clips=args.clips, force=args.force)
        if job.highlights():
            _print_clips(job)
        else:
            print(f"\nTranscrição pronta: job {job.id}\nNo Claude Code: /cortar {job.id}")
    elif args.cmd == "render":
        from .render import render_clip
        job = Job(s, args.job)
        for i in args.indices or [c["index"] for c in job.highlights()]:
            print(render_clip(job, i, s))
    elif args.cmd == "hook":
        from .pipeline import add_hook_narration
        print(add_hook_narration(Job(s, args.job), args.index, s, text=args.text,
                                 profile_id=args.voice, language=args.tts_language))
    elif args.cmd == "dub":
        from .pipeline import dub
        print(dub(Job(s, args.job), args.index, s, args.language, args.tts_language, profile_id=args.voice))
    elif args.cmd == "davinci":
        from .davinci import send_to_davinci
        print(json.dumps(send_to_davinci(Job(s, args.job), s, args.indices or None), ensure_ascii=False, indent=2))
    elif args.cmd == "ui":
        from .web.server import run
        run(open_browser=not args.no_browser)
    elif args.cmd == "jobs":
        for j in list_jobs(s):
            print(f"{j['id']:<55} {j['clips']} cortes  {j.get('title', '')}")
    elif args.cmd == "clips":
        _print_clips(Job(s, args.job))
    elif args.cmd == "install-davinci":
        from .davinci import install_menu_script
        print(f"Script instalado em {install_menu_script(s)}\nReinicie o DaVinci e use Workspace > Scripts > VideoCut")
    elif args.cmd == "voicestudio":
        from .voicestudio import VoiceStudio
        vs = VoiceStudio(s)
        print(json.dumps(vs.health(), ensure_ascii=False, indent=2))
        for name, schema in vs.tools().items():
            print(f"- {name}({', '.join(schema.get('properties', {}).keys())})")


def _print_clips(job: Job) -> None:
    print(f"\nJob: {job.id}")
    for c in job.highlights():
        print(f"  [{c['index']}] {c['start']:7.1f}s-{c['end']:7.1f}s  nota {c['score']:3d}  {c['title']}")
        print(f"       gancho: {c['hook']}")


if __name__ == "__main__":
    main()

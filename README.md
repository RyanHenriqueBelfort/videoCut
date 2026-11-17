# VideoCut

Cortes automáticos para Shorts/Reels/TikTok, com o **Claude Code** como editor-chefe:

```
link do YouTube / arquivo
        │
        ▼
  1. ingest        yt-dlp baixa (ou abre o arquivo local; .mp3 vira vídeo com forma de onda)
  2. transcrição   faster-whisper na GPU, com tempo de cada palavra
  3. seleção       o Claude (via MCP, skill /cortar) lê a transcrição e escolhe os cortes
                   (opcional: LLM local via Ollama, VIDEOCUT_SELECTOR=ollama)
  4. enquadramento detecção de rosto (YuNet) → câmera virtual 9:16 suavizada
  5. voz           VoiceStudio (MCP): narração do gancho e dublagem com voz clonada
  6. edição        Remotion renderiza: legendas animadas palavra a palavra + abertura com gancho
  7. DaVinci       timelines "final" e "bruto" (1080x1920) para ajuste manual
```

Tudo também é exposto como **servidor MCP** (`videocut-mcp`), então um agente de IA
(Claude Code, Claude Desktop...) pode operar o sistema: revisar cortes, mudar tempos,
trocar o gancho, dublar, renderizar e mandar para o DaVinci.

## Instalação (uma vez)

1. **Python** – `uv sync --extra gpu`
2. **Remotion** – `cd remotion && npm install`
3. **Claude Code** aberto nesta pasta: ele carrega o `.mcp.json` e a skill `/cortar`.
4. **VoiceStudio** – abra o app, termine a instalação e em **Model Catalog aceite a licença do
   OmniVoice** (sem isso o TTS responde HTTP 403).
5. **DaVinci Resolve** – `uv run videocut install-davinci` e reinicie o DaVinci.
6. Copie `.env.example` para `.env` se quiser mudar modelo, duração dos cortes etc.

## Uso

### Interface gráfica (recomendado)

Dê dois cliques em **`VideoCut.bat`** (ou rode `uv run videocut ui`). O painel abre no navegador
em <http://127.0.0.1:8765>:

1. **Novo vídeo:** cole um link do YouTube, um caminho de arquivo ou arraste o vídeo. Defina
   quantos cortes quer e, se quiser, dê instruções para a IA ("foque nos momentos engraçados").
2. O vídeo é baixado e transcrito na GPU, e o **Claude escolhe os cortes**. Ele usa o Claude Code
   da sua assinatura em modo não interativo, sem chave de API.
3. **Revise cada corte:** assista o trecho no vídeo original, ajuste início e fim (campos ou
   botões de ±½s), edite o título e o gancho e mude cor, tamanho e posição da legenda.
   Também dá para criar cortes à mão pela transcrição: clique em *início* e *fim* numa frase.
4. **Renderizar**, **🎙 Narrar gancho** e **🌐 Dublar** (estes dois precisam do VoiceStudio aberto),
   e **🎬 Enviar ao DaVinci**.

As tarefas aparecem na barra inferior, com progresso e log.

### Pelo chat do Claude Code

No Claude Code, dentro desta pasta:

```
/cortar https://www.youtube.com/watch?v=...
/cortar C:\videos\podcast.mp4 3 cortes, com gancho narrado, e manda pro DaVinci
```

O Claude transcreve, lê o vídeo inteiro, propõe os cortes numa tabela e, depois do seu ok,
narra, renderiza e envia. Para ajustar, é só conversar: "o corte 2 começa cedo demais",
"legenda azul e maior", "dubla o 3 em espanhol".

Pela linha de comando (as etapas que não precisam de IA):

```powershell
uv run videocut analyze "<link ou arquivo>"     # baixa e transcreve
uv run videocut clips <job_id>                   # lista os cortes salvos
uv run videocut render <job_id>                  # renderiza todos os cortes
uv run videocut hook <job_id> 2 --text "Ninguém te conta isso"
uv run videocut dub <job_id> 2 "espanhol" --tts-language es
uv run videocut render <job_id> 2
uv run videocut davinci <job_id>
uv run videocut voicestudio                      # testa a conexão com o VoiceStudio
```

### DaVinci Resolve gratuito × Studio

A versão **gratuita** não aceita controle *externo* por script. Por isso o VideoCut grava os
cortes numa fila e você clica em **Workspace → Scripts → VideoCut** dentro do DaVinci, o que
funciona na versão gratuita. Para cada corte são criadas duas timelines verticais:

- **VC NN … (final)**: o vídeo já editado pelo Remotion;
- **VC NN … (bruto)**: o trecho original sem edição, com marcador e legendas `.srt`, para você
  editar do seu jeito.

Com o **DaVinci Resolve Studio** e "External scripting: Local" ativado nas preferências, o
`videocut davinci` cria as timelines direto, sem clicar no menu.

> Se o menu Scripts não aparecer: o DaVinci precisa de um Python 3 instalado "para todos os
> usuários". Instale pelo python.org marcando *Install for all users*.

### Servidor MCP

O arquivo `.mcp.json` registra dois servidores para o Claude Code: `videocut` e `voicestudio`.
Ferramentas do `videocut`: `analyze_video`, `read_transcript`, `save_clips`, `get_clips`,
`edit_clip`, `narrate_hook`, `dub_clip`, `render`, `send_to_davinci`, `list_videos`,
`voicestudio_voices`. O fluxo editorial está em `.claude/skills/cortar/SKILL.md`.

Para rodar tudo sem o Claude (`videocut run`), instale o Ollama, rode `ollama pull qwen2.5:14b`
e defina `VIDEOCUT_SELECTOR=ollama` no `.env`.

## Estrutura

```
videocut/
  ingest.py        download / arquivo local
  transcribe.py    faster-whisper (subprocesso com fallback GPU→CPU) ou VoiceStudio
  highlights.py    prompt + seleção dos cortes com Ollama
  reframe.py       rastreamento de rosto e câmera virtual 9:16
  voicestudio.py   cliente MCP do VoiceStudio (TTS, clonagem)
  dubbing.py       tradução + TTS por frase + ajuste de tempo
  claude_select.py seleção de cortes com `claude -p` (Claude Code não interativo)
  web/             interface gráfica (FastAPI + página única em web/static/)
  render.py        prepara o corte e chama o Remotion
  davinci.py       fila + instalação do script do menu
  resolve_bridge.py código que roda dentro do DaVinci (só biblioteca padrão)
  mcp_server.py    servidor MCP do VideoCut
remotion/src/      composição ShortClip (vídeo 9:16, legendas, abertura com gancho)
jobs/<id>/         saída: transcript.json, highlights.json, clips/NN/*.mp4 e legendas.srt
```

Para ajustar o visual das legendas, edite `remotion/src/Captions.tsx` (cores, posição e
palavras por tela também podem ser mudadas por corte com `edit_clip` → `caption_style`).

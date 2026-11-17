---
name: cortar
description: Cria cortes curtos (Shorts/Reels/TikTok) de um vídeo do YouTube ou arquivo local usando o servidor MCP videocut. Use quando o usuário pedir para cortar, achar os melhores momentos ou gerar shorts de um vídeo, ou passar um job_id do VideoCut.
---

# /cortar — escolher e produzir cortes com o VideoCut

Argumento: link do YouTube, caminho de arquivo, ou um `job_id` já transcrito.
Opcional: quantidade de cortes (padrão 5) e pedidos como "com gancho narrado", "dublar em inglês",
"mandar pro DaVinci".

## Fluxo

1. **Transcrever**: `analyze_video(source)` (com um `job_id`, use `get_clips` + `read_transcript`).
   Pode levar alguns minutos em vídeos longos. Avise o usuário antes.
2. **Ler a transcrição inteira**. Se `transcript` vier vazio, leia com `read_transcript` em janelas
   de ~600 s até o fim. Não escolha cortes só pelo começo do vídeo.
3. **Escolher os cortes** seguindo o `editorial_guide` retornado:
   - o corte precisa se sustentar sozinho: gancho nos primeiros 3 s, ideia completa, final com conclusão;
   - respeite `clip_length_sec`; prefira começar numa frase que já prenda (pergunta, número, afirmação forte);
   - pule introduções, pedidos de inscrição, patrocínios e trechos que dependem de contexto anterior;
   - nada de cortes sobrepostos; varie os temas.
   Use `start_line`/`end_line` (números L) em vez de segundos, que é mais preciso.
4. **Salvar**: `save_clips(job_id, clips)` com title (máx. 60 caracteres, no idioma do vídeo),
   hook (máx. 15 palavras), reason e score.
5. **Mostrar ao usuário** uma tabela curta: nº, tempo (mm:ss–mm:ss), duração, título, gancho e o motivo.
   Pergunte se quer ajustar antes de renderizar, a não ser que ele já tenha pedido para renderizar direto.
6. **Produzir** (conforme o pedido):
   - gancho narrado: `narrate_hook(job_id, n)` (VoiceStudio precisa estar aberto);
   - dublagem: `dub_clip(job_id, n, "inglês", tts_language="en")`;
   - `render(job_id, n)` para cada corte (cerca de 1 min por corte);
   - `send_to_davinci(job_id)` e lembre: no DaVinci gratuito, Workspace > Scripts > VideoCut.
7. Termine listando os caminhos dos MP4 gerados.

## Ajustes comuns

- "começa cedo/tarde demais" → `edit_clip(job_id, n, start=..., end=...)` (relendo a transcrição do trecho).
- "legenda maior/em outra cor/no meio" → `edit_clip(..., caption_style={"fontSize": 96, "highlight": "#00E5FF", "position": 0.5})`.
- Mudou algo → `render` de novo só daquele corte.
- Se uma ferramenta do VoiceStudio falhar por conexão, avise que o app VoiceStudio precisa estar aberto.

"use strict";

// ----------------------------------------------------------------- utilidades
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const CLIP_COLORS = ["#ff3d77", "#ff8a3d", "#fbbf24", "#34d399", "#60a5fa", "#a78bfa", "#f472b6", "#22d3ee"];

function fmt(t, decimals = 1) {
  if (t == null || isNaN(t)) return "--:--";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0")}`;
}
function parseTime(v) {
  v = String(v).trim().replace(",", ".");
  if (!v) return NaN;
  const parts = v.split(":").map(Number);
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}
function fmtDur(t) {
  if (!t) return "";
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.round(t % 60);
  return h ? `${h}h${String(m).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const r = await fetch(url, opts);
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(data?.detail || data?.error || `Erro ${r.status}`);
  return data;
}

function toast(msg, kind = "info", ms = 4500) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem("vc." + k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("vc." + k, JSON.stringify(v)); } catch { /* sem storage */ } },
};

// ----------------------------------------------------------------- estado
const state = {
  status: null,
  jobs: [],
  jobId: null,
  job: null,
  transcript: [],
  tasks: [],
  voices: null,
  manual: { start: null, end: null },
  stopAt: null,
  file: null,
  knownDone: new Set(),
};

// ----------------------------------------------------------------- status
async function loadStatus() {
  try { state.status = await api("GET", "/api/status"); } catch { return; }
  const s = state.status;
  const pill = (ok, label, title, warn) =>
    `<span class="pill ${ok ? "ok" : warn ? "warn" : "off"}" title="${esc(title)}"><span class="dot"></span>${esc(label)}</span>`;
  $("#status").innerHTML = [
    pill(s.claude.ok, "Claude", s.claude.ok ? `IA de seleção: ${s.claude.path}` : "Claude Code não encontrado"),
    pill(true, `Whisper ${s.whisper.model}`, "Transcrição local"),
    pill(s.remotion.ok, "Remotion", s.remotion.ok ? "Editor pronto" : "Rode npm install em remotion/"),
    pill(s.voicestudio.ok, "VoiceStudio", s.voicestudio.ok ? "Narração e dublagem disponíveis" : "Abra o app VoiceStudio para narrar/dublar", true),
    pill(s.davinci.ok, s.davinci.pending ? `DaVinci (${s.davinci.pending} na fila)` : "DaVinci",
      s.davinci.pending ? "Abra o DaVinci: Workspace > Scripts > VideoCut" : "Script instalado no menu do DaVinci", true),
  ].join("");
}

// ----------------------------------------------------------------- lista de vídeos
async function loadJobs() {
  state.jobs = await api("GET", "/api/jobs");
  renderJobs();
}

function renderJobs() {
  const ul = $("#jobs");
  if (!state.jobs.length) {
    ul.innerHTML = `<li class="empty-list">Nenhum vídeo ainda.</li>`;
    return;
  }
  ul.innerHTML = state.jobs.map((j) => `
    <li class="job-item ${j.id === state.jobId ? "active" : ""}" data-id="${esc(j.id)}">
      <img src="${esc(j.thumb)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
      <div style="min-width:0">
        <div class="t" title="${esc(j.title)}">${esc(j.title)}</div>
        <div class="m">${fmtDur(j.duration)} · ${j.clip_count} corte${j.clip_count === 1 ? "" : "s"}${j.busy ? " · processando…" : ""}</div>
      </div>
    </li>`).join("");
}

$("#jobs").addEventListener("click", (e) => {
  const li = e.target.closest(".job-item");
  if (li) openJob(li.dataset.id);
});
$("#refresh-jobs").addEventListener("click", () => loadJobs());

// ----------------------------------------------------------------- novo vídeo
const drop = $("#drop");
$("#pick").addEventListener("click", () => $("#file").click());
$("#file").addEventListener("change", (e) => setFile(e.target.files[0]));
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

function setFile(f) {
  state.file = f || null;
  drop.classList.toggle("has-file", !!f);
  $("#drop-label").innerHTML = f
    ? `📄 ${esc(f.name)} <button type="button" class="link" id="clear-file">remover</button>`
    : `Arraste um vídeo aqui ou <button type="button" class="link" id="pick">escolha um arquivo</button>`;
  $("#clear-file")?.addEventListener("click", () => setFile(null));
  $("#pick")?.addEventListener("click", () => $("#file").click());
  if (f) $("#source").value = "";
}

$("#new-job").addEventListener("submit", async (e) => {
  e.preventDefault();
  const source = $("#source").value.trim();
  const maxClips = Number($("#max-clips").value) || 5;
  const instructions = $("#instructions").value.trim();
  if (!source && !state.file) return toast("Cole um link do YouTube, um caminho de arquivo ou arraste um vídeo.", "err");
  const btn = $("#start-btn");
  btn.disabled = true;
  try {
    if (state.file) {
      btn.textContent = "Enviando arquivo…";
      const fd = new FormData();
      fd.append("file", state.file);
      fd.append("max_clips", maxClips);
      fd.append("instructions", instructions);
      await api("POST", "/api/upload", fd);
      setFile(null);
    } else {
      await api("POST", "/api/jobs", { source, max_clips: maxClips, instructions });
      $("#source").value = "";
    }
    toast("Processando: baixar → transcrever → Claude escolhe os cortes. Acompanhe na barra de tarefas.", "ok");
    $("#tasks").classList.remove("collapsed");
    pollTasks();
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Começar";
  }
});

// ----------------------------------------------------------------- vídeo aberto
async function openJob(id, keepScroll = false) {
  state.jobId = id;
  history.replaceState(null, "", "#" + encodeURIComponent(id));
  renderJobs();
  const scroll = window.scrollY;
  try {
    const [job, tr] = await Promise.all([api("GET", `/api/jobs/${id}`), api("GET", `/api/jobs/${id}/transcript`)]);
    if (state.jobId !== id) return;
    state.job = job;
    state.transcript = tr.segments;
    state.manual = { start: null, end: null };
    renderJob();
    if (keepScroll) window.scrollTo(0, scroll);
  } catch (err) {
    toast(err.message, "err");
  }
}

async function refreshJob() {
  if (!state.jobId) return;
  const job = await api("GET", `/api/jobs/${state.jobId}`);
  state.job = job;
  renderClips();
  renderTranscript();
  renderJobHeaderCounts();
}

function renderJob() {
  const j = state.job;
  const main = $("#main");
  if (!j) { main.innerHTML = welcomeHtml(); return; }

  if (!j.transcribed) {
    main.innerHTML = `
      <div class="processing">
        <h2>${esc(j.title)}</h2>
        <p>Transcrevendo o vídeo…</p>
        <div class="bar indeterminate" id="proc-bar"><div></div></div>
        <p id="proc-stage"></p>
      </div>`;
    return;
  }

  const voicesOpts = voiceOptions();
  main.innerHTML = `
    <div class="job-head">
      <div>
        <h1>${esc(j.title)}</h1>
        <div class="sub">${fmtDur(j.duration)} · ${j.width || "?"}×${j.height || "?"} · idioma: ${esc(j.language || "?")}
          · <span id="clip-count">${j.clips.length}</span> cortes</div>
      </div>
      <div class="toolbar">
        <button class="btn" id="btn-select">✨ Escolher cortes com IA</button>
        <button class="btn" id="btn-render-all">▶ Renderizar todos</button>
        <button class="btn" id="btn-davinci">🎬 Enviar ao DaVinci</button>
        <button class="btn" id="btn-folder" title="Abrir pasta">📁</button>
        <button class="btn danger" id="btn-delete" title="Excluir vídeo">🗑</button>
      </div>
    </div>

    <div class="top-grid">
      <div class="card player-card">
        <video id="player" src="/api/jobs/${encodeURIComponent(j.id)}/source" controls preload="metadata"></video>
        <div class="player-bar">
          <span id="player-info">Clique numa frase da transcrição para pular até ela.</span>
          <label class="inline">Voz da narração
            <select id="voice" style="width:auto">${voicesOpts}</select>
          </label>
        </div>
      </div>
      <div class="card transcript">
        <header>
          <h3>Transcrição</h3>
          <input class="search" id="tr-search" type="text" placeholder="Buscar…">
        </header>
        <ol id="segments"></ol>
        <div class="manual-bar" id="manual-bar"></div>
      </div>
    </div>

    <div class="section-head">
      <h2>Cortes</h2>
      <span class="hint">As alterações são salvas automaticamente. Renderize de novo para aplicar no vídeo.</span>
    </div>
    <div class="clips" id="clips"></div>`;

  $("#btn-select").addEventListener("click", selectWithAI);
  $("#btn-render-all").addEventListener("click", async () => {
    if (!j.clips.length) return toast("Nenhum corte para renderizar.", "err");
    await act(() => api("POST", `/api/jobs/${j.id}/render`), `${j.clips.length} cortes na fila de renderização.`);
  });
  $("#btn-davinci").addEventListener("click", () => act(() => api("POST", `/api/jobs/${j.id}/davinci`),
    "Enviado. No DaVinci: Workspace > Scripts > VideoCut."));
  $("#btn-folder").addEventListener("click", () => api("POST", `/api/jobs/${j.id}/open`));
  $("#btn-delete").addEventListener("click", async () => {
    if (!confirm(`Excluir "${j.title}" e todos os cortes? Isso apaga os arquivos.`)) return;
    try {
      await api("DELETE", `/api/jobs/${j.id}`);
      state.jobId = null; state.job = null;
      history.replaceState(null, "", "#");
      renderJob(); loadJobs();
    } catch (err) { toast(err.message, "err"); }
  });
  $("#voice").addEventListener("change", (e) => store.set("voice", e.target.value));
  $("#tr-search").addEventListener("input", renderTranscript);

  const player = $("#player");
  player.addEventListener("timeupdate", () => {
    if (state.stopAt != null && player.currentTime >= state.stopAt) { player.pause(); state.stopAt = null; }
    highlightPlaying(player.currentTime);
  });
  player.addEventListener("seeking", () => { if (state.stopAt != null && player.currentTime > state.stopAt) state.stopAt = null; });

  renderTranscript();
  renderClips();
  if (state.voices === null) loadVoices();
}

function renderJobHeaderCounts() {
  const el = $("#clip-count");
  if (el && state.job) el.textContent = state.job.clips.length;
}

function welcomeHtml() {
  return `
    <div class="welcome">
      <h1>Cortes virais em poucos cliques</h1>
      <p>Cole um link do YouTube ou arraste um vídeo na barra ao lado.</p>
      <ol>
        <li>O vídeo é transcrito na sua GPU</li>
        <li>O Claude lê tudo e escolhe os melhores momentos</li>
        <li>Você revisa, ajusta e renderiza em 9:16 com legendas</li>
        <li>Opcional: gancho narrado, dublagem e envio ao DaVinci</li>
      </ol>
    </div>`;
}

async function selectWithAI() {
  const j = state.job;
  const has = j.clips.length > 0;
  const n = prompt(`Quantos cortes o Claude deve escolher?${has ? "\n(Os cortes atuais serão substituídos.)" : ""}`, String(Math.max(j.clips.length, 5)));
  if (n === null) return;
  const instructions = prompt("Instruções para a IA (opcional):", store.get("instructions", "")) ?? "";
  store.set("instructions", instructions);
  await act(() => api("POST", `/api/jobs/${j.id}/select`, { max_clips: Number(n) || 5, instructions, replace: true }),
    "Claude está lendo a transcrição…");
}

async function act(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(okMsg, "ok");
    pollTasks();
    return r;
  } catch (err) {
    toast(err.message, "err", 8000);
  }
}

// ----------------------------------------------------------------- vozes
async function loadVoices() {
  try {
    const v = await api("GET", "/api/voices");
    state.voices = Array.isArray(v) ? v : [];
  } catch {
    state.voices = [];
  }
  const sel = $("#voice");
  if (sel) sel.innerHTML = voiceOptions();
}
function voiceOptions() {
  if (state.voices === null) return `<option value="">carregando…</option>`;
  if (!state.voices.length) return `<option value="">padrão (VoiceStudio offline?)</option>`;
  const saved = store.get("voice", "");
  return `<option value="">voz padrão</option>` + state.voices.map((v) =>
    `<option value="${esc(v.id)}" ${v.id === saved ? "selected" : ""}>${esc(v.name)}${v.language ? " · " + esc(v.language) : ""}</option>`).join("");
}

// ----------------------------------------------------------------- transcrição
function clipColor(index) { return CLIP_COLORS[(index - 1) % CLIP_COLORS.length]; }

function renderTranscript() {
  const ol = $("#segments");
  if (!ol) return;
  const q = ($("#tr-search")?.value || "").toLowerCase().trim();
  const clips = state.job?.clips || [];
  const { start: ms, end: me } = state.manual;
  ol.innerHTML = state.transcript
    .filter((s) => !q || s.text.toLowerCase().includes(q))
    .map((s) => {
      const c = clips.find((c) => s.start >= c.start - 0.2 && s.end <= c.end + 0.5);
      const manual = ms != null && s.start >= ms - 0.01 && (me == null ? s.start <= ms + 0.01 : s.end <= me + 0.01);
      return `<li class="seg ${c ? "in-clip" : ""} ${manual ? "manual" : ""}" data-i="${s.i}" data-start="${s.start}"
                 ${c ? `style="--clip-color:${clipColor(c.index)}" title="Corte ${c.index}: ${esc(c.title)}"` : ""}>
        <span class="ts">${fmt(s.start, 0)}</span>
        <span>${esc(s.text)}</span>
        <span class="marks"><button data-mark="start">início</button><button data-mark="end">fim</button></span>
      </li>`;
    }).join("");
  renderManualBar();
}

$("#main").addEventListener("click", (e) => {
  const mark = e.target.closest("[data-mark]");
  const seg = e.target.closest(".seg");
  if (mark && seg) {
    e.stopPropagation();
    const s = state.transcript[Number(seg.dataset.i)];
    if (mark.dataset.mark === "start") state.manual = { start: s.start, end: state.manual.end && state.manual.end > s.start ? state.manual.end : null };
    else state.manual.end = s.end;
    if (state.manual.start == null) state.manual.start = s.start;
    renderTranscript();
    return;
  }
  if (seg) {
    const p = $("#player");
    if (p) { state.stopAt = null; p.currentTime = Number(seg.dataset.start); p.play(); }
  }
});

function renderManualBar() {
  const bar = $("#manual-bar");
  if (!bar) return;
  const { start, end } = state.manual;
  if (start == null) {
    bar.innerHTML = `Corte manual: passe o mouse numa frase e clique em <b>início</b> e depois em <b>fim</b>.`;
    return;
  }
  const ok = end != null && end > start;
  bar.innerHTML = `Novo corte: <b>${fmt(start)}</b> → <b>${end != null ? fmt(end) : "?"}</b>
    ${ok ? `(${(end - start).toFixed(1)}s)` : ""}
    <button class="btn small primary" id="manual-create" ${ok ? "" : "disabled"}>Criar corte</button>
    <button class="btn small" id="manual-play" ${ok ? "" : "disabled"}>▶ Ouvir</button>
    <button class="link" id="manual-clear">limpar</button>`;
  $("#manual-clear").onclick = () => { state.manual = { start: null, end: null }; renderTranscript(); };
  $("#manual-play").onclick = () => playRange(start, end);
  $("#manual-create").onclick = async () => {
    const title = prompt("Título do corte:", "") ?? "";
    try {
      await api("POST", `/api/jobs/${state.jobId}/clips`, { start, end, title });
      state.manual = { start: null, end: null };
      await refreshJob();
      toast("Corte criado.", "ok");
    } catch (err) { toast(err.message, "err"); }
  };
}

function highlightPlaying(t) {
  const ol = $("#segments");
  if (!ol) return;
  const cur = state.transcript.find((s) => t >= s.start && t < s.end);
  $$(".seg.playing", ol).forEach((el) => el.classList.remove("playing"));
  if (cur) $(`.seg[data-i="${cur.i}"]`, ol)?.classList.add("playing");
}

function playRange(start, end) {
  const p = $("#player");
  if (!p) return;
  p.currentTime = start;
  state.stopAt = end;
  p.play();
  p.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ----------------------------------------------------------------- cortes
const DUB_LANGS = [["inglês", "en"], ["espanhol", "es"], ["português", "pt"], ["francês", "fr"], ["italiano", "it"], ["alemão", "de"], ["japonês", "ja"]];

function renderClips() {
  const wrap = $("#clips");
  if (!wrap) return;
  const clips = state.job.clips;
  if (!clips.length) {
    wrap.innerHTML = `<div class="card" style="grid-column:1/-1;color:var(--muted)">
      Nenhum corte ainda. Clique em <b>✨ Escolher cortes com IA</b> ou crie um manualmente pela transcrição.</div>`;
    return;
  }
  // Preserva cards em que o usuário está digitando.
  const focused = document.activeElement?.closest?.(".clip")?.dataset.index;
  const existing = new Map($$(".clip", wrap).map((el) => [el.dataset.index, el]));
  wrap.innerHTML = "";
  for (const c of clips) {
    const keep = focused === String(c.index) ? existing.get(String(c.index)) : null;
    wrap.append(keep || clipCard(c));
  }
  updateClipProgress();
}

function clipCard(c) {
  const st = { color: "#FFFFFF", highlight: "#FFE11A", fontSize: 84, position: 0.72, wordsPerPage: 3, uppercase: true, ...(c.caption_style || {}) };
  const frame = `/api/jobs/${encodeURIComponent(state.jobId)}/frame?t=${(c.start + 1).toFixed(1)}`;
  const el = document.createElement("article");
  el.className = "card clip";
  el.dataset.index = c.index;
  el.style.borderTop = `3px solid ${clipColor(c.index)}`;
  el.innerHTML = `
    <div class="clip-media">
      ${c.output_url
        ? `<video src="${esc(c.output_url)}" controls preload="metadata" playsinline></video>`
        : `<img src="${frame}" alt=""><div class="overlay">Ainda não renderizado</div>`}
      ${c.output_url ? (c.dirty ? `<span class="badge dirty">desatualizado</span>` : `<span class="badge done">pronto</span>`) : ""}
    </div>
    <div class="clip-body">
      <div class="clip-top">
        <span class="num">#${c.index}</span>
        <input data-f="title" type="text" value="${esc(c.title)}" maxlength="80" placeholder="Título">
        ${c.score ? `<span class="badge score" title="Potencial viral segundo a IA">${c.score}</span>` : ""}
      </div>
      <div class="times">
        <input data-f="start" type="text" value="${fmt(c.start)}" title="Início (mm:ss)">
        <span class="nudge"><button data-nudge="start:-0.5">−½s</button><button data-nudge="start:0.5">+½s</button></span>
        →
        <input data-f="end" type="text" value="${fmt(c.end)}" title="Fim (mm:ss)">
        <span class="nudge"><button data-nudge="end:-0.5">−½s</button><button data-nudge="end:0.5">+½s</button></span>
        <span class="dur">${c.duration.toFixed(1)}s</span>
        <button class="btn small" data-a="play">▶ Trecho</button>
      </div>
      <div>
        <span class="field-label">Gancho</span>
        <textarea data-f="hook" rows="2" placeholder="Frase de abertura">${esc(c.hook)}</textarea>
      </div>
      <label class="check"><input type="checkbox" data-f="use_hook" ${c.use_hook ? "checked" : ""}>
        Abrir o vídeo com o gancho na tela ${c.hook_audio_url ? `<span class="badge info">narrado</span>` : ""}</label>
      ${c.dub ? `<div class="row" style="font-size:12px"><span class="badge info">dublado: ${esc(c.dub.language)}</span>
        <button class="link" data-a="undub">remover dublagem</button></div>` : ""}
      ${c.reason ? `<p class="reason" title="Clique para ver tudo">💡 ${esc(c.reason)}</p>` : ""}
      <details class="style-box">
        <summary>Estilo da legenda</summary>
        <div class="style-grid">
          Cor <span class="row"><input type="color" data-s="color" value="${esc(st.color)}">
            destaque <input type="color" data-s="highlight" value="${esc(st.highlight)}"></span>
          Tamanho <input type="range" data-s="fontSize" min="48" max="140" step="2" value="${st.fontSize}">
          Altura <input type="range" data-s="position" min="0.15" max="0.9" step="0.01" value="${st.position}">
          Palavras <select data-s="wordsPerPage" style="width:auto">${[1, 2, 3, 4, 5, 6].map((n) => `<option ${n === st.wordsPerPage ? "selected" : ""}>${n}</option>`).join("")}</select>
          Maiúsculas <input type="checkbox" data-s="uppercase" ${st.uppercase ? "checked" : ""}>
        </div>
      </details>
      <div class="progress" hidden><div class="bar"><div></div></div><span class="ptext"></span></div>
      <div class="actions">
        <button class="btn primary small" data-a="render">${c.output_url ? "Renderizar de novo" : "Renderizar"}</button>
        <button class="btn small" data-a="hook" title="Gera a narração do gancho no VoiceStudio e renderiza">🎙 Narrar gancho</button>
        <span class="group">
          <select data-a="dublang">${DUB_LANGS.map(([n, code]) => `<option value="${code}|${n}">${n}</option>`).join("")}</select>
          <button class="btn small" data-a="dub" title="Traduz e dubla com a voz original clonada (VoiceStudio)">🌐 Dublar</button>
        </span>
        ${c.output_url ? `<a class="btn small" href="${esc(c.output_url)}" download>⬇ Baixar</a>` : ""}
        <button class="btn small" data-a="folder" title="Abrir pasta do corte">📁</button>
        <button class="btn small danger" data-a="delete" title="Excluir corte">🗑</button>
      </div>
    </div>`;
  return el;
}

function clipByIndex(i) { return state.job.clips.find((c) => c.index === Number(i)); }

async function saveClip(index, changes) {
  try {
    const updated = await api("PUT", `/api/jobs/${state.jobId}/clips/${index}`, changes);
    const i = state.job.clips.findIndex((c) => c.index === Number(index));
    state.job.clips[i] = updated;
    const card = $(`.clip[data-index="${index}"]`);
    if (card) card.replaceWith(clipCard(updated));
    renderTranscript();
    updateClipProgress();
  } catch (err) {
    toast(err.message, "err");
    const card = $(`.clip[data-index="${index}"]`);
    const c = clipByIndex(index);
    if (card && c) card.replaceWith(clipCard(c));
  }
}

$("#main").addEventListener("change", (e) => {
  const card = e.target.closest(".clip");
  if (!card) return;
  const index = card.dataset.index;
  const f = e.target.dataset.f;
  const s = e.target.dataset.s;
  if (f === "title" || f === "hook") saveClip(index, { [f]: e.target.value });
  else if (f === "use_hook") saveClip(index, { use_hook: e.target.checked });
  else if (f === "start" || f === "end") {
    const t = parseTime(e.target.value);
    if (isNaN(t)) return toast("Tempo inválido. Use mm:ss (ex.: 01:23.5)", "err");
    saveClip(index, { [f]: t });
  } else if (s) {
    const c = clipByIndex(index);
    let v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    if (["fontSize", "position", "wordsPerPage"].includes(s)) v = Number(v);
    saveClip(index, { caption_style: { ...(c.caption_style || {}), [s]: v } });
  }
});

$("#main").addEventListener("click", async (e) => {
  const card = e.target.closest(".clip");
  if (!card) return;
  const index = Number(card.dataset.index);
  const c = clipByIndex(index);
  const base = `/api/jobs/${state.jobId}/clips/${index}`;

  if (e.target.closest(".reason")) return e.target.closest(".reason").classList.toggle("open");
  const nudge = e.target.closest("[data-nudge]");
  if (nudge) {
    const [field, delta] = nudge.dataset.nudge.split(":");
    return saveClip(index, { [field]: Math.max(0, c[field] + Number(delta)) });
  }
  const a = e.target.closest("[data-a]")?.dataset.a;
  if (!a || e.target.tagName === "SELECT") return;
  if (a === "play") return playRange(c.start, c.end);
  if (a === "render") return act(() => api("POST", `${base}/render`), `Corte ${index} na fila de renderização.`);
  if (a === "folder") return api("POST", `/api/jobs/${state.jobId}/open?clip=${index}`);
  if (a === "hook") {
    if (!state.status?.voicestudio.ok) return toast("VoiceStudio está offline. Abra o app VoiceStudio e tente de novo.", "err", 7000);
    const hookText = $("[data-f=hook]", card).value.trim();
    return act(() => api("POST", `${base}/hook`, { text: hookText || null, voice: $("#voice")?.value || null, render: true }),
      `Narrando o gancho do corte ${index}; depois renderiza.`);
  }
  if (a === "dub") {
    if (!state.status?.voicestudio.ok) return toast("VoiceStudio está offline. Abra o app VoiceStudio e tente de novo.", "err", 7000);
    const [code, name] = $("[data-a=dublang]", card).value.split("|");
    return act(() => api("POST", `${base}/dub`, { language: name, tts_language: code, render: true }),
      `Dublando o corte ${index} em ${name}…`);
  }
  if (a === "undub") {
    await api("DELETE", `${base}/dub`);
    return refreshJob();
  }
  if (a === "delete") {
    if (!confirm(`Excluir o corte ${index} "${c.title}"?`)) return;
    await api("DELETE", base);
    return refreshJob();
  }
});

function updateClipProgress() {
  for (const card of $$(".clip")) {
    const index = Number(card.dataset.index);
    const t = state.tasks.find((t) => t.job_id === state.jobId && t.clip === index && (t.status === "running" || t.status === "queued"));
    const box = $(".progress", card);
    if (!box) continue;
    box.hidden = !t;
    if (t) {
      const bar = $(".bar", box);
      bar.classList.toggle("indeterminate", t.progress == null || t.status === "queued");
      $(".bar > div", box).style.width = t.progress != null ? `${Math.round(t.progress * 100)}%` : "";
      $(".ptext", box).textContent = t.status === "queued" ? `${t.label}: na fila` : `${t.stage}${t.progress != null ? ` · ${Math.round(t.progress * 100)}%` : ""}`;
    }
    $$("[data-a=render],[data-a=hook],[data-a=dub]", card).forEach((b) => { b.disabled = !!t; });
  }
}

// ----------------------------------------------------------------- tarefas
let pollTimer = null;
async function pollTasks() {
  clearTimeout(pollTimer);
  try {
    state.tasks = await api("GET", "/api/tasks");
  } catch {
    pollTimer = setTimeout(pollTasks, 3000);
    return;
  }
  const active = state.tasks.filter((t) => t.status === "running" || t.status === "queued");
  renderTasks(active);
  updateClipProgress();
  updateProcessingView();

  // Reage a tarefas que acabaram de terminar.
  let needJobs = false, needJob = false;
  for (const t of state.tasks) {
    if ((t.status === "done" || t.status === "error") && !state.knownDone.has(t.id)) {
      state.knownDone.add(t.id);
      if (!state.booted) continue;
      if (t.status === "error") toast(`${t.label}: ${t.error}`, "err", 10000);
      if (t.kind === "analyze") {
        needJobs = true;
        if (t.status === "done" && t.result?.job_id) {
          toast(`Pronto! ${t.result.clips} cortes sugeridos.`, "ok");
          openJob(t.result.job_id);
        }
      } else {
        if (t.job_id === state.jobId) needJob = true;
        if (t.kind === "select") needJobs = true;
        if (t.kind === "render" && t.status === "done") toast(`${t.label}: pronto ✓`, "ok", 3000);
        if (t.kind === "davinci") loadStatus();
      }
    }
  }
  state.booted = true;
  if (needJobs) loadJobs();
  if (needJob) {
    if (!state.job?.transcribed) openJob(state.jobId, true);
    else refreshJob();
  }
  pollTimer = setTimeout(pollTasks, active.length ? 1000 : 4000);
}

function renderTasks(active) {
  const toggle = $("#tasks-toggle");
  const running = active.find((t) => t.status === "running");
  if (active.length) {
    const pct = running?.progress != null ? Math.round(running.progress * 100) : null;
    toggle.innerHTML = `<span class="spinner"></span>
      <span style="flex:1;color:var(--text)">${esc(running ? `${running.label} — ${running.stage}` : "Na fila…")}
        ${active.length > 1 ? `<span style="color:var(--muted)"> · +${active.length - 1} na fila</span>` : ""}</span>
      <span class="bar ${pct == null ? "indeterminate" : ""}"><div style="${pct != null ? `width:${pct}%` : ""}"></div></span>
      <span>${pct != null ? pct + "%" : ""}</span><span>▴</span>`;
  } else {
    toggle.innerHTML = `<span style="flex:1">Nenhuma tarefa em andamento</span><span>${state.tasks.length ? "histórico ▴" : ""}</span>`;
  }
  $("#tasks-list").innerHTML = state.tasks.slice(0, 40).map((t) => `
    <div class="task">
      <span>${t.status === "running" ? `<span class="spinner"></span>` : t.status === "queued" ? "⏳" : t.status === "done" ? "✅" : "❌"}</span>
      <span style="min-width:0">
        <div>${esc(t.label)}</div>
        <div class="${t.status === "error" ? "err" : "stage"}">${esc(t.status === "error" ? t.error : t.stage)}</div>
      </span>
      <span class="bar ${t.status === "running" && t.progress == null ? "indeterminate" : ""}"><div style="width:${t.status === "done" ? 100 : Math.round((t.progress || 0) * 100)}%"></div></span>
      <button class="btn small" data-log="${t.id}">log</button>
    </div>`).join("");
}

$("#tasks-toggle").addEventListener("click", () => $("#tasks").classList.toggle("collapsed"));
$("#tasks-list").addEventListener("click", async (e) => {
  const id = e.target.closest("[data-log]")?.dataset.log;
  if (!id) return;
  const t = await api("GET", `/api/tasks/${id}`);
  $("#log-title").textContent = t.label;
  $("#log-body").textContent = (t.log || []).join("\n") + (t.error ? `\n\nERRO: ${t.error}` : "") || "(sem log)";
  $("#log-dialog").showModal();
});
$("#log-dialog").addEventListener("click", (e) => { if (e.target.matches("[data-close]") || e.target === e.currentTarget) e.currentTarget.close(); });

function updateProcessingView() {
  const bar = $("#proc-bar");
  if (!bar) return;
  const t = state.tasks.find((t) => t.kind === "analyze" && t.status === "running");
  if (!t) return;
  bar.classList.toggle("indeterminate", t.progress == null);
  $("div", bar).style.width = t.progress != null ? `${Math.round(t.progress * 100)}%` : "";
  $("#proc-stage").textContent = t.stage;
}

// ----------------------------------------------------------------- início
(async function boot() {
  $("#main").innerHTML = welcomeHtml();
  await Promise.all([loadStatus(), loadJobs()]);
  const fromHash = decodeURIComponent(location.hash.slice(1));
  if (fromHash && state.jobs.some((j) => j.id === fromHash)) openJob(fromHash);
  else if (state.jobs.length) openJob(state.jobs[0].id);
  pollTasks();
  setInterval(loadStatus, 15000);
})();

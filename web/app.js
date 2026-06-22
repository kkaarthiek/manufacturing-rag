"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let STATE = {
  docs: [],            // ingested documents (the editable store)
  seedCount: 0,        // seed corpus.jsonl count (chat base)
  categories: {}, docTypes: [], activeCat: "__all__", search: "",
  groundTruth: {}, editing: null, feed: [],
};

// --------------------------------------------------------------------------
// API
// --------------------------------------------------------------------------
const api = {
  corpus: () => fetch("/api/corpus").then((r) => r.json()),
  ingested: () => fetch("/api/ingested").then((r) => r.json()),
  groundTruth: () => fetch("/api/ground-truth").then((r) => r.json()),
  chat: (message, mode) => fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, mode }),
  }).then((r) => r.json()),
  resolveConflict: (question, field, doc_id, mode) => fetch("/api/resolve-conflict", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, field, doc_id, mode: mode || "hosted" }),
  }).then((r) => r.json()),
  rawDoc: (doc_id) => fetch("/api/raw-doc?id=" + encodeURIComponent(doc_id)).then((r) => r.json()),
  modelsStatus: () => fetch("/api/models-status").then((r) => r.json()),
  activateModels: () => fetch("/api/activate-models", { method: "POST" }).then((r) => r.json()),
  upload: (file) => fetch("/api/upload", {
    method: "POST", headers: { "X-Filename": file.name }, body: file,
  }).then((r) => r.json()),
  ingestRaw: () => fetch("/api/ingest-raw", { method: "POST" }).then((r) => r.json()),
  saveDoc: (id, doc) => fetch("/api/doc?id=" + encodeURIComponent(id), {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(doc),
  }).then((r) => r.json()),
  delDoc: (id) => fetch("/api/doc?id=" + encodeURIComponent(id), { method: "DELETE" })
    .then((r) => r.json()),
};

// --------------------------------------------------------------------------
// Navigation
// --------------------------------------------------------------------------
function showView(name) {
  $$(".nav-btn").forEach((x) => x.classList.toggle("active", x.dataset.view === name));
  $$(".view").forEach((v) => v.classList.remove("active"));
  $("#view-" + name).classList.add("active");
  if (name === "ingest") refreshIngestStatus();   // show live/past ingestion status
}
$$(".nav-btn").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

function escapeHtml(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// --------------------------------------------------------------------------
// Chat
// --------------------------------------------------------------------------
function mdLite(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/_(.+?)_/g, "<i>$1</i>");
}
function addMsg(text, who) {
  const log = $("#chatLog");
  const welcome = log.querySelector(".welcome");
  if (welcome) welcome.remove();
  const div = document.createElement("div");
  div.className = "msg " + who;
  div.innerHTML = mdLite(text);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}
const STATUS_LABEL = {
  answered: ["✓ answered", "good"], abstained: ["⊘ abstained", "warn"],
  partial: ["◐ partial", "warn"], clarify: ["? needs clarification", "warn"],
  conflict: ["⚠ conflict — pick a source", "warn"],
  models_inactive: ["⚡ models not active", "warn"],
  error: ["✕ error", "danger"], empty: ["—", "muted"],
};

// --------------------------------------------------------------------------
// Local-model activation (Ollama)
// --------------------------------------------------------------------------
let MODELS_ACTIVE = false;

async function refreshModelStatus() {
  const dot = $("#modelDot"), label = $("#modelLabel"), btn = $("#activateBtn");
  if (!dot) return;
  let st;
  try { st = await api.modelsStatus(); }
  catch { label.textContent = "models: server unreachable"; return; }
  MODELS_ACTIVE = !!st.active;
  if (st.provider === "cloud") {
    dot.className = "model-dot on"; label.textContent = "cloud models";
    btn.style.display = "none"; return;
  }
  if (st.active) {
    dot.className = "model-dot on";
    label.textContent = "models active";
    btn.style.display = "none";
  } else {
    dot.className = "model-dot off";
    label.textContent = st.ollama_up === false ? "Ollama not running" : "models not loaded";
    btn.style.display = "block";
    btn.disabled = false;
    btn.textContent = "⚡ Activate models";
  }
  btn.title = st.detail || "";
}

async function activateModels() {
  const btn = $("#activateBtn"), label = $("#modelLabel");
  btn.disabled = true; btn.textContent = "loading… (~30s)";
  label.textContent = "loading qwen2.5 + nomic…";
  let st;
  try { st = await api.activateModels(); }
  catch { btn.disabled = false; btn.textContent = "⚡ Activate models"; label.textContent = "activation failed"; return; }
  await refreshModelStatus();
  if (!st.active) toast(st.detail || "Activation failed — is Ollama running?");
  else toast("Local models active ✓");
}

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "activateBtn") activateModels();
});

// Render a conflict card: both disputed values with their doc IDs + sources,
// a "view raw" toggle per source, and a pick button that resolves + remembers.
function renderConflict(container, question, conflict) {
  const card = document.createElement("div");
  card.className = "conflict-card";
  const field = (conflict.field || "value").replace(/_/g, " ");
  card.innerHTML = `<div class="conflict-head">⚠ Sources disagree on `
    + `<b>${escapeHtml(field)}</b> — choose which to trust:</div>`;
  (conflict.options || []).forEach((o) => {
    const row = document.createElement("div");
    row.className = "conflict-opt";
    const note = o.note ? ` <span class="conflict-note">(${escapeHtml(o.note)})</span>` : "";
    const head = document.createElement("div");
    head.className = "conflict-val";
    head.innerHTML = `<b>${escapeHtml(String(o.value))}</b>${note}<br>`
      + `<span class="cid">${escapeHtml(o.doc_id)}</span>`
      + (o.source_file ? ` <span class="ct">· ${escapeHtml(o.source_file)}</span>` : "");
    const acts = document.createElement("div");
    acts.className = "conflict-actions";
    const pick = document.createElement("button");
    pick.className = "btn-pick"; pick.textContent = "Use this source";
    pick.addEventListener("click", () => pickSource(card, question, conflict.field, o.doc_id));
    const raw = document.createElement("button");
    raw.className = "btn-raw"; raw.textContent = "view raw";
    raw.addEventListener("click", () => toggleRaw(row, o.doc_id));
    acts.appendChild(pick); acts.appendChild(raw);
    row.appendChild(head); row.appendChild(acts);
    card.appendChild(row);
  });
  container.appendChild(card);
}

async function pickSource(card, question, field, doc_id) {
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  const res = await api.resolveConflict(question, field, doc_id);
  const out = document.createElement("div");
  out.className = "conflict-resolved";
  out.innerHTML = `<span class="status-pill good">✓ resolved</span> ` + mdLite(res.answer || "")
    + `<div class="muted tiny">remembered — future answers use `
    + `${escapeHtml(doc_id)} for this field</div>`;
  card.appendChild(out);
}

async function toggleRaw(row, doc_id) {
  const existing = row.querySelector("pre.raw");
  if (existing) { existing.remove(); return; }
  const d = await api.rawDoc(doc_id);
  const pre = document.createElement("pre");
  pre.className = "raw";
  pre.textContent = d.error ? ("error: " + d.error)
    : (d.source_file ? d.source_file + "\n\n" : "") + (d.text || "(empty)");
  row.appendChild(pre);
}
async function sendChat(message) {
  if (!message.trim()) return;
  addMsg(message, "user");
  const mode = $("#chatMode").value;
  const thinking = addMsg(mode === "deterministic" ? "…" : "… (calling Claude Haiku)", "bot");
  try {
    const res = await api.chat(message, mode);
    const [lbl, cls] = STATUS_LABEL[res.status] || [res.status, "muted"];
    let html = `<span class="status-pill ${cls}">${lbl}</span> `
             + `<span class="mode-pill">${res.mode}</span><br>` + mdLite(res.answer || "");
    // exact-value claims only (lookups/calcs/counts) — not the prose 'entailment'
    // claim, which just repeats the answer. Keeps synthesis answers clean.
    const valueClaims = (res.claims || []).filter(
      (c) => c.type !== "entailment" && c.value);
    if (valueClaims.length) {
      html += `<div class="claims">` + valueClaims.map((c) =>
        `<span class="claim ${c.verified ? "v" : "u"}">${c.type}: ${escapeHtml(c.value)}`
        + ` ${c.verified ? "✓verified" : "⚠unverified"}</span>`).join("") + `</div>`;
    }
    // multi-hop plan (the verified chain)
    if (res.plan && res.plan.length) {
      html += `<div class="plan"><b>verified chain:</b><br>` + res.plan.map((s) =>
        `${escapeHtml(s.step)} <span class="${s.verified ? "v" : "u"}">`
        + `[${s.verified === false ? "✕" : "✓"}]</span>`).join("<br>") + `</div>`;
    }
    // only surface 'missing' when the system actually abstained/partialed
    if (res.missing && res.missing.length && res.status !== "answered") {
      html += `<div class="muted tiny">missing: ${escapeHtml(res.missing.join(", "))}</div>`;
    }
    thinking.innerHTML = html;
    // models not loaded -> inline Activate & retry
    if (res.status === "models_inactive") {
      const b = document.createElement("button");
      b.className = "btn primary act-btn";
      b.textContent = "⚡ Activate models & retry";
      b.addEventListener("click", async () => {
        b.disabled = true; b.textContent = "loading… (~30s, first time)";
        await activateModels();
        if (MODELS_ACTIVE) sendChat(message);
      });
      thinking.appendChild(b);
    }
    if (res.citations && res.citations.length) {
      const wrap = document.createElement("div");
      wrap.className = "cites";
      res.citations.forEach((c) => {
        const el = document.createElement("div");
        el.className = "cite";
        el.innerHTML = `<span class="cid">${c.doc_id}</span> `
          + `<span class="ct">${c.doc_type || ""} ${c.source_file ? "· " + escapeHtml(c.source_file) : ""}</span>`
          + (c.snippet ? `<div class="cs">${escapeHtml(c.snippet)}</div>` : "");
        wrap.appendChild(el);
      });
      thinking.appendChild(wrap);
    }
    // conflict: render the pick-a-source card
    if (res.conflict) {
      renderConflict(thinking, message, res.conflict);
      $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
    }
  } catch (e) { thinking.innerHTML = "Error contacting server."; }
}
$("#chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#chatBox").value; $("#chatBox").value = ""; sendChat(v);
});
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("ex")) sendChat(e.target.textContent);
});

// --------------------------------------------------------------------------
// Load stores
// --------------------------------------------------------------------------
async function loadAll() {
  // fresh portal: only the user's ingested documents (no synthetic corpus)
  const [ing, live] = await Promise.all([
    api.ingested(),
    fetch("/api/live-docs").then((r) => r.json()).catch(() => ({ count: 0 })),
  ]);
  STATE.seedCount = 0;
  STATE.docs = ing.docs;
  STATE.categories = ing.categories;
  STATE.docTypes = ing.doc_types;
  STATE.groundTruth = {};
  // "in chat" = the LIVE embedded index (what the chat actually retrieves from),
  // NOT the draft catalog. Don't fall back to the draft count — that was misleading.
  const pipe = live.ingesting ? "ingesting…" : ((live.count || 0) + " in chat (live)");
  $("#docCount").textContent = pipe;
  $("#ingCount").textContent = STATE.docs.length + " catalogued (draft)";
  $("#dataBadge").textContent = STATE.docs.length + " documents";
  renderCats(); renderDocs(); fillTypeSelect();
}

// --------------------------------------------------------------------------
// Ingested Data: category list + cards
// --------------------------------------------------------------------------
function renderCats() {
  const ul = $("#catList");
  ul.innerHTML = "";
  const all = document.createElement("li");
  all.innerHTML = `<span>All documents</span><span class="cnt">${STATE.docs.length}</span>`;
  all.classList.toggle("active", STATE.activeCat === "__all__");
  all.onclick = () => { STATE.activeCat = "__all__"; renderCats(); renderDocs(); };
  ul.appendChild(all);
  Object.keys(STATE.categories).sort().forEach((cat) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${cat}</span><span class="cnt">${STATE.categories[cat]}</span>`;
    li.classList.toggle("active", STATE.activeCat === cat);
    li.onclick = () => { STATE.activeCat = cat; renderCats(); renderDocs(); };
    ul.appendChild(li);
  });
}
function visibleDocs() {
  const q = STATE.search.toLowerCase();
  return STATE.docs.filter((d) => {
    if (STATE.activeCat !== "__all__" && d.doc_type !== STATE.activeCat) return false;
    if (!q) return true;
    return (d.doc_id + " " + d.title + " " + d.text).toLowerCase().includes(q);
  });
}
function renderDocs() {
  const list = $("#docList");
  const docs = visibleDocs();
  if (!docs.length) {
    list.innerHTML = `<div class="empty">No ingested documents${STATE.search || STATE.activeCat !== "__all__" ? " match this filter" : " yet — add some in the Ingestion tab"}.</div>`;
    return;
  }
  list.innerHTML = "";
  docs.forEach((d) => {
    const meta = d.metadata || {};
    const status = meta.status === "draft" ? `<span class="tag draft">draft</span>` : "";
    const conf = meta.extraction_confidence
      ? `<span class="tag ${meta.extraction_confidence}">conf: ${meta.extraction_confidence}</span>` : "";
    const src = meta.source_file ? `<span class="tag">${escapeHtml(meta.source_file)}</span>` : "";
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML =
      `<span class="ctype">${d.doc_type}</span>`
      + `<span class="cid">${d.doc_id}</span>`
      + `<h3>${escapeHtml(d.title || "(untitled)")}</h3>`
      + `<p>${escapeHtml((d.text || "").slice(0, 200))}</p>`
      + `<div class="tags">${status}${conf}${src}</div>`;
    card.onclick = () => openEditor(d);
    list.appendChild(card);
  });
}
$("#search").addEventListener("input", (e) => { STATE.search = e.target.value; renderDocs(); });

// --------------------------------------------------------------------------
// Ingestion intake + "just ingested" feed
// --------------------------------------------------------------------------
function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => { t.className = "toast"; }, 4000);
}
function pushFeed(docs) {
  STATE.feed = docs.concat(STATE.feed).slice(0, 50);
  renderFeed();
}
function renderFeed() {
  const box = $("#ingestResult");
  if (!STATE.feed.length) {
    box.innerHTML = `<div class="empty">Nothing ingested yet this session. Upload files or run the raw/ tree.</div>`;
    return;
  }
  box.innerHTML = "";
  STATE.feed.forEach((d) => {
    const conf = (d.metadata || {}).extraction_confidence || "?";
    const row = document.createElement("div");
    row.className = "feed-row";
    row.innerHTML = `<span class="fid">${d.doc_id} — ${escapeHtml(d.title || "")}</span>`
      + `<span class="tag ${conf}">conf: ${conf}</span>`
      + `<span class="ftype">${d.doc_type}</span>`;
    row.onclick = () => { showView("data"); const fresh = STATE.docs.find((x) => x.doc_id === d.doc_id); if (fresh) openEditor(fresh); };
    box.appendChild(row);
  });
}
async function uploadFiles(files) {
  const added = [];
  for (const f of files) {
    try {
      const r = await api.upload(f);
      if (r && r.error === "models_inactive") {
        toast("Activate models first (sidebar ⚡) before uploading.", true);
        return;
      }
      if (r.doc) added.push({ ...r.doc, _file: f.name });
    } catch (e) { /* skip */ }
  }
  await loadAll();
  if (added.length) pushFeed(added);
  toast(`Uploading ${files.length} file(s) — ingesting into the chat pipeline…`);
  refreshIngestStatus();   // show the live per-file status panel + start polling
}

// Live ingestion status panel: one row per file (processing / done / error),
// polled while anything is still processing.
let _ingestPoll = null;
async function refreshIngestStatus() {
  const panel = $("#ingestStatus");
  if (!panel) return;
  let data;
  try { data = await fetch("/api/ingest-status").then((r) => r.json()); }
  catch (e) { return; }
  const st = data.status || {};
  const names = Object.keys(st);
  if (!names.length) { panel.innerHTML = ""; return; }
  let anyProcessing = false;
  const rows = names.reverse().map((n) => {
    const s = st[n] || {};
    let badge, detail;
    if (s.state === "processing") {
      badge = `<span class="is-badge proc">⏳ processing</span>`;
      detail = s.detail || "extracting + embedding…";
      anyProcessing = true;
    } else if (s.state === "done") {
      badge = `<span class="is-badge done">✓ done</span>`;
      detail = `${s.chunks || 0} chunks · ${s.tables || 0} tables · ${s.image_captions || 0} captions`;
    } else if (s.state === "error") {
      badge = `<span class="is-badge err">✕ error</span>`;
      detail = s.detail || "";
    } else {
      badge = `<span class="is-badge">${escapeHtml(s.state || "")}</span>`; detail = "";
    }
    return `<div class="is-row"><div class="is-name" title="${escapeHtml(n)}">${escapeHtml(n)}</div>`
         + `${badge}<div class="is-detail">${escapeHtml(detail)}</div></div>`;
  }).join("");
  panel.innerHTML = `<div class="is-head">Ingestion status</div>` + rows;
  if (anyProcessing && !_ingestPoll) {
    _ingestPoll = setInterval(refreshIngestStatus, 2500);
  } else if (!anyProcessing && _ingestPoll) {
    clearInterval(_ingestPoll); _ingestPoll = null;
    loadAll();   // all done -> refresh the live-docs count
  }
}
$("#fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));
$("#gotoData").addEventListener("click", () => showView("data"));
$("#ingestRawBtn").addEventListener("click", async () => {
  $("#ingestRawBtn").disabled = true;
  try {
    const r = await api.ingestRaw();
    await loadAll();
    if (r.docs) pushFeed(r.docs);
    toast(`Ingested ${r.added} file(s) from the raw/ tree → Ingested Data.`);
  } catch (e) { toast("Ingestion failed.", true); }
  $("#ingestRawBtn").disabled = false;
});
const dz = $("#dropzone");
dz.addEventListener("click", () => $("#fileInput").click());   // click anywhere to browse
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.add("drag");
}));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.remove("drag");
}));
dz.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files); });

// paste-to-add: turn pasted text into a document through the same upload pipeline
$("#pasteAdd").addEventListener("click", () => {
  const text = $("#pasteText").value.trim();
  if (!text) { toast("Paste some text first.", true); return; }
  let name = ($("#pasteName").value || "").trim();
  if (!name) name = "pasted-" + Date.now() + ".txt";
  if (!/\.[a-z0-9]+$/i.test(name)) name += ".txt";
  uploadFiles([new File([text], name, { type: "text/plain" })]);
  $("#pasteText").value = ""; $("#pasteName").value = "";
});

// --------------------------------------------------------------------------
// Editor drawer
// --------------------------------------------------------------------------
function fillTypeSelect() {
  const sel = $("#edType");
  sel.innerHTML = "";
  STATE.docTypes.forEach((t) => {
    const o = document.createElement("option"); o.value = t; o.textContent = t; sel.appendChild(o);
  });
}
function openEditor(d) {
  STATE.editing = d.doc_id;
  $("#edTitle").textContent = "Edit " + d.doc_id;
  $("#edId").value = d.doc_id;
  $("#edType").value = d.doc_type;
  $("#edTitleField").value = d.title || "";
  $("#edText").value = d.text || "";
  $("#edMeta").value = JSON.stringify(d.metadata || {}, null, 2);
  $("#edMetaErr").textContent = "";
  const src = (d.metadata || {}).source_file;
  const gt = src && STATE.groundTruth[src];
  const box = $("#edGt");
  if (gt) {
    box.classList.add("show");
    box.innerHTML = `<b>Ground truth for ${escapeHtml(src)}</b><br>`
      + `Should map to: ${gt.maps_to_doc_ids.join(", ") || "(none)"}<br>`
      + `Expected type: ${gt.doc_type}<br>`
      + `Key facts: ${escapeHtml((gt.key_facts || []).join(" · "))}<br>`
      + `Mess: ${escapeHtml((gt.mess_challenges || []).join(" · "))}`;
  } else { box.classList.remove("show"); box.innerHTML = ""; }
  $("#drawer").classList.add("show");
  $("#scrim").classList.add("show");
}
function closeEditor() {
  $("#drawer").classList.remove("show");
  $("#scrim").classList.remove("show");
  STATE.editing = null;
}
$("#drawerClose").onclick = closeEditor;
$("#edCancel").onclick = closeEditor;
$("#scrim").onclick = closeEditor;
$("#edSave").onclick = async () => {
  let meta;
  try { meta = JSON.parse($("#edMeta").value || "{}"); }
  catch (e) { $("#edMetaErr").textContent = "Metadata is not valid JSON."; return; }
  const doc = {
    doc_id: $("#edId").value.trim(), doc_type: $("#edType").value,
    title: $("#edTitleField").value, text: $("#edText").value, metadata: meta,
  };
  const r = await api.saveDoc(STATE.editing, doc);
  if (r.error) { $("#edMetaErr").textContent = r.error; return; }
  closeEditor(); await loadAll();
  toast("Saved " + doc.doc_id + ".");
};
$("#edDelete").onclick = async () => {
  if (!confirm("Delete " + STATE.editing + "?")) return;
  const r = await api.delDoc(STATE.editing);
  if (r.error) { toast(r.error, true); return; }
  closeEditor(); await loadAll();
  toast("Deleted.");
};
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeEditor(); });

// --------------------------------------------------------------------------
loadAll();
refreshModelStatus();
setInterval(refreshModelStatus, 30000);   // keep the status pill fresh

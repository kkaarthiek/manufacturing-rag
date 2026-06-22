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
  error: ["✕ error", "danger"], empty: ["—", "muted"],
};

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
  const pipe = live.ingesting ? "ingesting…" : ((live.count || STATE.docs.length) + " in chat");
  $("#docCount").textContent = pipe;
  $("#ingCount").textContent = STATE.docs.length + " uploaded";
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
    try { const r = await api.upload(f); if (r.doc) added.push({ ...r.doc, _file: f.name }); } catch (e) { /* skip */ }
  }
  await loadAll();
  if (added.length) pushFeed(added);
  toast(`Uploaded ${added.length} file(s) — ingesting into the chat pipeline…`);
  added.forEach((d) => pollIngest(d._file || (d.metadata || {}).source_file));
}

// poll background ingestion -> show real chunk/table/caption counts when done
async function pollIngest(filename) {
  if (!filename) return;
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    let st;
    try { st = (await fetch("/api/ingest-status").then((r) => r.json())).status[filename]; }
    catch (e) { continue; }
    if (!st) continue;
    if (st.state === "done") {
      await loadAll();
      toast(`✓ ${filename}: ${st.chunks} chunks · ${st.tables} tables · ${st.image_captions || 0} captions — ready to chat`);
      return;
    }
    if (st.state === "error") { toast(`✕ ${filename}: ${st.detail}`, true); return; }
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
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.add("drag");
}));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.remove("drag");
}));
dz.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files); });

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

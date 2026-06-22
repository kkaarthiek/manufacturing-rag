#!/usr/bin/env python3
"""
app.py — Helios RAG web app (standard library only; zero external deps).

Run:
    python app.py            # then open http://localhost:8000

Features
  * CHAT (headline)  — chat UI backed by /api/chat. Currently a transparent
    RETRIEVAL-ONLY preview (keyword scoring over the corpus, returns cited
    docs). Wire an LLM into `chat_answer()` later to complete it.
  * INGESTION        — upload files (any format in raw/), auto-extract + auto-
    categorize via ingest.py, browse documents BY CATEGORY, and EDIT/DELETE the
    extracted data inline. Edits persist to corpus.jsonl.

Data store: corpus.jsonl (a backup corpus.backup.jsonl is written before the
first mutation).
"""

import json
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import ingest

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus.jsonl"          # seed knowledge base (kept clean)
BACKUP = ROOT / "corpus.backup.jsonl"
INGESTED = ROOT / "ingested.jsonl"       # separate store for ingested data
INBOX = ROOT / "raw" / "inbox"
WEB = ROOT / "web"
GROUND_TRUTH = ROOT / "raw" / "INGESTION_GROUND_TRUTH.jsonl"

_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Stores
# --------------------------------------------------------------------------- #
def load_store(path):
    docs = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    docs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue          # skip a corrupt/partial line, never crash the store
    return docs


def save_store(path, docs, backup=None):
    if backup and path.exists() and not backup.exists():
        backup.write_bytes(path.read_bytes())
    with open(path, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def load_corpus():
    return load_store(CORPUS)


def save_corpus(docs):
    save_store(CORPUS, docs, backup=BACKUP)


def load_ingested():
    return load_store(INGESTED)


def save_ingested(docs):
    save_store(INGESTED, docs)


def categorize(docs):
    cats = {}
    for d in docs:
        t = d.get("doc_type", "uncategorized")
        cats[t] = cats.get(t, 0) + 1
    return cats


def load_ground_truth():
    gt = {}
    if GROUND_TRUTH.exists():
        for line in GROUND_TRUTH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                row = json.loads(line)
                gt[row["source_file"]] = row
    return gt


# --------------------------------------------------------------------------- #
# Retrieval-only chat preview (replace with an LLM later)
# --------------------------------------------------------------------------- #
_WORD = re.compile(r"[a-z0-9][a-z0-9\-]+")


def _tokens(s):
    return _WORD.findall(s.lower())


def retrieve(query, docs, k=4):
    q = set(_tokens(query))
    if not q:
        return []
    scored = []
    for d in docs:
        title_t = _tokens(d.get("title", ""))
        body_t = _tokens(d.get("text", ""))
        meta_t = _tokens(json.dumps(d.get("metadata", {})))
        score = 0
        for term in q:
            score += 3 * title_t.count(term)
            score += body_t.count(term)
            score += 2 * meta_t.count(term)
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


# --------------------------------------------------------------------------- #
# Chat backed by the manufacturing_rag System (real Phase 3->4->5 pipeline)
# --------------------------------------------------------------------------- #
_RAG = {}            # mode -> built System (lazy, cached)
_RAG_LOCK = threading.Lock()
_INGEST_STATUS = {}  # filename -> {state, ...} (background ingestion progress)


def _ingest_into_live(filename, raw):
    """Background: ingest an uploaded file into the live (hosted) pipeline —
    rich extraction + CHUNKING + embeddings. Updates _INGEST_STATUS live with
    phase + progress fraction + ETA so the UI can show real-time status."""
    started = time.time()
    _INGEST_STATUS[filename] = {"state": "processing", "phase": "queued",
                                "frac": 0.0, "elapsed_s": 0}

    def prog(phase, frac):
        el = time.time() - started
        st = {"state": "processing", "phase": phase, "frac": round(frac, 3),
              "elapsed_s": int(el)}
        if frac > 0.02:
            st["eta_s"] = max(0, int(el * (1 - frac) / frac))   # linear extrapolation
        _INGEST_STATUS[filename] = st

    try:
        rag = get_rag()           # build empty hosted System if needed (fast)
        with _RAG_LOCK:           # queued files wait here -> shown as 'queued'
            res = rag.add_document(filename, raw, progress=prog)
        _INGEST_STATUS[filename] = {"state": "done", **res,
                                    "elapsed_s": int(time.time() - started)}
    except Exception as e:                    # fail toward a clear status, not silent
        _INGEST_STATUS[filename] = {"state": "error", "detail": str(e)}


def get_rag(hosted: bool = True):
    """Lazily build + cache a FRESH (empty) System — the real-data portal answers
    only over YOUR uploaded documents. Always uses hosted mode (OpenAI emb + LLM
    synthesis/vision)."""
    with _RAG_LOCK:
        if "hosted" not in _RAG:
            from manufacturing_rag.app.system import System
            _RAG["hosted"] = System(fresh=True)
        return _RAG["hosted"]


# --------------------------------------------------------------------------- #
# Local-model activation (Ollama): status + warm-load, so chat/ingestion can
# require the models to be loaded and prompt the user to Activate them first.
# --------------------------------------------------------------------------- #
def _ollama_host():
    return (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")


def _model_names(cfg):
    """Configured Ollama model names (None for any lane that isn't ollama:*)."""
    llm, emb = cfg.models.llm, cfg.models.embeddings
    return (llm.split(":", 1)[1] if llm.startswith("ollama:") else None,
            emb.split(":", 1)[1] if emb.startswith("ollama:") else None)


def _ollama_get(route, timeout=5):
    with urllib.request.urlopen(_ollama_host() + route, timeout=timeout) as r:
        return json.load(r)


def models_status():
    """Is the local model stack ready? cloud => always active (no activation)."""
    from manufacturing_rag.config import load_config
    cfg = load_config()
    llm_m, emb_m = _model_names(cfg)
    needed = [m for m in (llm_m, emb_m) if m]
    if not needed:
        return {"provider": "cloud", "active": True,
                "detail": "Cloud models — no activation needed."}
    try:
        tags = _ollama_get("/api/tags")
    except Exception:
        return {"provider": "ollama", "ollama_up": False, "active": False,
                "needed": needed,
                "detail": "Ollama isn't running. Start it (CPU mode), then Activate."}
    base = lambda n: n.split(":")[0]
    pulled = {m.get("name", "") for m in tags.get("models", [])}
    pulled_base = {base(n) for n in pulled}
    try:
        loaded = {m.get("name", "") for m in _ollama_get("/api/ps").get("models", [])}
    except Exception:
        loaded = set()
    loaded_base = {base(n) for n in loaded}
    models = [{"name": m,
               "pulled": m in pulled or base(m) in pulled_base,
               "loaded": m in loaded or base(m) in loaded_base} for m in needed]
    not_pulled = [x["name"] for x in models if not x["pulled"]]
    active = all(x["loaded"] for x in models)
    if not_pulled:
        detail = "Not downloaded: " + ", ".join(not_pulled) + " — run `ollama pull <model>`."
    elif not active:
        detail = "Models downloaded but not loaded — click Activate (first load ~30s on CPU)."
    else:
        detail = "Local models active."
    return {"provider": "ollama", "ollama_up": True, "active": active,
            "models": models, "detail": detail}


def activate_models():
    """Warm-load (and pin via keep_alive=-1) the configured Ollama models."""
    from manufacturing_rag.config import load_config
    cfg = load_config()
    llm_m, emb_m = _model_names(cfg)
    if not (llm_m or emb_m):
        return {"active": True, "provider": "cloud",
                "detail": "Cloud models — no activation needed."}
    from manufacturing_rag.providers import OllamaLLM, OllamaEmbedder
    try:
        if emb_m:
            OllamaEmbedder(model=emb_m).embed(["warm"])
        if llm_m:
            OllamaLLM(model=llm_m).complete("ok")
    except Exception as e:
        return {"active": False, "error": str(e)[:200],
                "detail": f"Activation failed: {str(e)[:160]}"}
    # the warm calls succeeding IS the proof of activation — return success
    # directly rather than re-querying /api/ps (which can race the just-warmed
    # embedder and momentarily report it unloaded).
    return {"provider": "ollama", "ollama_up": True, "active": True,
            "models": [{"name": m, "pulled": True, "loaded": True}
                       for m in (llm_m, emb_m) if m],
            "detail": "Local models active."}


def _citation_view(rag, doc_ids):
    out = []
    for did in doc_ids:
        meta = rag.stores.text.get_meta(did)
        txt = rag.retriever.doc_text(did) if did in rag.stores.doc_ids else ""
        out.append({"doc_id": did, "doc_type": meta.get("doc_type", ""),
                    "source_file": meta.get("source_file", ""),
                    "snippet": " ".join(txt.split())[:240]})
    return out


def chat_answer(message, mode="hosted"):
    """Answer via the real RAG System. Returns {answer, status, citations, ...}."""
    if not message.strip():
        return {"mode": mode, "status": "empty", "answer": "Ask a question.",
                "citations": [], "claims": []}
    st = models_status()
    if not st.get("active"):
        return {"mode": mode, "status": "models_inactive",
                "answer": st.get("detail") or "Local models aren't active.",
                "citations": [], "claims": [], "models": st}
    try:
        rag = get_rag()
        with _RAG_LOCK:                                 # serialize store access (sqlite)
            a = rag.answer(message, mode="agentic" if mode == "agentic" else "deterministic")
    except Exception as e:                              # fail toward abstention
        return {"mode": mode, "status": "error",
                "answer": f"Pipeline error: {e}", "citations": [], "claims": []}

    cite_ids = sorted({c for cl in a.claims for c in (cl.citations or [])})
    claims = [{"type": cl.ctype, "value": str(cl.value)[:80] if cl.value is not None else None,
               "verified": cl.verified} for cl in a.claims]
    plan = [{"step": s.get("step"), "verified": s.get("verified")}
            for s in (a.trace.get("subtasks") or [])]
    out = {"mode": mode, "status": a.status, "answer": a.text,
           "citations": _citation_view(rag, cite_ids), "claims": claims,
           "missing": a.missing, "plan": plan,
           "trace_summary": {k: a.trace.get(k) for k in
                             ("orchestration", "synthesis", "agentic_plan",
                              "coverage", "entities") if k in a.trace}}
    # conflict surfacing: hand the pick-options to the UI (doc_id, value, source, note)
    if a.status == "conflict" and (a.trace or {}).get("conflict"):
        out["conflict"] = a.trace["conflict"]
    return out


def resolve_conflict(question, field, doc_id, mode="hosted"):
    """User picked a source for a disputed field. Record the choice (remember it),
    then answer the question from that source. Returns a normal answer dict."""
    try:
        rag = get_rag()
        from manufacturing_rag.verification.conflict import resolve_choice
        with _RAG_LOCK:
            flag = resolve_choice(rag.stores, field, doc_id)
            if not flag:
                return {"status": "error", "answer": f"No conflict on '{field}' with source {doc_id}.",
                        "citations": [], "claims": []}
            # re-answer: now resolved -> answers from the chosen source
            a = rag.answer(question, mode="agentic" if mode == "agentic" else "deterministic")
    except Exception as e:
        return {"status": "error", "answer": f"Pipeline error: {e}", "citations": [], "claims": []}
    cite_ids = sorted({c for cl in a.claims for c in (cl.citations or [])})
    return {"status": a.status, "answer": a.text, "chosen": doc_id, "field": field,
            "citations": _citation_view(rag, cite_ids),
            "claims": [{"type": cl.ctype, "value": str(cl.value)[:80], "verified": cl.verified}
                       for cl in a.claims]}


def raw_doc(doc_id):
    """Return the raw/indexed text of a document for the 'view raw' link."""
    try:
        rag = get_rag()
        with _RAG_LOCK:
            meta = rag.stores.text.get_meta(doc_id)
            # gather every text unit belonging to this doc, in index order
            parts = [rag.stores.text.texts[i]
                     for i, u in enumerate(rag.stores.text.ids)
                     if (rag.stores.parent_of.get(u, u) == doc_id
                         and rag.stores.text.meta[i].get("kind") == "chunk")]
            text = "\n".join(parts) or rag.retriever.doc_text(doc_id)
            source = rag.stores.originals.get(doc_id) or meta.get("source_file", "")
    except Exception as e:
        return {"doc_id": doc_id, "error": str(e), "text": "", "source_file": ""}
    return {"doc_id": doc_id, "source_file": source, "text": text[:4000]}


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "HeliosRAG/0.1"

    def log_message(self, fmt, *args):  # quieter logs
        pass

    # ---- helpers ----
    def _send(self, code, body=b"", ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def _json_body(self):
        try:
            return json.loads(self._read_body() or b"{}")
        except json.JSONDecodeError:
            return None

    # ---- GET ----
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")
        if path in ("/app.js", "/styles.css"):
            return self._serve_static(path.lstrip("/"))
        if path == "/api/corpus":
            with _LOCK:
                docs = load_corpus()
            return self._send(200, {"docs": docs, "categories": categorize(docs),
                                    "doc_types": ingest.DOC_TYPES})
        if path == "/api/ingested":
            with _LOCK:
                docs = load_ingested()
            return self._send(200, {"docs": docs, "categories": categorize(docs),
                                    "doc_types": ingest.DOC_TYPES})
        if path == "/api/ground-truth":
            return self._send(200, {"ground_truth": list(load_ground_truth().values())})
        if path == "/api/ingest-status":
            return self._send(200, {"status": _INGEST_STATUS})
        if path == "/api/models-status":
            return self._send(200, models_status())
        if path == "/api/graph":
            try:
                rag = get_rag()
                with _RAG_LOCK:
                    return self._send(200, rag.stores.graph.dump())
            except Exception as e:
                return self._send(200, {"nodes": [], "edges": [], "error": str(e)[:120]})
        if path == "/api/raw-doc":
            qs = parse_qs(urlparse(self.path).query)
            doc_id = (qs.get("id") or [""])[0]
            if not doc_id:
                return self._send(400, {"error": "missing id"})
            return self._send(200, raw_doc(doc_id))
        if path == "/api/live-docs":
            # Non-blocking: if an ingestion holds the lock (large PDF embedding),
            # report 'ingesting' instead of hanging the request.
            if not _RAG_LOCK.acquire(blocking=False):
                return self._send(200, {"docs": [], "count": 0, "ingesting": True})
            try:
                docs, built = [], []
                for key, sysm in _RAG.items():
                    built.append(key)
                    try:
                        docs = sysm.live_docs() or docs
                    except Exception:
                        pass
            finally:
                _RAG_LOCK.release()
            return self._send(200, {"docs": docs, "built_systems": built,
                                    "count": len(docs)})
        return self._send(404, {"error": "not found"})

    def _serve_static(self, name):
        f = WEB / name
        if not f.exists():
            return self._send(404, {"error": f"missing {name}"})
        ctype = {"js": "application/javascript", "css": "text/css",
                 "html": "text/html"}.get(name.rsplit(".", 1)[-1], "text/plain")
        self._send(200, f.read_bytes(), ctype + "; charset=utf-8")

    # ---- POST ----
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/chat":
            data = self._json_body() or {}
            return self._send(200, chat_answer(data.get("message", ""),
                                               data.get("mode", "hosted")))

        if path == "/api/activate-models":
            return self._send(200, activate_models())

        if path == "/api/remove-doc":
            data = self._json_body() or {}
            doc_id = data.get("doc_id", "")
            if not doc_id:
                return self._send(400, {"error": "missing doc_id"})
            try:
                rag = get_rag()
                with _RAG_LOCK:
                    res = rag.remove_document(doc_id)
                return self._send(200, res)
            except Exception as e:
                return self._send(500, {"error": str(e)})

        if path == "/api/resolve-conflict":
            data = self._json_body() or {}
            return self._send(200, resolve_conflict(
                data.get("question", ""), data.get("field", ""),
                data.get("doc_id", ""), data.get("mode", "hosted")))

        if path == "/api/upload":
            filename = self.headers.get("X-Filename", "upload.bin")
            raw = self._read_body()
            if not raw:
                return self._send(400, {"error": "empty body"})
            st = models_status()                         # ingestion needs the embedder loaded
            if not st.get("active"):
                return self._send(409, {"error": "models_inactive",
                                        "detail": st.get("detail"), "models": st})
            with _LOCK:
                ingested = load_ingested()
                ids = {d["doc_id"] for d in load_corpus()} | {d["doc_id"] for d in ingested}
                INBOX.mkdir(parents=True, exist_ok=True)
                (INBOX / Path(filename).name).write_bytes(raw)
                draft = ingest.ingest_bytes(Path(filename).name, raw, ids)
                ingested.append(draft)
                save_ingested(ingested)
            # Ingest into the LIVE pipeline in the BACKGROUND (chunk + embed) so
            # the upload returns immediately; the chat can answer once it's "done".
            threading.Thread(target=_ingest_into_live,
                             args=(Path(filename).name, raw), daemon=True).start()
            return self._send(200, {"doc": draft, "live_ingest": "processing"})

        if path == "/api/ingest-raw":
            # ingest every file under raw/ (skip inbox + manifest) into the ingested store
            with _LOCK:
                ingested = load_ingested()
                ids = {d["doc_id"] for d in load_corpus()} | {d["doc_id"] for d in ingested}
                added = []
                rawdir = ROOT / "raw"
                for p in sorted(rawdir.rglob("*")):
                    if (not p.is_file() or p.name == GROUND_TRUTH.name
                            or "inbox" in p.parts):
                        continue
                    d = ingest.ingest_path(p, ids)
                    d["metadata"]["source_file"] = str(p.relative_to(rawdir)).replace("\\", "/")
                    ids.add(d["doc_id"])
                    ingested.append(d)
                    added.append(d)
                save_ingested(ingested)
            return self._send(200, {"added": len(added), "docs": added})

        return self._send(404, {"error": "not found"})

    # ---- PUT (edit) ----
    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/doc":
            qs = parse_qs(urlparse(self.path).query)
            doc_id = (qs.get("id") or [""])[0]
            payload = self._json_body()
            if payload is None:
                return self._send(400, {"error": "invalid JSON"})
            with _LOCK:
                docs = load_ingested()
                idx = next((i for i, d in enumerate(docs) if d["doc_id"] == doc_id), None)
                if idx is None:
                    return self._send(404, {"error": "doc not found"})
                meta = payload.get("metadata", docs[idx].get("metadata", {}))
                if not isinstance(meta, dict):
                    return self._send(400, {"error": "metadata must be an object"})
                new_id = payload.get("doc_id", doc_id)
                if new_id != doc_id and any(d["doc_id"] == new_id for d in docs):
                    return self._send(409, {"error": "doc_id already exists"})
                docs[idx] = {
                    "doc_id": new_id,
                    "doc_type": payload.get("doc_type", docs[idx].get("doc_type")),
                    "title": payload.get("title", docs[idx].get("title", "")),
                    "text": payload.get("text", docs[idx].get("text", "")),
                    "metadata": meta,
                }
                save_ingested(docs)
            return self._send(200, {"doc": docs[idx]})
        return self._send(404, {"error": "not found"})

    # ---- DELETE ----
    def do_DELETE(self):
        path = urlparse(self.path).path
        if path == "/api/doc":
            qs = parse_qs(urlparse(self.path).query)
            doc_id = (qs.get("id") or [""])[0]
            with _LOCK:
                docs = load_ingested()
                new = [d for d in docs if d["doc_id"] != doc_id]
                if len(new) == len(docs):
                    return self._send(404, {"error": "doc not found"})
                save_ingested(new)
            return self._send(200, {"deleted": doc_id})
        return self._send(404, {"error": "not found"})


def _warm_up():
    """Build the live (hosted) System at startup so any previously-uploaded files
    in raw/inbox are ingested (chunked + embedded) automatically — loads the
    persisted index instantly if present, else ingests once and persists."""
    try:
        rag = get_rag()
        n = len(rag.stores.doc_ids)
        if n:
            print(f"  warm-up: {n} document(s) live in the chat pipeline.")
    except Exception as e:
        print(f"  warm-up skipped: {e}")


def main():
    port = 8000
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Real-data RAG portal running at  http://localhost:{port}")
    print("  - Chat:       ask questions over YOUR ingested documents (Claude Haiku)")
    print("  - Ingestion:  upload real files -> chunked + embedded into the live pipeline")
    print("Press Ctrl+C to stop.")
    threading.Thread(target=_warm_up, daemon=True).start()   # ingest inbox on startup
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()

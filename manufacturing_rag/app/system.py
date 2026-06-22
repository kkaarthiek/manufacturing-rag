"""
End-to-end System — the single query->answer entry point.  STATUS: IMPLEMENTED.

Ties the phases together: build stores (1-2) -> retrieve (3) -> verify/answer (4)
-> orchestrate multi-part (5). The answer path:

  abstain-first (Phase-4 answerability) ->
  deterministic op (exact slot-fill / calc / count) if one matches ->
  else GROUNDED SYNTHESIS over retrieved evidence (LLM, grounded) ->
  multi-part questions go through the verified-chain orchestrator.

Every shipped answer is grounded-or-abstained.
"""

from __future__ import annotations

from ..config import load_config
from ..providers import get_llm
from ..indexing.load import build_index
from ..retrieval.router import Retriever
from ..retrieval.agent import AgenticRetriever
from ..verification.abstain import decide
from ..verification.assemble import answer as deterministic_answer
from ..verification.synthesize import synthesize
from ..orchestration import is_multipart, orchestrate
from ..contracts import Answer, Entity, Edge
from ..ingestion.incremental import ingest_upload, chunk_text, classify_doc_type, resolve_mentions
from ..ingestion.extract import extract_chunk
from ..ingestion.derive import derive_units
from ..ingestion.rich import rich_extract
from ..contracts import CanonicalDoc, StructuredRecord


class System:
    def __init__(self, hosted: bool = True, derive: bool | None = None,
                 fresh: bool = False):
        self.cfg = load_config()
        self.fresh = fresh
        # derive (multi-granularity) defaults to True (extraction cache needed)
        derive = True if derive is None else derive
        self.stores, self.meta = build_index(self.cfg, persist=False, derive=derive,
                                             fresh=fresh)
        self.retriever = Retriever(self.cfg, self.stores)
        self.agent = AgenticRetriever(self.cfg, self.stores)
        self.llm = get_llm(self.cfg)
        # fresh portal: load the persisted live index if present (fast, no
        # re-extraction); otherwise replay inbox uploads once and persist.
        if fresh:
            if not self._load_live():
                self._replay_inbox()
                self._save_live()
        else:
            self._replay_inbox()

    def _live_dir(self):
        from pathlib import Path
        d = Path(self.cfg.paths.artifacts) / f"live_{self.cfg.models.provider_mode}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_live(self):
        """Persist the live stores so a restart reloads instantly (no re-extract)."""
        import json
        d = self._live_dir()
        try:
            self.stores.text.save(d / "text_index.json")
            self.stores.graph.save(d / "graph.json")
            rows = self.stores.structured.conn.execute(
                "SELECT tbl,key,fields,raw,normalized,units,validity,source_doc_id "
                "FROM records").fetchall()
            (d / "structured.json").write_text(json.dumps(rows), encoding="utf-8")
            (d / "meta.json").write_text(json.dumps({
                "doc_ids": list(self.stores.doc_ids), "alias_map": self.stores.alias_map,
                "parent_of": self.stores.parent_of, "originals": self.stores.originals,
            }), encoding="utf-8")
        except Exception:
            pass

    def _load_live(self) -> bool:
        import json
        from pathlib import Path
        d = self._live_dir()
        if not (d / "text_index.json").exists() or not (d / "meta.json").exists():
            return False
        try:
            self.stores.text.load(d / "text_index.json")
            self.stores.graph.load(d / "graph.json")
            for r in json.loads((d / "structured.json").read_text(encoding="utf-8")):
                self.stores.structured.conn.execute(
                    "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?,?)", r)
            self.stores.structured.commit()
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            self.stores.doc_ids = set(m["doc_ids"])
            self.stores.alias_map = m["alias_map"]
            self.stores.parent_of = m["parent_of"]
            self.stores.originals = m["originals"]
            self.retriever = Retriever(self.cfg, self.stores)
            self.agent = AgenticRetriever(self.cfg, self.stores)
            return bool(self.stores.doc_ids)
        except Exception:
            return False

    def _replay_inbox(self):
        """Re-ingest any previously-uploaded files (raw/inbox/) so uploads persist
        across restarts and are present whenever the System is (re)built."""
        from .. import REPO_ROOT
        inbox = REPO_ROOT / "raw" / "inbox"
        if not inbox.exists():
            return
        for p in sorted(inbox.glob("*")):
            if p.is_file():
                try:
                    self.add_document(p.name, p.read_bytes())
                except Exception:
                    pass

    def add_document(self, filename: str, raw: bytes, progress=None) -> dict:
        """Incrementally ingest an uploaded file into the LIVE stores (spec 6.11):
        parse+classify+resolve -> add doc node + MENTIONS edges + text-index chunk
        (+ Haiku-derived propositions/questions when hosted). Idempotent, no rebuild.
        After this returns, the chat can answer over the new document.
        `progress(phase, frac)` is called with the current phase + overall [0,1]
        fraction so callers can show a live status + ETA."""
        def _p(phase, frac):
            if progress:
                try: progress(phase, max(0.0, min(1.0, frac)))
                except Exception: pass
        _p("parsing", 0.02)
        # RICH extraction: digital text + structured tables + image captions /
        # scanned-page OCR — robust to real-industry PDFs (spec 6.2/6.4)
        rd = rich_extract(filename, raw, vision_llm=self.llm, hosted=True,
                          max_images=self.cfg.thresholds.vision_max_images,
                          max_ocr_pages=self.cfg.thresholds.vision_max_ocr_pages)
        from ..ingestion.incremental import _slug
        did = _slug(filename)
        cdoc = CanonicalDoc(
            id=did, doc_type=classify_doc_type(rd.text, filename),
            source_file=filename, format=rd.text and "pdf" or "bin",
            clean_text=rd.text, structured_fields={"uploaded": True,
                "tables": len(rd.tables), "image_captions": len(rd.image_captions),
                "ocr_used": rd.ocr_used, "extraction_flags": rd.flags},
            entities=resolve_mentions(rd.text, self.stores.alias_map),
            provenance={"file": filename, "uploaded": True})

        # register name-like aliases (capitalized phrases) -> this doc, so the
        # chat can resolve the new entity by name (e.g. "Apex Components")
        import re as _re
        head = cdoc.clean_text[:300]
        _SKIP = ("supplier", "part ", "work ", "purchase", "material", "quality",
                 "standard operating", "profile")
        for ph in _re.findall(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})\b", head):
            toks = ph.split()
            # register the full phrase AND its first-two-words (drops Inc/LLC/GmbH suffix)
            for al in {ph.lower(), " ".join(toks[:2]).lower()}:
                if (len(al) >= 4 and al not in self.stores.alias_map
                        and not al.startswith(_SKIP)):
                    self.stores.alias_map[al] = did

        # graph: doc node + MENTIONS edges to resolved entities (multi-hop reach)
        if not self.stores.graph.has_node(did):
            self.stores.graph.add_entity(Entity(canonical_id=did, type="doc",
                                                source_links=[did]))
        for ent in cdoc.entities:
            if not self.stores.graph.has_node(ent):
                self.stores.graph.add_entity(Entity(canonical_id=ent, type="mention",
                                                    source_links=[did]))
            self.stores.graph.add_edge(Edge(src=did, rel="MENTIONS", dst=ent,
                                            source_doc_id=did, trust=1.0))

        # text index: CHUNK the doc (real multi-page PDFs are too big for one unit)
        base_meta = {"doc_id": did, "doc_type": cdoc.doc_type,
                     "source_file": filename, "entities": cdoc.entities,
                     "trust": 1.0, "uploaded": True}
        chunks = chunk_text(cdoc.clean_text) or [cdoc.clean_text[:1200]]
        n_extract = min(len(chunks), self.cfg.thresholds.ingest_extract_chunks)
        # weighted work for ETA: embedding a chunk ~1 unit, extracting a chunk ~15
        # (the LLM pass is far slower than an embed). +1 for parse already done.
        total_w = len(chunks) * 1.0 + n_extract * 15.0 + 1.0
        done_w = 1.0
        self.stores.doc_ids.add(did)
        self.stores.originals[did] = filename
        # the doc-level unit (id == did) holds the first chunk so the doc is a
        # retrievable node; remaining chunks are child units pointing to it.
        self.stores.text.add_unit(did, f"{did}\n{chunks[0]}",
                                  {**base_meta, "kind": "chunk", "parent": did})
        self.stores.parent_of[did] = did
        done_w += 1; _p("embedding", done_w / total_w)
        for ci, ch in enumerate(chunks[1:], 1):
            cid = f"{did}::c{ci}"
            self.stores.text.add_unit(cid, ch,
                                      {**base_meta, "kind": "chunk", "parent": did})
            self.stores.parent_of[cid] = did
            done_w += 1; _p("embedding", done_w / total_w)

        derived = 0
        # extraction pass over a CAPPED set of chunks (cost/context control)
        for ch in chunks[:self.cfg.thresholds.ingest_extract_chunks]:
            try:
                ex = extract_chunk(self.llm, ch, n=1)
                _ctx, units, edges = derive_units(did, ch, ex)
                for u in units:
                    self.stores.text.add_unit(u.id, u.text,
                                              {**base_meta, "kind": u.kind,
                                               "parent": did, "trust": u.trust})
                    self.stores.parent_of[u.id] = did
                    derived += 1
                for ed in edges:
                    if (self.stores.graph.has_node(ed.src)
                            and self.stores.graph.has_node(ed.dst)):
                        self.stores.graph.add_edge(ed)
            except Exception:
                pass
            done_w += 15; _p("extracting", done_w / total_w)

        # structured tables -> per-row records (spec 6.4: tables -> per-row records
        # with header context). Exact, queryable; the markdown is also in the text.
        for ti, tbl in enumerate(rd.tables):
            rows = tbl["rows"]
            header = rows[0] if rows else []
            for ri, row in enumerate(rows[1:], 1):
                fields = {header[ci] if ci < len(header) else f"col{ci}": v
                          for ci, v in enumerate(row)}
                self.stores.structured.put(StructuredRecord(
                    table=f"{did}_table{ti}", key=f"{did}::t{ti}r{ri}",
                    fields=fields, source_doc_id=did))
        self.stores.structured.commit()

        # refresh retriever doc-text cache so reranking sees the new doc
        _p("finalizing", 0.99)
        self.retriever = Retriever(self.cfg, self.stores)
        self.agent = AgenticRetriever(self.cfg, self.stores)
        if self.fresh:
            self._save_live()                           # persist for fast restart
        return {"doc_id": did, "doc_type": cdoc.doc_type,
                "entities": cdoc.entities, "chunks": len(chunks),
                "tables": len(rd.tables), "image_captions": len(rd.image_captions),
                "ocr_used": rd.ocr_used, "flags": rd.flags,
                "derived_units": derived, "indexed": True}

    def live_docs(self) -> list:
        """Summary of every document the chat can answer over (for the UI)."""
        out = {}
        for i, uid in enumerate(self.stores.text.ids):
            m = self.stores.text.meta[i]
            did = m.get("parent") or uid
            if did not in self.stores.doc_ids:
                continue
            d = out.setdefault(did, {"doc_id": did, "doc_type": m.get("doc_type"),
                                     "source_file": m.get("source_file"),
                                     "chunks": 0, "units": 0})
            if m.get("kind") == "chunk":
                d["chunks"] += 1
            d["units"] += 1
        return sorted(out.values(), key=lambda x: x["source_file"] or x["doc_id"])

    def answer(self, query: str, mode: str = "deterministic") -> Answer:
        # FRESH/real-data portal: retrieve over the user's docs -> grounded
        # synthesis or abstain. (Skip the synthetic-corpus deterministic ops.)
        if self.fresh:
            return self._answer_fresh(query, mode)

        # multi-part -> verified-chain orchestrator (Phase 5)
        if is_multipart(query, self.stores):
            a = orchestrate(query, self.stores)
            if a.status == "answered":
                return a
            # fall through to synthesis if the chain didn't resolve cleanly

        # Phase 4 abstain-first + deterministic op (+ conflict surfacing)
        det = deterministic_answer(query, self.stores)
        if det.status in ("answered", "abstained", "conflict"):
            return det

        # else: retrieve evidence (Phase 3) + grounded synthesis (Phase 4 / 9.2)
        retr = self.agent if mode == "agentic" else self.retriever
        evidence, cov, trace = retr.retrieve(query, k=self.cfg.thresholds.retrieve_k)
        if not cov.sufficient:
            return Answer(text="Not enough grounded evidence to answer.", claims=[],
                          status="abstained", missing=["coverage"],
                          trace={"coverage": cov.score, "retrieval": trace})
        d = decide(query, self.stores)
        exact = {}
        a = synthesize(query, evidence, self.llm, exact_values=exact,
                       top_n=self.cfg.thresholds.synthesis_top_n)
        a.trace = {**(a.trace or {}), "retrieval_mode": mode,
                   "coverage": cov.score, "entities": d.entities}
        return a

    def _answer_fresh(self, query: str, mode: str) -> Answer:
        """Real-data path: retrieve the relevant CHUNKS (not parent-deduped docs —
        a real PDF is many chunks), rerank, then grounded synthesis or abstain."""
        from ..contracts import Evidence
        from ..retrieval.coverage import assess
        if not self.stores.doc_ids:
            return Answer(text="No documents ingested yet — upload files first.",
                          claims=[], status="abstained", missing=["documents"],
                          trace={"reason": "empty knowledge base"})

        # CHUNK-level hybrid retrieval (vector + BM25 over every chunk/proposition)
        hits = self.stores.text.search(query, 40)
        if not hits:
            return Answer(text="I couldn't find that in your documents.", claims=[],
                          status="abstained", missing=["no match"], trace={})
        id_index = {u: i for i, u in enumerate(self.stores.text.ids)}
        cand = [(u, self.stores.text.texts[id_index[u]]) for u, _ in hits if u in id_index]
        # rerank for precision, but NEVER drop the top hybrid hits (rerank must not
        # reduce recall): synthesis context = union(top-6 hybrid, top reranked).
        scores = self.retriever.reranker.rerank(query, [t for _, t in cand])
        reranked = [c for c, _ in sorted(zip(cand, scores), key=lambda x: x[1], reverse=True)]
        ordered, seen = [], set()
        floor = self.cfg.thresholds.fresh_hybrid_floor
        for u, txt in cand[:floor] + reranked:          # guarantee top hybrid hits first
            if u not in seen:
                seen.add(u); ordered.append((u, txt))
        ordered = ordered[:self.cfg.thresholds.fresh_context_max]
        evidence = [Evidence(id=u, kind="chunk", content=txt,
                             source={"doc_id": self.stores.parent_of.get(u, u)},
                             scores={}) for u, txt in ordered]

        cov = assess(query, [e.content for e in evidence],
                     self.cfg.thresholds.coverage_threshold,
                     max(scores) if scores else 0.0)
        if not cov.sufficient:
            return Answer(text="I couldn't find that in your documents.", claims=[],
                          status="abstained", missing=["not in ingested documents"],
                          trace={"coverage": cov.score})
        a = synthesize(query, evidence, self.llm,
                       top_n=self.cfg.thresholds.fresh_context_max)
        a.trace = {**(a.trace or {}), "retrieval_mode": mode, "coverage": cov.score,
                   "chunks_considered": len(evidence)}
        return a


__all__ = ["System"]

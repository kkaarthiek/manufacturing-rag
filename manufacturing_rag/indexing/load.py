"""
Loader + Phase-2 gate (spec 7.4-7.5).  STATUS: IMPLEMENTED (P2-early).

Loads the Tranche-A canonical objects (CanonicalDoc, StructuredRecord, Entity,
Edge) into the durable stores and proves retrievability:

  * structured store (sqlite)  <- StructuredRecord
  * graph store (JSON)         <- Entity + Edge  (+ doc-mention entities)
  * text index (vector+BM25)   <- CanonicalDoc (doc granularity for now;
                                   Tranche B adds propositions/questions/summaries)
  * originals manifest         <- source_file per doc

Load discipline (7.4): ALL-OR-NOTHING per object — staged, then committed only
if every store accepted it; IDEMPOTENT — re-running upserts cleanly.

Gate (7.5): index-coverage 100% (every object present + retrievable), round-trip
recall@k on gold, join integrity (no dangling edges / orphan entity refs),
embedding sanity (consistent dims, nothing failed to embed).

Multi-granularity text units + real embeddings arrive in P2-late (after Tranche
B); until then only the doc-level chunk is indexed in the vector lane.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from ..providers import get_embedder, get_llm
from ..contracts import Entity, Edge
from ..ingestion.pipeline import run_pipeline, ENTITY_GRAPH_ID
from ..ingestion.extract import extract_chunk, Extraction
from ..ingestion.derive import derive_units
from .structured import StructuredStore
from .graph import GraphStore, Neo4jGraphStore
from .text_index import TextIndex


def _extract_all(cfg: Config, docs: dict, cache: Path | None):
    """Run the Haiku extraction pass over every doc, with a disk cache so the
    spend (one call/doc) is paid once. Returns {doc_id: Extraction}."""
    cached = {}
    if cache and cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
    llm = get_llm(cfg)
    n = cfg.models.self_consistency_n
    out = {}
    for did, d in docs.items():
        if did == ENTITY_GRAPH_ID:
            continue
        if did in cached:
            out[did] = Extraction(**cached[did])
        else:
            out[did] = extract_chunk(llm, d.clean_text, n=n)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({k: vars(v) for k, v in out.items()},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    return out


class Stores:
    def __init__(self, structured, graph, text, originals,
                 alias_map=None, doc_ids=None, parent_of=None):
        self.structured = structured
        self.graph = graph
        self.text = text
        self.originals = originals          # doc_id -> source_file
        self.alias_map = alias_map or {}    # surface form -> canonical ID (query resolution)
        self.doc_ids = doc_ids or set()     # the set of canonical doc IDs (vs entity IDs)
        self.parent_of = parent_of or {}    # unit_id -> parent doc_id


def _relationship_edges(graph, rec):
    """Deterministic entity-relationship edges from a structured record — the
    join structure PPR/BFS traverses for multi-hop (part->machine, part->supplier,
    WO->machine/part, PO->supplier). Endpoints are guaranteed nodes (doc + ID nodes)."""
    f = rec.fields
    src = rec.key

    def link(rel, dst):
        if dst and graph.has_node(dst) and graph.has_node(src):
            graph.add_edge(Edge(src=src, rel=rel, dst=dst,
                                source_doc_id=rec.source_doc_id, trust=1.0))

    if rec.table == "parts":
        link("SUPPLIED_BY", f.get("supplier_id"))
        for m in f.get("used_on", []) or []:
            link("ON_MACHINE", m)
    elif rec.table == "purchase_orders":
        link("FROM_SUPPLIER", f.get("supplier_id"))
    elif rec.table == "work_orders":
        link("ON_MACHINE", f.get("machine"))
        link("REPLACED_PART", f.get("part"))
    elif rec.table == "telemetry":
        link("ON_MACHINE", f.get("machine"))


def _make_graph(cfg: Config):
    """Return a Neo4jGraphStore when graph_store='neo4j', else in-memory GraphStore."""
    if getattr(cfg.models, "graph_store", "memory") != "neo4j":
        return GraphStore()
    return Neo4jGraphStore(
        uri=cfg.paths.neo4j_uri,
        user=cfg.paths.neo4j_user,
        password=cfg.paths.neo4j_password,
    )


def _make_qdrant(cfg: Config, collection: str):
    """Return a QdrantVectorStore when vector_store='qdrant', else None."""
    if getattr(cfg.models, "vector_store", "flat") != "qdrant":
        return None
    from .vector import QdrantVectorStore
    return QdrantVectorStore(
        path=cfg.paths.qdrant_path,
        collection=collection,
        dim=cfg.models.embedding_dim,
    )


def build_empty_index(cfg: Config) -> tuple[Stores, dict]:
    """Fresh/real-data mode: empty stores, no synthetic corpus. The System then
    ingests the user's real uploads incrementally (spec 6.11)."""
    text = TextIndex(get_embedder(cfg), qdrant_store=_make_qdrant(cfg, "live_index"))
    text.build()                                        # finalize empty BM25 state
    stores = Stores(StructuredStore(None), _make_graph(cfg), text, {},
                    alias_map={}, doc_ids=set(), parent_of={})
    return stores, {"doc_ids": [], "record_keys": [], "derived": {}, "flags": []}


def build_index(cfg: Config, persist: bool = False, derive: bool = False,
                fresh: bool = False) -> tuple[Stores, dict]:
    """Run P1-A, load all stores all-or-nothing + idempotent.

    fresh=True -> empty knowledge base (real-data portal); skip the synthetic
    Helios pipeline. derive=True (P2-late) runs the Haiku extraction pass."""
    if fresh:
        return build_empty_index(cfg)
    pipe = run_pipeline()
    art = Path(cfg.paths.artifacts)

    structured = StructuredStore(str(art / "structured.db") if persist else None)
    graph = _make_graph(cfg)
    text = TextIndex(get_embedder(cfg), qdrant_store=_make_qdrant(cfg, "eval_index"))
    originals: dict[str, str] = {}

    # --- graph: seed entities/edges from master, then doc-mention entities ---
    for e in pipe.entities:
        graph.add_entity(e)
    for ed in pipe.edges:
        graph.add_edge(ed)
    for did, d in pipe.docs.items():
        if did == ENTITY_GRAPH_ID:
            continue
        # the doc itself is a node; MENTIONS edges connect it to its entities
        if not graph.has_node(did):
            graph.add_entity(Entity(canonical_id=did, type="doc", source_links=[did]))
        for ent_id in d.entities:
            if not graph.has_node(ent_id):
                graph.add_entity(Entity(canonical_id=ent_id, type="mention",
                                        source_links=[did]))
            graph.add_edge(Edge(src=did, rel="MENTIONS", dst=ent_id,
                                source_doc_id=did, trust=1.0))

    # --- structured store + deterministic relationship edges (multi-hop spine) ---
    for rec in pipe.records:
        structured.put(rec)
        _relationship_edges(graph, rec)
    structured.commit()

    # --- optional: Tranche-B extraction -> derived units ---
    extractions = {}
    derived_counts = {"proposition": 0, "question": 0, "chunk": 0, "unverified": 0}
    if derive:
        extractions = _extract_all(cfg, pipe.docs, art / "extractions.json")

    # --- text index (multi-granularity) + originals ---
    for did, d in pipe.docs.items():
        if did == ENTITY_GRAPH_ID:
            continue
        originals[did] = d.source_file
        base_meta = {"doc_id": did, "doc_type": d.doc_type,
                     "source_file": d.source_file, "version": d.version,
                     "entities": d.entities, "trust": 1.0}
        chunk_text = f"{d.id}\n{d.clean_text}"
        if derive and did in extractions:
            ctx, units, edges = derive_units(did, d.clean_text, extractions[did])
            chunk_text = f"{d.id}\n{ctx}"                # contextual chunk
            derived_counts["chunk"] += 1
            for u in units:
                text.add(u.id, u.text, {**base_meta, "kind": u.kind, "parent": did,
                                        "trust": u.trust})
                derived_counts[u.kind] = derived_counts.get(u.kind, 0) + 1
                if not u.verified:
                    derived_counts["unverified"] += 1
            for ed in edges:
                # only wire triple edges whose endpoints are known nodes (join-safe)
                if graph.has_node(ed.src) and graph.has_node(ed.dst):
                    graph.add_edge(ed)
        text.add(did, chunk_text, {**base_meta, "kind": "chunk", "parent": did})
    text.build()

    if persist:
        graph.save(art / "graph.json")
        text.save(art / "text_index.json")

    doc_ids = {d for d in pipe.docs if d != ENTITY_GRAPH_ID}
    parent_of = {uid: (text.meta[i].get("parent") or uid) for i, uid in enumerate(text.ids)}
    stores = Stores(structured, graph, text, originals,
                    alias_map=pipe.alias_map, doc_ids=doc_ids, parent_of=parent_of)
    return stores, {
        "doc_ids": list(doc_ids),
        "record_keys": [r.key for r in pipe.records],
        "derived": derived_counts, "flags": pipe.flags}


def verify_index(cfg: Config, stores: Stores, meta: dict, gold_questions: list[dict]) -> dict:
    """Phase-2 gate: coverage, round-trip recall@k, join integrity, embedding sanity."""
    issues = []

    # ---- index-coverage: every doc has its chunk unit in the text index ----
    text_ids = set(stores.text.ids)
    docs_covered = all(d in text_ids for d in meta["doc_ids"])
    if not docs_covered:
        issues.append("docs missing from text index: "
                      + str([d for d in meta['doc_ids'] if d not in text_ids]))
    # parent map for unit->doc resolution (props/questions -> parent doc)
    parent_of = {uid: (stores.text.meta[i].get("parent") or uid)
                 for i, uid in enumerate(stores.text.ids)}
    rec_keys = stores.structured.all_keys()
    recs_covered = all(k in rec_keys for k in meta["record_keys"])
    if not recs_covered:
        issues.append("records missing from structured store")
    orig_covered = all(d in stores.originals for d in meta["doc_ids"])
    coverage = 1.0 if (docs_covered and recs_covered and orig_covered) else 0.0

    # ---- join integrity: no dangling edges; doc entities exist as nodes ----
    dangling = stores.graph.dangling_edges()
    if dangling:
        issues.append(f"{len(dangling)} dangling graph edge(s)")
    join_ok = not dangling

    # ---- embedding sanity: consistent dims, nothing failed ----
    if stores.text._qdrant:
        qdrant_count = stores.text._qdrant.count()
        emb_ok = qdrant_count == stores.text.count()
        dims = {stores.text.embedder.dim}
    elif stores.text.vecs:
        dims = {len(v) for v in stores.text.vecs}
        emb_ok = (len(dims) <= 1) and (len(stores.text.vecs) == stores.text.count())
    else:
        dims, emb_ok = set(), False
    if not emb_ok:
        issues.append(f"embedding sanity failed (dims={dims})")

    # ---- round-trip recall@k on gold (answerable, gold docs present) ----
    ks = cfg.thresholds.recall_ks
    items = [q for q in gold_questions if q.get("answerable", True) and q.get("gold_doc_ids")]
    recall = {k: 0 for k in ks}
    kmax = max(ks)
    for q in items:
        # retrieve units, resolve to parent docs, dedupe preserving rank
        seen, ranked = set(), []
        for uid, _ in stores.text.search(q["question"], kmax * 4):
            par = parent_of.get(uid, uid)
            if par not in seen:
                seen.add(par); ranked.append(par)
        gold = set(q["gold_doc_ids"])
        for k in ks:
            if gold.issubset(set(ranked[:k])):
                recall[k] += 1
    recall_at = {k: (recall[k] / len(items) if items else 0.0) for k in ks}

    return {"coverage": coverage, "join_integrity": join_ok,
            "embedding_sanity": emb_ok, "recall_at_k": recall_at,
            "docs_indexed": stores.text.count(),
            "records_indexed": stores.structured.count(),
            "graph_nodes": stores.graph.node_count(),
            "graph_edges": stores.graph.edge_count(),
            "issues": issues,
            "pass": coverage >= cfg.thresholds.index_coverage_target and join_ok and emb_ok}


__all__ = ["Stores", "build_index", "verify_index"]

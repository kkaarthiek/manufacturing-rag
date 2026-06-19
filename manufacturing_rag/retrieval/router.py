"""
Router (spec 8.2, 8.6, 8.7).  STATUS: IMPLEMENTED (deterministic mode).

Fan-out to the matching lanes; WHEN IN DOUBT RUN MULTIPLE AND UNION (the union is
the recall floor). Over-retrieve -> RRF fuse -> rerank -> coverage check ->
Evidence[] + coverage signal for Phase 4.

Both modes share this spine; agentic mode (agent.py) seeds from this
deterministic floor, so opting in can only ADD evidence — recall never drops.
"""

from __future__ import annotations

from ..config import Config
from ..contracts import Evidence
from ..providers import get_reranker
from .understand import understand
from .lanes import hybrid_lane, graph_lane, structured_lane
from .fuse_rerank import rrf_merge, rerank
from .coverage import assess


class Retriever:
    def __init__(self, cfg: Config, stores):
        self.cfg = cfg
        self.stores = stores
        self.reranker = get_reranker(cfg)
        # doc text for reranking: id + clean text (from the index chunk unit)
        self._doc_text = {}
        for i, uid in enumerate(stores.text.ids):
            if stores.text.meta[i].get("kind") == "chunk":
                self._doc_text[uid] = stores.text.texts[i]

    def doc_text(self, doc_id: str) -> str:
        return self._doc_text.get(doc_id, doc_id)

    def retrieve(self, query: str, k: int = 10, mode: str = "deterministic"):
        """Return (Evidence[], coverage, trace). Deterministic fan-out + union."""
        plan = understand(query, self.stores.alias_map)

        lanes = {"hybrid": hybrid_lane(self.stores, plan, k=max(k, 20)),
                 "graph": graph_lane(self.stores, plan, depth=3, k=max(k, 20)),
                 "structured": structured_lane(self.stores, plan, k=max(k, 20))}

        fused = rrf_merge(lanes)
        reranked = rerank(self.reranker, query, fused, self.doc_text, top_k=k)
        ev_texts = [self.doc_text(d) for d, _, _ in reranked]
        rerank_top = reranked[0][1] if reranked else 0.0
        cov = assess(query, ev_texts, self.cfg.thresholds.coverage_threshold, rerank_top)

        evidence = [Evidence(
            id=doc_id, kind="chunk", content=self.doc_text(doc_id),
            source={"doc_id": doc_id, **self._src(doc_id)},
            entities=plan.entities, scores={"rerank": score},
            trust=1.0) for doc_id, score, _ in reranked]

        trace = {"query": query, "mode": mode, "entities": plan.entities,
                 "qtypes": plan.qtypes,
                 "lane_counts": {ln: len(r) for ln, r in lanes.items()},
                 "fused": len(fused), "coverage": cov.score,
                 "sufficient": cov.sufficient}
        return evidence, cov, trace

    def candidate_docs(self, query: str, k: int = 10):
        """Recall-floor view: union doc_ids (pre-rerank) for the recall gate."""
        plan = understand(query, self.stores.alias_map)
        lanes = {"hybrid": hybrid_lane(self.stores, plan, k=max(k, 20)),
                 "graph": graph_lane(self.stores, plan, depth=3, k=max(k, 20)),
                 "structured": structured_lane(self.stores, plan, k=max(k, 20))}
        fused = rrf_merge(lanes)
        return [d for d, _, _ in fused], lanes

    def _src(self, doc_id):
        meta = self.stores.text.get_meta(doc_id)
        return {"doc_type": meta.get("doc_type"), "source_file": meta.get("source_file"),
                "version": meta.get("version")}


__all__ = ["Retriever"]

"""
Fusion + rerank (spec 8.4).  STATUS: IMPLEMENTED.

Union lane outputs -> RRF merge -> de-duplicate (collapse the same doc from
multiple lanes, keep provenance) -> cross-encoder rerank (calibrated; offline
LexicalReranker, zerank-2 when hosted). Rerank is the single largest precision
lever — it is what lets the high-recall union survive as a precise top-k.
"""

from __future__ import annotations


# Exact/entity-grounded lanes outweigh fuzzy text (spec 8.3: exact facts come
# from the structured store / graph, not prose). Weighted RRF surfaces them.
LANE_WEIGHTS = {"structured": 3.0, "graph": 2.0, "hybrid": 1.0}


def rrf_merge(lane_results: dict[str, list], k: int = 60, weights: dict | None = None):
    """lane_results: {lane_name: [(doc_id, score)]} -> [(doc_id, rrf, lanes)]."""
    weights = weights or LANE_WEIGHTS
    agg: dict[str, float] = {}
    prov: dict[str, set] = {}
    for lane, results in lane_results.items():
        w = weights.get(lane, 1.0)
        for rank, (doc_id, _) in enumerate(results, 1):
            agg[doc_id] = agg.get(doc_id, 0.0) + w / (k + rank)
            prov.setdefault(doc_id, set()).add(lane)
    fused = [(d, s, sorted(prov[d])) for d, s in agg.items()]
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused


def rerank(reranker, query: str, fused, doc_text, top_k: int):
    """Cross-encoder rerank the fused candidates; return precise top_k.
    `doc_text(doc_id) -> str` supplies the text the reranker scores."""
    if not fused:
        return []
    docs = [doc_text(d) for d, _, _ in fused]
    scores = reranker.rerank(query, docs)
    rescored = [(fused[i][0], scores[i], fused[i][2]) for i in range(len(fused))]
    rescored.sort(key=lambda x: x[1], reverse=True)
    return rescored[:top_k]


__all__ = ["rrf_merge", "rerank"]

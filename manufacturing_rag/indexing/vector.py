"""
Vector index (spec 7.1, 7.3).  STATUS: SKELETON.

Embeds contextual chunks + propositions + questions + summary nodes (multi-
granularity), each pointing to its parent. At 42 docs use EXACT flat search
(zero approximation); switch to HNSW with high `ef` only when the corpus
outgrows exact search. Offline default = brute-force cosine over HashingEmbedder.
"""

from __future__ import annotations

import math

from ..providers import Embedder


class FlatVectorIndex:
    """Exact (brute-force) cosine index — the accurate default at this scale."""
    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.ids: list[str] = []
        self.vecs: list[list[float]] = []
        self.meta: list[dict] = []

    def add(self, unit_id: str, text: str, metadata: dict):
        self.ids.append(unit_id)
        self.vecs.append(self.embedder.embed([text])[0])
        self.meta.append(metadata)

    def search(self, query: str, k: int = 10):
        if not self.vecs:
            return []
        q = self.embedder.embed([query])[0]
        sims = [(self.ids[i], sum(a * b for a, b in zip(q, v)))
                for i, v in enumerate(self.vecs)]
        sims.sort(key=lambda x: x[1], reverse=True)
        return sims[:k]

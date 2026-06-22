"""
Text index (spec 7.1, 7.3) — hybrid vector + contextual-BM25.  STATUS: IMPLEMENTED.

Indexes retrieval units (Phase-2 P2-early: canonical docs at doc granularity;
Tranche-B/P2-late adds propositions + questions + summary nodes). Each unit
carries the metadata schema (entity IDs, doc_type, source/provenance, version,
trust, parent pointer). Search = RRF fusion of exact flat-vector (OpenAI
embeddings via FlatVectorIndex or Qdrant) + BM25 — the spec's recall floor.

At 42 docs the vector lane is EXACT (brute-force cosine), zero approximation
(spec 7.3). Persistable to JSON for idempotent reload.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from ..providers import Embedder, tokenize


def rrf_fuse(*ranked_lists, k: int = 60):
    """Reciprocal-rank fusion of ranked [(id, score)] lists -> [(id, rrf)]."""
    agg: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, (uid, _) in enumerate(lst, 1):
            agg[uid] = agg.get(uid, 0.0) + 1.0 / (k + rank)
    return sorted(agg.items(), key=lambda x: x[1], reverse=True)


class TextIndex:
    def __init__(self, embedder: Embedder, qdrant_store=None):
        """qdrant_store: optional QdrantVectorStore. When set, vectors are
        persisted there instead of self.vecs (which stays empty). BM25 always
        lives in-memory."""
        self.embedder = embedder
        self._qdrant = qdrant_store
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.meta: list[dict] = []
        self.vecs: list[list[float]] = []   # populated only when _qdrant is None
        # bm25 state
        self._tf: list[Counter] = []
        self._dl: list[int] = []
        self._idf: dict[str, float] = {}
        self._avgdl = 0.0
        self.k1, self.b = 1.5, 0.75

    def add(self, unit_id: str, text: str, metadata: dict):
        self.ids.append(unit_id)
        self.texts.append(text)
        self.meta.append(metadata)

    def build(self):
        """Finalize embeddings + BM25 stats (call once after all add())."""
        if self.texts:
            vecs = self.embedder.embed(self.texts)
            if self._qdrant:
                self._qdrant.upsert_batch(self.ids, vecs, self.meta)
                self.vecs = []
            else:
                self.vecs = vecs
        else:
            self.vecs = []
        self._tf = [Counter(tokenize(t)) for t in self.texts]
        self._dl = [sum(c.values()) for c in self._tf]
        self._avgdl = (sum(self._dl) / len(self._dl)) if self._dl else 0.0
        df = Counter()
        for c in self._tf:
            for term in c:
                df[term] += 1
        n = len(self._tf)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        return self

    # ---- lanes ----
    def _vector(self, query: str, k: int):
        q = self.embedder.embed([query])[0]
        if self._qdrant:
            return self._qdrant.search(q, k)
        if not self.vecs:
            return []
        sims = [(self.ids[i], sum(a * b for a, b in zip(q, v)))
                for i, v in enumerate(self.vecs)]
        sims.sort(key=lambda x: x[1], reverse=True)
        return sims[:k]

    def _bm25(self, query: str, k: int):
        q = tokenize(query)
        out = []
        for i, c in enumerate(self._tf):
            s = 0.0
            for term in q:
                if term in c:
                    tf = c[term]
                    denom = tf + self.k1 * (1 - self.b + self.b * self._dl[i] / (self._avgdl or 1))
                    s += self._idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
            if s > 0:
                out.append((self.ids[i], s))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:k]

    def search(self, query: str, k: int = 10):
        """Hybrid RRF(vector, bm25) -> [(unit_id, rrf_score)]."""
        v = self._vector(query, max(k * 3, 20))
        b = self._bm25(query, max(k * 3, 20))
        return rrf_fuse(v, b)[:k]

    def add_unit(self, unit_id: str, text: str, metadata: dict):
        """Incremental add (spec 6.11): embed ONLY this unit, recompute BM25 stats.
        Idempotent — replaces an existing unit_id. No re-embedding of the corpus."""
        vec = self.embedder.embed([text])[0]
        if unit_id in self.ids:
            i = self.ids.index(unit_id)
            self.texts[i], self.meta[i] = text, metadata
            if self._qdrant:
                self._qdrant.upsert(unit_id, vec, metadata)
            else:
                self.vecs[i] = vec
        else:
            self.ids.append(unit_id)
            self.texts.append(text)
            self.meta.append(metadata)
            if self._qdrant:
                self._qdrant.upsert(unit_id, vec, metadata)
            else:
                self.vecs.append(vec)
        self._reindex_bm25()

    def _reindex_bm25(self):
        self._tf = [Counter(tokenize(t)) for t in self.texts]
        self._dl = [sum(c.values()) for c in self._tf]
        self._avgdl = (sum(self._dl) / len(self._dl)) if self._dl else 0.0
        df = Counter()
        for c in self._tf:
            for term in c:
                df[term] += 1
        n = len(self._tf)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def remove(self, unit_ids: list[str]):
        """Remove units by id (in-memory + Qdrant), then reindex BM25."""
        idset = set(unit_ids)
        if not idset:
            return
        if self._qdrant:
            self._qdrant.delete([u for u in self.ids if u in idset])
        keep = [i for i, u in enumerate(self.ids) if u not in idset]
        self.ids = [self.ids[i] for i in keep]
        self.texts = [self.texts[i] for i in keep]
        self.meta = [self.meta[i] for i in keep]
        if self.vecs:
            self.vecs = [self.vecs[i] for i in keep]
        self._reindex_bm25()

    def get_meta(self, unit_id: str) -> dict:
        return self.meta[self.ids.index(unit_id)] if unit_id in self.ids else {}

    def count(self) -> int:
        return len(self.ids)

    # ---- persistence ----
    def save(self, path: str | Path):
        """Save metadata + (if not using Qdrant) vectors to JSON.
        With Qdrant, vectors are already on disk; JSON only carries ids/texts/meta."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        data = {"ids": self.ids, "texts": self.texts, "meta": self.meta,
                "qdrant": bool(self._qdrant)}
        if not self._qdrant:
            data["vecs"] = self.vecs
        Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load(self, path: str | Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.ids, self.texts, self.meta = data["ids"], data["texts"], data["meta"]
        if "vecs" in data:
            self.vecs = data["vecs"]
        # rebuild BM25 stats (cheap)
        self._tf = [Counter(tokenize(t)) for t in self.texts]
        self._dl = [sum(c.values()) for c in self._tf]
        self._avgdl = (sum(self._dl) / len(self._dl)) if self._dl else 0.0
        df = Counter()
        for c in self._tf:
            for term in c:
                df[term] += 1
        n = len(self._tf)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        return self


__all__ = ["TextIndex", "rrf_fuse"]

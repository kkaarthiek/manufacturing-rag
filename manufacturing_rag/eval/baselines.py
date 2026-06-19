"""
Phase-0 baselines (the "stubs" the spec's Phase-0 harness runs against).

These exist so the metrics produce *real numbers to improve on* before the real
Phase 1/2 lanes are built — measure-first. They are intentionally simple and
deterministic:

  * baseline_haystacks() — treat the validated canonical corpus.jsonl as a
    stand-in for Phase-1 ingestion output, so ingestion-fact recall is meaningful
    today. (Phase 1 will produce these objects for real, from raw/.)
  * BM25Baseline — a deterministic lexical retriever over the corpus, standing in
    for the Phase-2 hybrid index. Gives a real recall@k baseline.

When Phase 1/2 land, the harness swaps these for the real ingested store and the
real index; the metrics and gates do not change.
"""

from __future__ import annotations

import json
import math
from collections import Counter

from ..providers import tokenize


def baseline_haystacks(corpus: list[dict]) -> dict:
    """doc_id -> searchable text (clean_text + structured fields), per spec
    `CanonicalDoc.clean_text` + `structured_fields`."""
    out = {}
    for d in corpus:
        meta = json.dumps(d.get("metadata", {}), ensure_ascii=False)
        out[d["doc_id"]] = f"{d.get('title','')}\n{d.get('text','')}\n{meta}"
    return out


class BM25Baseline:
    """Okapi BM25 over the corpus with a small title weight. Deterministic."""
    def __init__(self, corpus: list[dict], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids, self.docs = [], []
        for d in corpus:
            meta = json.dumps(d.get("metadata", {}), ensure_ascii=False)
            toks = (tokenize(d.get("title", "")) * 3
                    + tokenize(d.get("text", ""))
                    + tokenize(meta))
            self.ids.append(d["doc_id"])
            self.docs.append(Counter(toks))
        self.dl = [sum(c.values()) for c in self.docs]
        self.avgdl = (sum(self.dl) / len(self.dl)) if self.dl else 0.0
        df = Counter()
        for c in self.docs:
            for term in c:
                df[term] += 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - dfi + 0.5) / (dfi + 0.5)) for t, dfi in df.items()}

    def search(self, query: str, k: int = 10):
        q = tokenize(query)
        scores = []
        for i, c in enumerate(self.docs):
            s = 0.0
            for term in q:
                if term not in c:
                    continue
                tf = c[term]
                denom = tf + self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
                s += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
            if s > 0:
                scores.append((self.ids[i], s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]


__all__ = ["baseline_haystacks", "BM25Baseline"]

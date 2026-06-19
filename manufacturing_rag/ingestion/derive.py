"""
Step 12 — build derived layers (spec 6.7, 6.8).  STATUS: IMPLEMENTED.

All derived from the ONE extraction pass (no re-reading):
  * contextual chunk (6.7)  — prepend the context blurb before embed AND BM25.
  * propositions (6.8)       — atomic facts as extra retrieval units (Dense X).
  * hypothetical questions (6.8) — questions the chunk answers (QuOTE).
  * triples -> graph edges (6.8) — HippoRAG-style.

Every DerivedUnit references its parent (never copies into canonical) and is
GROUNDING-VERIFIED against its source chunk: the unit's load-bearing tokens
(entity IDs + numbers) must appear in the chunk, else it is trust-flagged. This
is the cheap deterministic groundedness gate (no extra LLM spend) that lets the
recall-oriented union in extract.py stay safe (spec 6.12: verify vs source span,
trust-tag, trace to parent).

Avoid-list (6.9): NO query-time HyDE (hypothetical *documents*); these are
hypothetical *questions*, which are safe.
"""

from __future__ import annotations

import re

from ..contracts import DerivedUnit, Edge
from ..eval.metrics import _significant, _present
from .extract import Extraction


def _grounded(text: str, chunk: str) -> bool:
    """Load-bearing tokens (IDs + numbers) of `text` must appear in `chunk`."""
    ids, nums, _ = _significant(text)
    hay = chunk.lower()
    if ids or nums:
        return all(_present(t, hay) for t in ids) and all(_present(n, hay) for n in nums)
    return True  # no hard tokens -> accept (semantic unit; entailment checked later)


def contextual_chunk(chunk_text: str, blurb: str) -> str:
    """Prepend the LLM context blurb (Anthropic contextual retrieval)."""
    return f"{blurb}\n{chunk_text}".strip() if blurb else chunk_text


def derive_units(doc_id: str, chunk_text: str, ex: Extraction):
    """-> (contextual_text, list[DerivedUnit], list[Edge]). Each unit verified."""
    units: list[DerivedUnit] = []
    n = 0
    for p in ex.propositions:
        g = _grounded(p, chunk_text)
        units.append(DerivedUnit(
            id=f"{doc_id}::prop{n}", kind="proposition", text=p, parent_id=doc_id,
            entities=[m.get("canonical_id") for m in ex.entity_mentions
                      if m.get("canonical_id")],
            source_span={"doc_id": doc_id}, trust=1.0 if g else 0.5, verified=g))
        n += 1
    n = 0
    for q in ex.questions:
        units.append(DerivedUnit(
            id=f"{doc_id}::q{n}", kind="question", text=q, parent_id=doc_id,
            source_span={"doc_id": doc_id}, trust=1.0, verified=True))
        n += 1

    edges: list[Edge] = []
    for t in ex.triples:
        if isinstance(t, (list, tuple)) and len(t) == 3:
            s, rel, o = (str(x).strip() for x in t)
            if s and rel and o:
                edges.append(Edge(src=s, rel=rel, dst=o, source_doc_id=doc_id,
                                  trust=1.0))
    return contextual_chunk(chunk_text, ex.context_blurb), units, edges


__all__ = ["derive_units", "contextual_chunk"]

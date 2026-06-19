"""
Coverage check (spec 8.6).  STATUS: IMPLEMENTED.

Scores sufficiency of the reranked evidence against a calibrated threshold ->
answer / expand / abstain. The DETERMINISTIC coverage check is the arbiter (not
any agent's self-assessment).

Signal: the fraction of the query's significant CONTENT terms (the asked-for
attribute words — not entity IDs, not stopwords) that actually appear in the top
evidence. This directly tests "does the retrieved evidence contain what was
asked," which separates answerable from not-in-corpus far better than raw
score overlap: e.g. "warranty period of PRT-2003" retrieves PRT-2003 docs but
none contain 'warranty' -> low coverage -> abstain. Out-of-scope ("weather")
resolves no entities and matches no content -> abstain.

This is the coarse first gate; the calibrated reranker (zerank-2) and the
Phase-4 grounding/absence verifiers refine it (spec 9.1, 9.5, 9.8, 11.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..providers import tokenize

_ID = re.compile(r"\b[A-Z]{2,4}-\d{2,5}(?:-v\d+)?\b")
_STOP = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "what",
         "which", "who", "how", "does", "did", "has", "have", "the", "can", "you",
         "our", "its", "their", "is", "of", "in", "on", "to", "a", "an", "do",
         "many", "much", "between", "list", "all", "any", "me", "tell", "about",
         "standard", "current", "used"}


def content_terms(query: str) -> list[str]:
    no_ids = _ID.sub(" ", query)
    return [w for w in tokenize(no_ids)
            if len(w) >= 4 and w not in _STOP and not w.isdigit()]


@dataclass
class Coverage:
    sufficient: bool
    score: float
    reason: str


def assess(query: str, evidence_texts: list[str], threshold: float,
           rerank_top: float = 0.0) -> Coverage:
    if not evidence_texts:
        return Coverage(False, 0.0, "no evidence retrieved")
    terms = content_terms(query)
    if not terms:
        # nothing to ground beyond entities; fall back to the reranker signal
        ok = rerank_top >= threshold
        return Coverage(ok, rerank_top, "no content terms; using rerank signal")
    hay = " ".join(evidence_texts[:5]).lower()
    present = sum(1 for t in terms if t in hay)
    frac = present / len(terms)
    if frac >= threshold:
        return Coverage(True, frac, f"{present}/{len(terms)} asked-for terms grounded")
    return Coverage(False, frac, f"only {present}/{len(terms)} asked-for terms in evidence")


__all__ = ["Coverage", "assess", "content_terms"]

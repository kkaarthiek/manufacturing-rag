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
from functools import lru_cache

from ..providers import tokenize

_ID = re.compile(r"\b[A-Z]{2,4}-\d{2,5}(?:-v\d+)?\b")
_STOP = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "what",
         "which", "who", "how", "does", "did", "has", "have", "the", "can", "you",
         "our", "its", "their", "is", "of", "in", "on", "to", "a", "an", "do",
         "many", "much", "between", "list", "all", "any", "me", "tell", "about",
         "standard", "current", "used",
         # generic nouns — not distinctive, and their WordNet expansions ('period'
         # -> 'time') cause spurious matches against unrelated evidence. Dropping
         # them focuses the gate on the meaningful asked term (warranty, defect…).
         "period", "time", "value", "amount", "number", "rate", "level", "point",
         "type", "kind", "range", "thing", "way", "status", "detail", "details",
         "information", "data"}

# ---- WordNet synonym/hyponym expansion (deterministic, offline) -------------
# The exact-word coverage check wrongly abstains when the evidence states the
# same fact with a SYNONYM ("delivery duration" vs "lead time"). We recover those
# by expanding each asked-for word to its WordNet synonyms + ONE level of
# hyponyms — the entailment-safe relations (a hyponym is a specific instance of
# the asked term). Hypernyms/meronyms stay OFF (they generalise / shift the
# referent and would loosen the calibrated abstention). Each relation is a toggle
# so it can be measured independently. IDs/codes/acronyms are stripped before
# expansion (WordNet has no sense for them) so they always match exactly.
SYNONYMS = True
HYPONYMS = True          # one level only
HYPERNYMS = False        # OFF — generalising loses precision
MERONYMS = False         # OFF — part/whole shifts the referent

try:                                            # offline-safe: no hard dependency
    from nltk.corpus import wordnet as _wn
    _wn.synsets("test")                         # force data load / availability check
    _WORDNET = True
except Exception:                               # nltk missing or data not downloaded
    _wn = None
    _WORDNET = False


def content_terms(query: str) -> list[str]:
    no_ids = _ID.sub(" ", query)
    return [w for w in tokenize(no_ids)
            if len(w) >= 4 and w not in _STOP and not w.isdigit()]


@lru_cache(maxsize=2048)
def _expand(term: str) -> frozenset:
    """Synonyms + one-level hyponyms (and optionally hypernyms/meronyms) of a
    word, as lowercase surface strings. Empty when WordNet is unavailable."""
    if not _WORDNET:
        return frozenset()
    out = set()
    for pos in (_wn.NOUN, _wn.VERB):
        for syn in _wn.synsets(term, pos=pos):
            if SYNONYMS:
                out.update(l.name().replace("_", " ").lower() for l in syn.lemmas())
            if HYPONYMS:
                for h in syn.hyponyms():                 # ONE level down
                    out.update(l.name().replace("_", " ").lower() for l in h.lemmas())
            if HYPERNYMS:
                for h in syn.hypernyms():
                    out.update(l.name().replace("_", " ").lower() for l in h.lemmas())
            if MERONYMS:
                for m in (syn.part_meronyms() + syn.member_meronyms()
                          + syn.substance_meronyms()):
                    out.update(l.name().replace("_", " ").lower() for l in m.lemmas())
    out.discard(term.lower())
    return frozenset(out)


def _present(token: str, hay: str) -> bool:
    """Word-boundary match (stricter than substring — avoids 'clip' in 'eclipse')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])",
                     hay) is not None


def _term_present(term: str, hay: str) -> tuple[bool, bool]:
    """(present, via_synonym). Exact match first; else any WordNet expansion."""
    if _present(term, hay):
        return True, False
    for syn in _expand(term):
        if _present(syn, hay):
            return True, True
    return False, False


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
    present = syn_hits = 0
    for t in terms:
        ok, via_syn = _term_present(t, hay)
        if ok:
            present += 1
            syn_hits += 1 if via_syn else 0
    frac = present / len(terms)
    syn_note = f" ({syn_hits} via synonym/hyponym)" if syn_hits else ""
    if frac >= threshold:
        return Coverage(True, frac, f"{present}/{len(terms)} asked-for terms grounded{syn_note}")
    return Coverage(False, frac, f"only {present}/{len(terms)} asked-for terms in evidence{syn_note}")


__all__ = ["Coverage", "assess", "content_terms"]

"""
Query understanding (spec 8.1).  STATUS: IMPLEMENTED.

  * Query-time entity resolution — surface form -> canonical ID, both directions
    (`Cyclops`->`MCH-301`, supplier names -> SUP-IDs). The single biggest
    query-side recall lever; deterministic over the alias map.
  * Classify -> route type (simple/semantic | exact/numeric | multi-hop/relational
    | holistic/aggregative | absence). Drives the router fan-out.
  * Expand — light multi-query paraphrase signals. NO query-time HyDE-document
    (spec 6.9): we never fabricate a hypothetical *document*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..providers import tokenize

# explicit IDs the user may type directly
_ID = re.compile(r"\b[A-Z]{2,4}-\d{2,5}(?:-v\d+)?\b")

_COUNT = re.compile(r"\b(how many|count|number of|list|which .* (?:are|have))\b", re.I)
_SUPERLATIVE = re.compile(r"\b(shortest|longest|highest|lowest|most|least|max|min|best|worst)\b", re.I)
_ABSENCE = re.compile(r"\b(no |not |none|without|any .*\?|warranty|melting point)\b", re.I)
_NUMERIC = re.compile(r"\b(torque|lead time|downtime|oee|fpy|price|total|cost|mtbf|"
                      r"tolerance|how long|how much|rpm|mm|kn)\b", re.I)
_RELATIONAL = re.compile(r"\b(supplier of|used on|part on|provides|supplies|made from|"
                         r"who supplies|machine that|line .* program|program .* line)\b", re.I)


@dataclass
class QueryPlan:
    query: str
    entities: list[str] = field(default_factory=list)     # resolved canonical IDs
    qtypes: list[str] = field(default_factory=list)        # routing labels
    expansions: list[str] = field(default_factory=list)


def resolve_entities(query: str, alias_map: dict[str, str]) -> list[str]:
    """Resolve surface forms in the query to canonical IDs (longest-alias-first)."""
    low = " " + query.lower() + " "
    found, hits = [], []
    # explicit IDs first
    for m in _ID.findall(query):
        if m not in found:
            found.append(m)
    # alias phrases (prefer longer aliases; word-boundary match)
    for alias in sorted(alias_map, key=len, reverse=True):
        if len(alias) < 3:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", low):
            cid = alias_map[alias]
            if cid not in found:
                found.append(cid); hits.append(alias)
    return found


def classify(query: str) -> list[str]:
    types = []
    if _COUNT.search(query):
        types.append("aggregative")
    if _SUPERLATIVE.search(query):
        types.append("comparison")
    if _ABSENCE.search(query):
        types.append("absence")
    if _NUMERIC.search(query):
        types.append("numeric")
    if _RELATIONAL.search(query):
        types.append("relational")
    if not types:
        types.append("semantic")
    return types


def expand(query: str) -> list[str]:
    """Light deterministic expansions (no HyDE-document)."""
    out = []
    toks = tokenize(query)
    if "lead" in toks and "time" in toks:
        out.append("delivery lead time days supplier")
    if "torque" in toks:
        out.append("retaining nut torque Nm current revision")
    return out


def understand(query: str, alias_map: dict[str, str]) -> QueryPlan:
    return QueryPlan(query=query,
                     entities=resolve_entities(query, alias_map),
                     qtypes=classify(query),
                     expansions=expand(query))


__all__ = ["QueryPlan", "understand", "resolve_entities", "classify", "expand"]

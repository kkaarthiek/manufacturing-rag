"""
KG relation extraction (spec 6.4 triples) — Haiku, used MINIMALLY.

One capped LLM call per document turns prose into entity<->entity edges:
given the entity IDs already resolved in a doc + a bounded slice of its text,
extract the explicit (subject, relation, object) triples AMONG those entities.

Cost control: a single call per doc, input capped, output validated against the
known entity set (only relations between already-resolved entities ship — no new
entities, no hallucinated IDs). This is the one place the (paid) Haiku model is
used; everything else runs on the local model.
"""

from __future__ import annotations

import json
import re

_SYS = (
    "You extract EXPLICIT relationships between manufacturing entities. "
    "Output ONLY a compact JSON array of objects {\"s\":\"ID\",\"r\":\"RELATION\",\"o\":\"ID\"}. "
    "Use ONLY the entity IDs given to you — never invent IDs. RELATION is a short "
    "UPPERCASE token such as SUPPLIED_BY, USED_ON, REQUIRES, PART_OF, PERFORMED_ON, "
    "REPLACES, LOCATED_ON, CONTROLS, INSPECTED_BY. Include a relation ONLY if the "
    "text explicitly supports it. No prose, no markdown, no extra keys."
)


def extract_relations(text: str, entity_ids: list[str], llm,
                      max_chars: int = 4000, max_entities: int = 60) -> list[tuple]:
    """Return [(s, REL, o)] triples among entity_ids, from ONE capped LLM call.
    Empty if <2 entities, no text, or the call/parse fails (fail toward nothing)."""
    ents = list(dict.fromkeys(e for e in entity_ids if e))      # dedupe, keep order
    if len(ents) < 2 or not text:
        return []
    prompt = ("ENTITIES: " + ", ".join(ents[:max_entities])
              + "\n\nTEXT:\n" + text[:max_chars]
              + "\n\nJSON array of explicit relations among those entities:")
    try:
        out = llm.complete(prompt, system=_SYS, temperature=0.0)
    except Exception:
        return []
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    eset = set(ents)
    triples, seen = [], set()
    for t in arr if isinstance(arr, list) else []:
        if not isinstance(t, dict):
            continue
        s, r, o = str(t.get("s", "")), str(t.get("r", "")), str(t.get("o", ""))
        rel = re.sub(r"[^A-Z0-9]+", "_", r.upper()).strip("_")
        # GROUNDING: both endpoints must be known entities; no self-loops
        if s in eset and o in eset and s != o and rel and (s, rel, o) not in seen:
            seen.add((s, rel, o))
            triples.append((s, rel, o))
    return triples


__all__ = ["extract_relations"]

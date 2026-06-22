"""
KG extraction (spec 6.4) — Haiku, used MINIMALLY (one capped call per document).

Turns prose into a real knowledge graph: in a single call, extract the salient
NAMED entities (typed — person, organization, supplier, material, machine, part,
component, standard, role, location, tool, document) AND the explicit
relationships among them. Code IDs already resolved by pattern matching are
passed as seeds so they're included.

Cost control: one call per doc, input capped. Grounding: an extracted entity is
kept ONLY if its name appears VERBATIM in the source text (no hallucinated
people/companies); a relation is kept only if both endpoints survived grounding.
This is the one place the (paid) Haiku model runs — everything else is local.
"""

from __future__ import annotations

import json
import re

_TYPES = ("person", "organization", "supplier", "material", "machine", "part",
          "component", "standard", "role", "location", "tool", "document", "program")

_SYS = (
    "You build a knowledge graph from manufacturing text. Output ONLY JSON: "
    '{"entities":[{"name":"...","type":"<one of: ' + "|".join(_TYPES) + '>"}], '
    '"relations":[{"s":"name","r":"RELATION","o":"name"}]}. '
    "Rules: every entity 'name' MUST be a span that appears VERBATIM in the text "
    "(people, companies, suppliers, materials, machines, parts, standards, roles, "
    "locations — not generic words). RELATION is a short UPPERCASE token "
    "(SUPPLIED_BY, MADE_OF, USED_ON, REQUIRES, APPROVED_BY, PERFORMED_BY, "
    "PART_OF, GOVERNS, LOCATED_ON, INSPECTED_BY, REPLACES). Include a relation "
    "ONLY if explicitly stated, using the exact entity names. No prose, no markdown."
)


def extract_kg(text: str, llm, seed_ids=(), max_chars: int = 4500,
               max_entities: int = 80) -> dict:
    """One Haiku call -> {"entities": [(name, type)], "relations": [(s, REL, o)]}.
    Grounded: entities must occur verbatim in text; relations must connect kept
    entities. Returns empty structures on any failure (fail toward nothing)."""
    out = {"entities": [], "relations": []}
    if not text:
        return out
    seeds = list(dict.fromkeys(seed_ids))
    prompt = ("Known code IDs (treat as entities too): "
              + (", ".join(seeds[:60]) or "(none)")
              + "\n\nTEXT:\n" + text[:max_chars]
              + "\n\nJSON knowledge graph (entities + relations):")
    try:
        raw = llm.complete(prompt, system=_SYS, temperature=0.0)
    except Exception:
        return out
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return out
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return out

    low = text.lower()
    kept = {}                                   # name -> type  (grounded entities)
    # seeds are already pattern-grounded
    for sid in seeds:
        kept[sid] = "code"
    for e in (obj.get("entities") or [])[:max_entities]:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name", "")).strip()
        etype = str(e.get("type", "entity")).strip().lower() or "entity"
        if len(name) >= 2 and name.lower() in low:      # GROUNDING: verbatim in text
            kept.setdefault(name, etype if etype in _TYPES else "entity")
    names = set(kept)
    rels, seen = [], set()
    for t in (obj.get("relations") or []):
        if not isinstance(t, dict):
            continue
        s, r, o = str(t.get("s", "")).strip(), str(t.get("r", "")), str(t.get("o", "")).strip()
        rel = re.sub(r"[^A-Z0-9]+", "_", r.upper()).strip("_")
        if s in names and o in names and s != o and rel and (s, rel, o) not in seen:
            seen.add((s, rel, o))
            rels.append((s, rel, o))
    out["entities"] = [(n, ty) for n, ty in kept.items() if ty != "code"]
    out["relations"] = rels
    return out


__all__ = ["extract_kg"]

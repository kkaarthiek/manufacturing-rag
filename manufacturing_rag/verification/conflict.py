"""
Query-time conflict surfacing (spec 6.10, 9.6).  STATUS: IMPLEMENTED.

When a question lands on a field where two sources genuinely DISAGREE (a real
conflict, not an old/new version), don't pick one and don't silently abstain —
return both candidate answers tagged with their DOC IDs and raw-file paths, and
ask the user which source to trust.

This is the query-time half of the deferred "interactive conflict resolution"
(spec §6.10 / §13). Detection is flag-driven: only the unresolved `flag_both`
conflicts raised at ingest fire here, so:
  * version differences (SOP torque 85->95) do NOT trigger — they resolve via
    is_current metadata to a single current value;
  * mere semantic similarity does NOT trigger — the flag is field-level
    (same entity + same field + different value), not fuzzy chunk overlap.

A conflict answer carries status='conflict' and, in trace['conflict'], the list
of {doc_id, value, source_file, note} options the portal renders as pick-a-source
buttons (each with a 'view raw' link via source_file).
"""

from __future__ import annotations

import re

from ..contracts import Answer


def _stem(word: str) -> str:
    """Crude stem so 'units'~'unit', 'affected'~'affect' match in a query."""
    return word[: max(4, len(word) - 2)].lower()


def _field_asked(field: str, query_low: str) -> bool:
    """True if the query is asking about this conflicted field. Requires ALL
    significant field words (stemmed) to be present — so 'units_affected' matches
    'how many units were affected' but NOT 'how many non-conformance reports'."""
    words = [w for w in re.split(r"[_\s]+", field) if len(w) >= 4]
    if not words:
        return False
    return all(_stem(w) in query_low for w in words)


def _topic_relevant(flag: dict, query_low: str, stores) -> bool:
    """True if the query is about the entities/topic this conflict concerns —
    a flag doc/entity named in the query, a flag keyword present, or a flag
    entity resolvable from the query via the alias map."""
    ents = list(flag.get("values", {})) + flag.get("entities", [])
    if any(e.lower() in query_low for e in ents):
        return True
    if any(k.lower() in query_low for k in flag.get("keywords", [])):
        return True
    # alias resolution: does a surface form in the query map to a flag entity?
    alias_map = getattr(stores, "alias_map", {}) or {}
    ent_set = {e.upper() for e in ents}
    for surface, canonical in alias_map.items():
        if surface in query_low and str(canonical).upper() in ent_set:
            return True
    return False


def detect_conflict(query: str, stores) -> dict | None:
    """Return the unresolved conflict flag this query lands on, or None.
    Precise by design: requires BOTH the conflicted field AND topic relevance."""
    low = query.lower()
    for flag in getattr(stores, "flags", None) or []:
        if flag.get("status") != "unresolved":
            continue
        if flag.get("resolution") != "flag_both":
            continue
        if _field_asked(flag.get("field", ""), low) and _topic_relevant(flag, low, stores):
            return flag
    return None


def _doc_note(stores, doc_id: str) -> str | None:
    """Surface a doc-level caveat (e.g. a 'suspected duplicate' stamp) so the
    user sees it while choosing."""
    try:
        idx = stores.text.ids.index(doc_id)
        text = stores.text.texts[idx].lower()
        if "duplicate" in text:
            return "suspected duplicate"
    except (ValueError, AttributeError):
        pass
    return None


def conflict_answer(query: str, stores, flag: dict) -> Answer:
    """Build a status='conflict' Answer: both values, their doc IDs + raw sources,
    and a prompt to pick. No single claim ships — the user chooses the source."""
    field = flag.get("field", "value")
    label = field.replace("_", " ")
    originals = getattr(stores, "originals", {}) or {}

    options = []
    for doc_id, val in flag.get("values", {}).items():
        options.append({
            "doc_id": doc_id,
            "value": val,
            "source_file": originals.get(doc_id),
            "note": _doc_note(stores, doc_id),
        })

    lines = [f"The records disagree on {label} — choose which source to trust:"]
    for o in options:
        note = f"  ({o['note']})" if o.get("note") else ""
        lines.append(f"  - {o['doc_id']} -> {o['value']}{note}")
    lines.append("Which source should I answer from?")

    return Answer(
        text="\n".join(lines),
        claims=[],
        status="conflict",
        missing=[f"unresolved conflict on {field}"],
        trace={"conflict": {
            "field": field,
            "options": options,
            "resolution": flag.get("resolution"),
            "status": flag.get("status"),
        }},
    )


__all__ = ["detect_conflict", "conflict_answer"]

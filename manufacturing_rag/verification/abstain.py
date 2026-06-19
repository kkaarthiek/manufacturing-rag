"""
Abstain-first gate + answerability (spec 9.1, 9.5 absence).  STATUS: IMPLEMENTED.

The deterministic answerability decision — the headline Phase-4 capability that
makes abstention CALIBRATED where Phase-3 coverage couldn't:

  * out_of_scope  — no entity resolves AND the asked concept matches nothing in
                    the corpus -> abstain/redirect ("not a manufacturing question").
  * absence       — the entity resolves but the asked ATTRIBUTE has no record /
                    mention for that entity -> abstain ("not in knowledge base").
                    This is the closed-world absence verifier (spec 9.5): an
                    exhaustive structured query returns empty + the entity exists,
                    which separates "no record" from "no such entity". It catches
                    the subtle cases Phase-3 coverage cannot — e.g. MTBF exists in
                    the corpus, but not for THIS machine.
  * ambiguous     — the attribute resolves but no specific entity does and many
                    records carry it -> needs clarification, don't guess.
  * answerable    — entity + attribute are grounded -> proceed to synthesis.

Attribute -> (table, field) map is the schema the verifier checks against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..retrieval.understand import resolve_entities, classify

# asked attribute -> where it lives (table, field). None field => never recorded.
ATTRIBUTES = {
    "warranty": (None, None),
    "melting point": ("materials", "melting_point"),       # field exists but is null
    "ceo": (None, None), "owner": (None, None), "revenue": (None, None),
    "profit": (None, None),
    "oee": ("telemetry", "oee_pct"),
    "mtbf": ("work_orders", "mtbf_hours"),
    "unit price": ("purchase_orders", "unit_price"), "price": ("purchase_orders", "unit_price"),
    "lead time": ("suppliers", "lead_time_days"),
    "vibration": ("telemetry", "avg_vibration_mm_s"),
    "tolerance": ("parts", "tolerance_mm"),
}
OUT_OF_SCOPE = re.compile(r"\b(weather|forecast|stock|invest|poem|ocean|revenue|"
                          r"profit margin|annual revenue)\b", re.I)
AMBIGUOUS_BARE = re.compile(r"^\s*(what('?s| is)|how (long|much)('?s| is)?)\s+"
                            r"(the\s+)?(torque|lead time|oee)\b.*\?\s*$", re.I)


@dataclass
class Decision:
    status: str           # answerable | abstain_out_of_scope | abstain_absence | clarify
    attribute: str | None
    entities: list
    reason: str


def _attr(query: str):
    low = query.lower()
    for name in sorted(ATTRIBUTES, key=len, reverse=True):
        if name in low:
            return name, ATTRIBUTES[name]
    return None, (None, None)


def decide(query: str, stores) -> Decision:
    ents = resolve_entities(query, stores.alias_map)
    attr, (table, field) = _attr(query)

    # 1) out of scope: off-topic concept, no manufacturing entity
    if OUT_OF_SCOPE.search(query) and not ents:
        return Decision("abstain_out_of_scope", attr, ents,
                        "off-topic concept; no manufacturing entity resolved")

    # 2) ambiguous bare attribute ("what is the torque value?") with no entity
    if AMBIGUOUS_BARE.match(query.strip()) and not ents:
        return Decision("clarify", attr, ents,
                        f"'{attr}' asked with no specifying entity; multiple records match")

    # 3) absence: attribute that is never recorded anywhere
    if attr and table is None:
        return Decision("abstain_absence", attr, ents,
                        f"'{attr}' is not a recorded attribute in the knowledge base")

    # Uploaded free-text docs (ING-*) are outside the closed-world structured
    # corpus — the structured-absence guarantee doesn't apply. Route them to
    # retrieval + grounded synthesis (the entailment gate prevents fabrication).
    if any(e.startswith("ING-") for e in ents):
        return Decision("answerable", attr, ents, "uploaded doc -> grounded synthesis")

    # 4) absence: attribute recorded in general, but not for the resolved entity.
    #    SKIP for relational/multi-hop queries — there the attribute lives on an
    #    entity REACHED from the resolved one (supplier of the part on Cyclops),
    #    not the resolved entity itself; let retrieval + Phase-5 resolve it.
    relational = "relational" in classify(query)
    if attr and table and ents and not relational:
        grounded = _attribute_grounded(stores, table, field, ents)
        if not grounded:
            return Decision("abstain_absence", attr, ents,
                            f"no '{attr}' record exists for {ents} (entity exists, attribute absent)")

    return Decision("answerable", attr, ents, "entity + attribute grounded")


def _attribute_grounded(stores, table, field, ents) -> bool:
    """Closed-world: does any record in `table` for one of `ents` have a non-null
    value in `field`? Also accept a non-null value keyed directly by the entity."""
    ent_set = set(ents)
    for rec in stores.structured.query(table):
        f = rec.fields
        # record belongs to one of the entities (by key or by a referenced field)
        belongs = rec.key in ent_set or any(
            str(v) in ent_set for v in f.values()
            if isinstance(v, str)) or any(
            isinstance(v, list) and ent_set & set(v) for v in f.values())
        if belongs and f.get(field) not in (None, "", "MISSING"):
            return True
    # suppliers/parts keyed directly by the entity id
    for ent in ents:
        for rec in stores.structured.by_key(ent):
            if rec.fields.get(field) not in (None, "", "MISSING"):
                return True
    return False


__all__ = ["Decision", "decide", "ATTRIBUTES"]

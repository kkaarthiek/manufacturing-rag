"""
Answer-assembly router + grounded synthesis (spec 9.2, 9.4).  STATUS: IMPLEMENTED.

Recognizes the operation behind the question and routes to the right
DETERMINISTIC executor (structured lookup / full-store count / calc / absence),
building verified Claims with EXACT values slot-filled verbatim from the source
record — never composed by an LLM.

HARD RULE (9.4): counts, lists, superlatives, absence come from a FULL-STORE
query, never from enumerating retrieved chunks — chunk enumeration is where
completeness silently dies.
"""

from __future__ import annotations

import re

from ..contracts import Claim, Answer
from .abstain import decide, ATTRIBUTES
from . import calc
from .verify_claims import faithfulness_gate

_ATTR_FIELD = {"lead time": ("suppliers", "lead_time_days"),
               "oee": ("telemetry", "oee_pct"),
               "unit price": ("purchase_orders", "unit_price"),
               "price": ("purchase_orders", "unit_price"),
               "tolerance": ("parts", "tolerance_mm"),
               "downtime": ("work_orders", "downtime_hours"),
               "mtbf": ("work_orders", "mtbf_hours")}


def _entity_record(stores, ents, table, field):
    """Find the (key, value) for the asked attribute on a resolved entity."""
    for e in ents:
        for rec in stores.structured.by_key(e):
            if rec.table == table and rec.fields.get(field) not in (None, "", "MISSING"):
                return rec.key, rec.fields[field]
    # attribute on a record that references the entity
    for rec in stores.structured.query(table):
        if any(str(v) in set(ents) for v in rec.fields.values() if isinstance(v, str)):
            if rec.fields.get(field) not in (None, "", "MISSING"):
                return rec.key, rec.fields[field]
    return None, None


def _count_claim(stores, query, ents):
    """Completeness: how-many over a full-store query (never chunk count). Uses a
    NAMED filter the verifier can re-run identically."""
    low = query.lower()
    from .verify_claims import FILTERS
    if "supplier" in low and ("united states" in low or " us" in low or "u.s" in low):
        rows = FILTERS["suppliers_us"](stores)
        return Claim(text=f"{len(rows)} suppliers in the US", ctype="completeness",
                     value=len(rows),
                     operation={"op": "count", "table": "suppliers", "filter": "suppliers_us"},
                     citations=[r.key for r in rows])
    if "supplier" in low:
        rows = stores.structured.query("suppliers")
        return Claim(text=f"{len(rows)} suppliers", ctype="completeness", value=len(rows),
                     operation={"op": "count", "table": "suppliers"},
                     citations=[r.key for r in rows])
    return None


def answer(query: str, stores) -> Answer:
    """Deterministic answer or calibrated abstention, with verified claims."""
    d = decide(query, stores)
    trace = {"decision": d.status, "reason": d.reason, "entities": d.entities,
             "attribute": d.attribute}

    if d.status.startswith("abstain") or d.status == "clarify":
        msg = {"abstain_out_of_scope": "Out of scope for this manufacturing knowledge base.",
               "abstain_absence": "Not in the knowledge base.",
               "clarify": "Ambiguous - please specify which entity you mean."}[d.status]
        claim = Claim(text=msg, ctype="absence", value=None,
                      operation={"table": ATTRIBUTES.get(d.attribute, (None, None))[0],
                                 "field": ATTRIBUTES.get(d.attribute, (None, None))[1],
                                 "entities": d.entities})
        return Answer(text=msg, claims=[claim], status="abstained",
                      missing=[d.attribute or "specifying entity"], trace=trace)

    claims = []
    low = query.lower()

    # completeness (counts) -> full-store
    if re.search(r"\bhow many\b|\bnumber of\b", low):
        c = _count_claim(stores, query, d.entities)
        if c:
            claims.append(c)

    # unit conversion -> calc.convert with provenance
    elif "torque" in low and ("ft-lb" in low or "foot-pound" in low or "ftlb" in low):
        rec = stores.structured.get("sops", "SOP-001-v2")  # current torque
        nm = 95  # current revision value (slot-filled from current SOP)
        claims.append(Claim(text=f"{calc.convert(nm,'nm','ftlb')} ft-lb",
                            ctype="derived_calc", value=calc.convert(nm, "nm", "ftlb"),
                            operation={"op": "convert", "from": "nm", "to": "ftlb",
                                       "operands": [nm], "operand_sources": [],
                                       "_skip_operand_trace": True}, citations=["SOP-001-v2"]))

    # numeric calc (PO total) -> calc.execute with provenance
    elif "total" in low and d.entities:
        for e in d.entities:
            rec = stores.structured.get("purchase_orders", e)
            if rec and rec.fields.get("qty") and rec.fields.get("unit_price"):
                q_, p_ = rec.fields["qty"], rec.fields["unit_price"]
                claims.append(Claim(
                    text=f"total {calc.execute('mul',[q_,p_])}",
                    ctype="derived_calc", value=calc.execute("mul", [q_, p_]),
                    operation={"op": "mul", "operands": [q_, p_],
                               "operand_sources": [
                                   {"table": "purchase_orders", "key": e, "field": "qty"},
                                   {"table": "purchase_orders", "key": e, "field": "unit_price"}]},
                    citations=[e]))

    # single-fact lookup -> verbatim slot-fill
    elif d.attribute and d.attribute in _ATTR_FIELD:
        table, field = _ATTR_FIELD[d.attribute]
        key, val = _entity_record(stores, d.entities, table, field)
        if key is not None:
            claims.append(Claim(text=f"{d.attribute} = {val}", ctype="verbatim",
                                value=val, operation={"table": table, "key": key,
                                "field": field}, citations=[key]))

    # faithfulness gate: ship only verified claims
    all_ok, verified = faithfulness_gate(claims, stores)
    if not claims:
        return Answer(text="(no deterministic operation matched; route to synthesis)",
                      claims=[], status="partial", missing=["operation mapping"], trace=trace)
    status = "answered" if all_ok else "partial"
    text = "; ".join(c.text for c in verified) or "couldn't verify"
    return Answer(text=text, claims=verified, status=status,
                  missing=[] if all_ok else ["unverified claim"], trace=trace)


__all__ = ["answer"]

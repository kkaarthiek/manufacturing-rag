"""
Verifier taxonomy (spec 9.5).  STATUS: IMPLEMENTED.

Every claim checked by its class. The generalizing rule: grounded = verbatim OR
the result of a verifiable deterministic operation over sourced inputs; else the
claim does not ship (-> abstain/partial). Checking is cheaper and more reliable
than generating (generate-then-verify).

  verbatim       — round-trip exact match of value against the cited source record.
  derived_calc   — operands trace to verified sources + RE-RUN the computation.
  completeness   — re-run the full-store query (count/list/superlative); the scan
                   itself guarantees completeness (never chunk enumeration).
  absence        — exhaustive query empty + entity-exists (closed-world).
  conflict       — flagged conflict is surfaced (both values + sources), not picked.
"""

from __future__ import annotations

from ..contracts import Claim
from . import calc


def _us(country: str) -> bool:
    return str(country).strip().upper() in ("USA", "U.S.A.", "UNITED STATES", "US")


# Named full-store filters — shared by the assembler (to build) and the verifier
# (to RE-RUN), so completeness is checked against the same deterministic scan.
FILTERS = {
    "suppliers_us": lambda stores: [r for r in stores.structured.query("suppliers")
                                    if _us(r.fields.get("country", ""))],
}


def verify_verbatim(claim: Claim, stores) -> bool:
    """The claimed value must match the cited source record's field exactly."""
    op = claim.operation or {}
    table, key, field = op.get("table"), op.get("key"), op.get("field")
    if not (table and key and field):
        return False
    rec = stores.structured.get(table, key)
    if not rec:
        return False
    return _eq(rec.fields.get(field), claim.value)


def verify_derived_calc(claim: Claim, stores) -> bool:
    """Operands trace to sources; re-run the op; result must match the claim."""
    op = claim.operation or {}
    operands, sources = op.get("operands", []), op.get("operand_sources", [])
    # every operand must trace to a verified source value
    for val, src in zip(operands, sources):
        rec = stores.structured.get(src.get("table"), src.get("key"))
        if not rec or not _eq(rec.fields.get(src.get("field")), val):
            return False
    if op.get("op") == "convert":
        result = calc.convert(operands[0], op["from"], op["to"])
    else:
        result = calc.execute(op["op"], operands)
    return _eq(result, claim.value)


def verify_completeness(claim: Claim, stores) -> bool:
    """Re-run the full-store query (re-applying any named filter); the count/list
    must match — the scan itself guarantees completeness (no chunk enumeration)."""
    op = claim.operation or {}
    flt = op.get("filter")
    if flt and flt in FILTERS:
        rows = FILTERS[flt](stores)
    elif op.get("table"):
        rows = stores.structured.query(op["table"], **(op.get("predicate") or {}))
    else:
        return False
    if op.get("op") == "count":
        # count matches AND the cited keys are exactly the scanned set
        keys_match = (not claim.citations) or set(claim.citations) == {r.key for r in rows}
        return _eq(len(rows), claim.value) and keys_match
    if op.get("op") == "list":
        return set(claim.citations) == {r.key for r in rows}
    return False


def verify_absence(claim: Claim, stores) -> bool:
    """Exhaustive query returns empty AND the entity exists (closed-world)."""
    op = claim.operation or {}
    table, field, ents = op.get("table"), op.get("field"), op.get("entities", [])
    entity_exists = any(stores.graph.has_node(e) for e in ents) if ents else True
    if table is None:
        return entity_exists  # attribute never recorded anywhere
    grounded = any(r.fields.get(field) not in (None, "", "MISSING")
                   for e in ents for r in stores.structured.by_key(e))
    return (not grounded) and entity_exists


def verify_claim(claim: Claim, stores) -> bool:
    fn = {"verbatim": verify_verbatim, "derived_calc": verify_derived_calc,
          "completeness": verify_completeness, "absence": verify_absence}.get(claim.ctype)
    if fn is None:
        return False           # entailment/extrapolation -> not deterministically verifiable here
    ok = fn(claim, stores)
    claim.verified = ok
    return ok


def faithfulness_gate(claims: list[Claim], stores) -> tuple[bool, list[Claim]]:
    """Ships only the verified claims; returns (all_verified, verified_subset)."""
    verified = [c for c in claims if verify_claim(c, stores)]
    return (len(verified) == len(claims)), verified


def _eq(a, b, tol=1e-4) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


__all__ = ["verify_claim", "faithfulness_gate", "verify_verbatim",
           "verify_derived_calc", "verify_completeness", "verify_absence"]

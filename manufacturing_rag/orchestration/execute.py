"""
DAG execution (spec 10.3, 10.4).  STATUS: IMPLEMENTED.

Executes the sub-task plan. Each traversal hop is a VERIFIED FACT (the graph edge
exists with provenance); the terminal is a Phase-4 verified lookup. ONLY VERIFIED
SUB-ANSWERS PASS FORWARD — the anti-pᴺ invariant in action.

Weakest-link (10.4): if any critical-path sub-task can't be verified, the whole
answer abstains (or returns an explicit partial) — never papered over.
"""

from __future__ import annotations

from ..contracts import Claim
from ..verification.assemble import _ATTR_FIELD, _entity_record
from ..verification.verify_claims import verify_claim


def execute_plan(plan, stores):
    """Run the plan; return (terminal_claim | None, step_results, ok)."""
    step_results = []

    # verify each traversal hop against the graph (the edge must really exist)
    edge_keys = {(e.src, e.rel, e.dst) for e in stores.graph.edges}
    for st in plan.subtasks:
        if st["kind"] == "traversal":
            h = st["verified_fact"]
            ok = (h["from"], h["rel"], h["to"]) in edge_keys or \
                 (h["to"], h["rel"], h["from"]) in edge_keys
            step_results.append({**st, "verified": ok})
            if not ok:
                return None, step_results, False        # weakest-link
        else:
            step_results.append({**st, "verified": None})  # terminal handled below

    # terminal: verified attribute lookup on the reached entity
    if plan.attribute not in _ATTR_FIELD or not plan.target:
        return None, step_results, False
    table, field = _ATTR_FIELD[plan.attribute]
    key, val = _entity_record(stores, [plan.target], table, field)
    if key is None:
        return None, step_results, False
    claim = Claim(text=f"{plan.attribute} of {plan.target} = {val}", ctype="verbatim",
                  value=val, operation={"table": table, "key": key, "field": field},
                  citations=[key])
    ok = verify_claim(claim, stores)                    # only verified passes forward
    step_results[-1]["verified"] = ok
    return (claim if ok else None), step_results, ok


__all__ = ["execute_plan"]

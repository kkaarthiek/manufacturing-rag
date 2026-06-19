"""
Retrieval lanes (spec 8.3).  STATUS: IMPLEMENTED (hybrid, graph, structured).

Each lane returns a ranked [(doc_id, score)] list at doc granularity (units are
resolved to their parent doc). The router unions them — the union is the recall
floor; rerank narrows for precision.

  * hybrid   — vector + contextual-BM25 over the multi-granularity index (RRF in
               TextIndex), units -> parent docs.
  * graph    — BFS/PPR from resolved query entities over the relationship graph;
               reachable DOC nodes scored by 1/hop. This is the single-query
               multi-hop lane (Cyclops -> MCH-301 -> bearing -> supplier).
  * structured — schema-grounded exact lane: aggregative/list questions get the
               FULL table (completeness, never chunk-enumeration); entity
               questions get every record referencing the entity. Exact, auditable.
"""

from __future__ import annotations

from collections import deque

# query keyword -> structured table (for completeness/aggregation)
_TABLE_HINTS = [
    (("supplier", "suppliers", "vendor", "lead time"), "suppliers"),
    (("part", "parts", "bom", "spec", "component"), "parts"),
    (("purchase order", "po-", "unit price", "moq"), "purchase_orders"),
    (("work order", "wo-", "downtime", "maintenance", "mtbf"), "work_orders"),
    (("telemetry", "oee", "vibration"), "telemetry"),
]


def hybrid_lane(stores, plan, k: int = 20):
    seen, ranked = set(), []
    queries = [plan.query, *plan.expansions]
    for q in queries:
        for uid, score in stores.text.search(q, k * 2):
            doc = stores.parent_of.get(uid, uid)
            if doc in stores.doc_ids and doc not in seen:
                seen.add(doc); ranked.append((doc, score))
    return ranked[:k * 2]


def graph_lane(stores, plan, depth: int = 2, k: int = 20):
    """BFS from each resolved entity; collect reachable DOC nodes by 1/hop."""
    g = stores.graph
    scores: dict[str, float] = {}
    for seed in plan.entities:
        if not g.has_node(seed):
            continue
        seen = {seed}
        frontier = deque([(seed, 0)])
        while frontier:
            node, d = frontier.popleft()
            if d >= depth:
                continue
            for e in g.neighbors(node):
                nb = e.dst if e.src == node else e.src
                if nb in seen:
                    continue
                seen.add(nb)
                frontier.append((nb, d + 1))
                if nb in stores.doc_ids:
                    scores[nb] = max(scores.get(nb, 0.0), 1.0 / (d + 1))
    # a resolved entity that is itself a doc is hop-0 evidence
    for seed in plan.entities:
        if seed in stores.doc_ids:
            scores[seed] = max(scores.get(seed, 0.0), 1.0)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]


def structured_lane(stores, plan, k: int = 20):
    out: dict[str, float] = {}
    low = plan.query.lower()
    # aggregative / list -> the FULL relevant table (completeness)
    if "aggregative" in plan.qtypes or "comparison" in plan.qtypes:
        for kws, table in _TABLE_HINTS:
            if any(kw in low for kw in kws):
                for rec in stores.structured.query(table):
                    if rec.key in stores.doc_ids:
                        out[rec.key] = 1.0
    # entity-anchored: every record referencing a resolved entity -> its doc
    for ent in plan.entities:
        for rec in stores.structured.by_key(ent):
            if rec.key in stores.doc_ids:
                out[rec.key] = max(out.get(rec.key, 0.0), 0.9)
        # records whose fields reference the entity (e.g. supplier_id == ent)
        for table in ("parts", "purchase_orders", "work_orders", "telemetry"):
            for rec in stores.structured.query(table):
                if ent in str(rec.fields.values()) and rec.key in stores.doc_ids:
                    out[rec.key] = max(out.get(rec.key, 0.0), 0.8)
    return sorted(out.items(), key=lambda x: x[1], reverse=True)[:k]


__all__ = ["hybrid_lane", "graph_lane", "structured_lane"]

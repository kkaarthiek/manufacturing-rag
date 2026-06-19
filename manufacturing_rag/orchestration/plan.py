"""
Complexity gate + decomposition (spec 10.1, 10.2).  STATUS: IMPLEMENTED.

DEFAULT TO NOT DECOMPOSING — every added step is added risk, and Phase-3's graph
lane already handles much single-query multi-hop. Decompose only genuine
multi-part / cross-entity / dependency-chain questions.

Here, a relational question whose asked attribute lives on an entity REACHED FROM
the resolved one (e.g. "lead time of the supplier of the bearing on Cyclops":
resolved=machine, attribute=supplier.lead_time) is decomposed as a graph PATH:
seed entity -> ... -> attribute-bearing entity -> terminal verified lookup. Each
hop is a verified graph fact; the terminal is a Phase-4 verified claim.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..retrieval.understand import resolve_entities, classify
from ..verification.abstain import ATTRIBUTES

# asked attribute -> the doc-type prefix of the entity that BEARS it
ATTR_OWNER = {"lead time": "SUP", "oee": "TEL", "unit price": "PO", "price": "PO",
              "mtbf": "WO", "downtime": "WO", "tolerance": "SPEC", "vibration": "TEL"}


def _attr(query: str):
    low = query.lower()
    for name in sorted(ATTRIBUTES, key=len, reverse=True):
        if name in low:
            return name
    return None


def _prefix(node_id: str) -> str:
    return node_id.split("-")[0] if "-" in node_id else node_id


@dataclass
class Plan:
    multipart: bool
    subtasks: list = field(default_factory=list)   # ordered hops (audit artifact)
    attribute: str | None = None
    owner_prefix: str | None = None
    seed: str | None = None
    target: str | None = None                      # resolved attribute-bearing doc id
    reason: str = ""


def is_multipart(query: str, stores) -> bool:
    """Multi-part iff relational AND the attribute owner type differs from the
    resolved entity type (the attribute is a hop away)."""
    ents = resolve_entities(query, stores.alias_map)
    attr = _attr(query)
    if not (attr and ents and "relational" in classify(query)):
        return False
    owner = ATTR_OWNER.get(attr)
    if not owner:
        return False
    # if a resolved entity already IS the owner type, it's single-hop
    return not any(_prefix(e) == owner for e in ents)


_PART_TYPES = ("bearing", "shaft", "gasket", "bracket", "cover", "sensor",
               "bolt", "fastener")


def _constraint_part(query: str, stores) -> str | None:
    """If the query names a part TYPE (e.g. 'bearing'), resolve it to the specific
    SPEC doc whose description matches — the intermediate constraint a pure graph
    path would otherwise ignore (which part of Cyclops? the bearing)."""
    low = query.lower()
    for pt in _PART_TYPES:
        if pt in low:
            for rec in stores.structured.query("parts"):
                if pt in str(rec.fields.get("description", "")).lower():
                    return rec.key
    return None


def decompose(query: str, stores) -> Plan:
    """Find the shortest graph path from a resolved seed to an attribute-bearing
    entity of the owner type; each hop is a sub-task (verified fact). If the query
    names an intermediate part constraint, route the path THROUGH it."""
    ents = resolve_entities(query, stores.alias_map)
    attr = _attr(query)
    owner = ATTR_OWNER.get(attr) if attr else None
    if not (attr and ents and owner):
        return Plan(False, reason="not decomposable")

    # intermediate constraint waypoint (e.g. the 'bearing') the path must pass
    waypoint = _constraint_part(query, stores)

    g = stores.graph
    for seed in ents:
        if not g.has_node(seed):
            continue
        if waypoint and g.has_node(waypoint):
            # seed -> waypoint (the constraint part) -> target (owner type)
            p1 = _bfs_path(g, seed, lambda n: n == waypoint, stores)
            p2 = _bfs_path(g, waypoint, lambda n: _prefix(n) == owner and n in stores.doc_ids,
                           stores)
            if p1 is not None and p2:
                path = p1 + p2
                target = path[-1]["to"] if path else None
            else:
                continue
        else:
            path = _bfs_path(g, seed, lambda n: _prefix(n) == owner and n in stores.doc_ids
                             and n != seed, stores)
            target = path[-1]["to"] if path else None
        if path and target:
            subtasks = [{"id": f"T{i+1}", "step": f"{h['from']} -[{h['rel']}]-> {h['to']}",
                         "kind": "traversal", "verified_fact": h} for i, h in enumerate(path)]
            subtasks.append({"id": f"T{len(path)+1}",
                             "step": f"lookup {attr} of {target}", "kind": "terminal_lookup"})
            return Plan(True, subtasks=subtasks, attribute=attr, owner_prefix=owner,
                        seed=seed, target=target,
                        reason=f"{len(path)}-hop path {seed} -> {target}"
                               + (f" via {waypoint}" if waypoint else ""))
    return Plan(True, attribute=attr, owner_prefix=owner, seed=ents[0],
                reason="multipart but no graph path found -> will abstain (weakest-link)")


def _bfs_path(g, src, is_target, stores):
    """Shortest path from src to the first node satisfying is_target. Returns a
    list of {from,rel,to} hops ([] if src itself is the target, None if none)."""
    if is_target(src):
        return []
    prev = {src: None}
    frontier = deque([src])
    while frontier:
        node = frontier.popleft()
        for e in g.neighbors(node):
            nb = e.dst if e.src == node else e.src
            if nb in prev:
                continue
            prev[nb] = (node, e.rel)
            if is_target(nb):
                path, cur = [], nb
                while prev[cur] is not None:
                    par, rel = prev[cur]
                    path.append({"from": par, "rel": rel, "to": cur})
                    cur = par
                path.reverse()
                return path
            frontier.append(nb)
    return None


__all__ = ["Plan", "is_multipart", "decompose", "ATTR_OWNER"]

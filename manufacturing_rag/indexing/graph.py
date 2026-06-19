"""
Graph store (spec 7.1).  STATUS: IMPLEMENTED (in-memory adjacency + JSON persist).

Nodes (entity, and later chunk/proposition/summary) + edges (triples,
chunk->entity, parent-child, ...). Idempotent entity merge (aliases/source_links
unioned). `neighbors()` works today; `personalized_pagerank` is the Phase-3
multi-hop lever (stub). Edges carry relation `properties` for Phase-4 rule eval.
Neo4j/Kuzu is the hosted swap target; same interface.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import Entity, Edge


class GraphStore:
    def __init__(self):
        self.nodes: dict[str, Entity] = {}
        self.edges: list[Edge] = []

    def add_entity(self, e: Entity):
        if e.canonical_id in self.nodes:                 # idempotent alias merge
            cur = self.nodes[e.canonical_id]
            cur.aliases = sorted(set(cur.aliases) | set(e.aliases))
            cur.source_links = sorted(set(cur.source_links) | set(e.source_links))
            cur.attrs = {**cur.attrs, **e.attrs}
        else:
            self.nodes[e.canonical_id] = e

    def add_edge(self, edge: Edge):
        key = (edge.src, edge.rel, edge.dst)
        if key not in {(x.src, x.rel, x.dst) for x in self.edges}:   # idempotent
            self.edges.append(edge)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def neighbors(self, node_id: str):
        return [e for e in self.edges if e.src == node_id or e.dst == node_id]

    def node_count(self) -> int:
        return len(self.nodes)

    def edge_count(self) -> int:
        return len(self.edges)

    def dangling_edges(self) -> list[Edge]:
        """Edges whose src or dst is not a known node (join-integrity check)."""
        ids = set(self.nodes)
        return [e for e in self.edges if e.src not in ids or e.dst not in ids]

    # ---- persistence (idempotent) ----
    def save(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        data = {"nodes": [n.to_dict() for n in self.nodes.values()],
                "edges": [e.to_dict() for e in self.edges]}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def load(self, path: str | Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for n in data.get("nodes", []):
            self.add_entity(Entity.from_dict(n))
        for e in data.get("edges", []):
            self.add_edge(Edge.from_dict(e))
        return self

    def personalized_pagerank(self, seeds: list[str], k: int = 10):
        raise NotImplementedError("Phase 3: PPR multi-hop over the seeded graph.")


__all__ = ["GraphStore"]

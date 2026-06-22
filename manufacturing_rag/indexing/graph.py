"""
Graph store (spec 7.1).

GraphStore     — in-memory adjacency + JSON persistence (default).
Neo4jGraphStore — Neo4j-backed persistent graph; same interface, Cypher behind
                  the methods. Activated when models.graph_store = 'neo4j'.

Connection: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD env vars (or config).
Local:  bolt://localhost:7687  (Neo4j Desktop / Docker)
Cloud:  neo4j+s://<id>.databases.neo4j.io  (AuraDB)
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

    def dump(self, limit: int = 400) -> dict:
        """Nodes + edges for visualization."""
        nodes = [{"id": n.canonical_id, "type": n.type}
                 for n in list(self.nodes.values())[:limit]]
        edges = [{"src": e.src, "rel": e.rel, "dst": e.dst}
                 for e in self.edges[:limit]]
        return {"nodes": nodes, "edges": edges}

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


class Neo4jGraphStore:
    """Neo4j-backed graph store — persistent, no rebuild needed on restart.

    Implements the same interface as GraphStore so all callers (graph_lane,
    agent.py data_map, verify_index) work without changes.

    Relationship types in Neo4j must be valid identifiers; we sanitize rel
    names to [A-Z0-9_]+ before writing (safe — rels come from our pipeline,
    not user input).
    """

    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_constraints()

    def _ensure_constraints(self):
        with self.driver.session() as s:
            s.run("CREATE CONSTRAINT entity_id IF NOT EXISTS "
                  "FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE")

    def close(self):
        self.driver.close()

    # ---- helpers ----

    @staticmethod
    def _rel_type(rel: str) -> str:
        import re
        return re.sub(r"[^A-Z0-9]", "_", rel.upper()) or "RELATED"

    def _edge_from_record(self, rec) -> Edge:
        props = dict(rec["props"] or {})
        return Edge(
            src=rec["src"], rel=rec["rel"], dst=rec["dst"],
            properties=props,
            source_doc_id=props.pop("source_doc_id", ""),
            trust=float(props.pop("trust", 1.0)),
        )

    # ---- write ----

    def add_entity(self, e: Entity):
        with self.driver.session() as s:
            s.run(
                "MERGE (n:Entity {canonical_id: $id}) "
                "SET n.type = $type, n.aliases = $aliases, "
                "    n.source_links = $sl, n.attrs = $attrs, "
                "    n.name = $id",                       # name = caption shown in Neo4j Browser
                id=e.canonical_id, type=e.type,
                aliases=json.dumps(e.aliases),
                sl=json.dumps(e.source_links),
                attrs=json.dumps(e.attrs),
            )

    def add_edge(self, edge: Edge):
        rtype = self._rel_type(edge.rel)
        props = {**edge.properties,
                 "rel": edge.rel,             # store original rel name in props
                 "source_doc_id": edge.source_doc_id,
                 "trust": edge.trust}
        with self.driver.session() as s:
            s.run(
                f"MATCH (a:Entity {{canonical_id: $src}}), "
                f"      (b:Entity {{canonical_id: $dst}}) "
                f"MERGE (a)-[r:{rtype} {{src: $src, dst: $dst}}]->(b) "
                f"SET r += $props",
                src=edge.src, dst=edge.dst, props=props,
            )

    # ---- read ----

    def has_node(self, node_id: str) -> bool:
        with self.driver.session() as s:
            result = s.run(
                "MATCH (n:Entity {canonical_id: $id}) RETURN count(n) > 0 AS found",
                id=node_id,
            )
            rec = result.single()
            return bool(rec and rec["found"])

    def neighbors(self, node_id: str) -> list[Edge]:
        with self.driver.session() as s:
            result = s.run(
                "MATCH (n:Entity {canonical_id: $id})-[r]-(m:Entity) "
                "RETURN properties(r) AS props, "
                "       n.canonical_id AS src_id, m.canonical_id AS dst_id, "
                "       type(r) AS rtype",
                id=node_id,
            )
            edges = []
            for rec in result:
                props = dict(rec["props"] or {})
                rel = props.get("rel") or rec["rtype"]
                src = props.get("src") or rec["src_id"]
                dst = props.get("dst") or rec["dst_id"]
                edges.append(Edge(
                    src=src, rel=rel, dst=dst,
                    properties={k: v for k, v in props.items()
                                 if k not in ("rel", "src", "dst", "source_doc_id", "trust")},
                    source_doc_id=props.get("source_doc_id", ""),
                    trust=float(props.get("trust", 1.0)),
                ))
            return edges

    @property
    def edges(self) -> list[Edge]:
        """All edges — used by agent.py data_map() to enumerate relation types."""
        with self.driver.session() as s:
            result = s.run(
                "MATCH (a:Entity)-[r]->(b:Entity) "
                "RETURN properties(r) AS props, type(r) AS rtype LIMIT 5000"
            )
            out = []
            for rec in result:
                props = dict(rec["props"] or {})
                out.append(Edge(
                    src=props.get("src", ""),
                    rel=props.get("rel") or rec["rtype"],
                    dst=props.get("dst", ""),
                    properties={}, source_doc_id="", trust=1.0,
                ))
            return out

    def node_count(self) -> int:
        with self.driver.session() as s:
            return s.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]

    def edge_count(self) -> int:
        with self.driver.session() as s:
            return s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    def dangling_edges(self) -> list[Edge]:
        """Neo4j enforces referential integrity — relationships always have
        both endpoints. Always returns []."""
        return []

    def dump(self, limit: int = 400) -> dict:
        """Nodes + edges for visualization (via Cypher)."""
        with self.driver.session() as s:
            nodes = [{"id": r["id"], "type": r["type"]} for r in s.run(
                "MATCH (n:Entity) RETURN n.canonical_id AS id, n.type AS type LIMIT $lim",
                lim=limit)]
            edges = [{"src": r["src"], "rel": (r["p"] or {}).get("rel") or r["rt"],
                      "dst": r["dst"]} for r in s.run(
                "MATCH (a:Entity)-[r]->(b:Entity) RETURN a.canonical_id AS src, "
                "type(r) AS rt, b.canonical_id AS dst, properties(r) AS p LIMIT $lim",
                lim=limit)]
        return {"nodes": nodes, "edges": edges}

    # ---- persistence (no-ops — Neo4j persists automatically) ----

    def save(self, path=None):
        pass   # data is already in Neo4j; nothing to write to disk

    def load(self, path=None):
        return self  # reconnects via __init__; data already in Neo4j

    def personalized_pagerank(self, seeds: list[str], k: int = 10):
        raise NotImplementedError("Use Neo4j GDS plugin for PPR multi-hop.")


__all__ = ["GraphStore", "Neo4jGraphStore"]

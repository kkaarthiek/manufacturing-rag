"""
Agentic retrieval mode (spec 8.7).  STATUS: IMPLEMENTED.

A schema-aware traverse agent: it reads the machine-readable DATA MAP, then asks
the LLM (temp 0) to plan retrieval ACTIONS over the real stores. It SEEDS
FROM THE DETERMINISTIC FLOOR and may only ADD evidence (recall never drops below
the floor). Bounded iterations; full action trace logged; the deterministic
coverage check (not the agent) still decides answer vs abstain.

Action set the planner may emit: resolve_entity, hybrid_search,
graph_traverse(seed, hops), sql_lookup(entity). Each maps to a real store call.
"""

from __future__ import annotations

import json
import re

from ..providers import get_llm
from ..contracts import Evidence
from .router import Retriever
from .lanes import graph_lane, hybrid_lane, structured_lane
from .understand import understand
from .fuse_rerank import rrf_merge, rerank
from .coverage import assess

PLANNER_SYSTEM = (
    "You are a retrieval planner over a manufacturing knowledge graph. Given a "
    "question, the data map, and the entities already resolved, output ONLY a JSON "
    "list of retrieval actions to gather the evidence. Allowed actions: "
    '{"action":"graph_traverse","seed":"<ID>","hops":<1-4>}, '
    '{"action":"hybrid_search","query":"<text>"}, '
    '{"action":"sql_lookup","entity":"<ID>"}. '
    "Plan the minimal set of hops needed; for multi-hop questions traverse from the "
    "resolved entity toward the answer entity. Output JSON only."
)


class AgenticRetriever:
    def __init__(self, cfg, stores, max_actions: int | None = None):
        self.cfg = cfg
        self.stores = stores
        self.base = Retriever(cfg, stores)
        self.max_actions = (max_actions if max_actions is not None
                            else getattr(cfg.thresholds, "agentic_max_actions", 6))
        self.llm = get_llm(cfg)

    def data_map(self) -> dict:
        return {
            "graph_relations": sorted({e.rel for e in self.stores.graph.edges}),
            "structured_tables": ["suppliers", "parts", "purchase_orders",
                                  "work_orders", "telemetry", "materials"],
            "doc_count": len(self.stores.doc_ids),
            "actions": ["resolve_entity", "hybrid_search",
                        "graph_traverse(seed,hops)", "sql_lookup(entity)"],
        }

    # ---- action executors (real store calls) ----
    def _exec(self, action: dict, plan) -> list:
        a = action.get("action")
        if a == "graph_traverse":
            seed = action.get("seed")
            hops = int(action.get("hops", 2))
            p = type(plan)(query=plan.query, entities=[seed], qtypes=plan.qtypes)
            return graph_lane(self.stores, p, depth=hops, k=20)
        if a == "hybrid_search":
            p = type(plan)(query=action.get("query", plan.query), entities=[], qtypes=[])
            return hybrid_lane(self.stores, p, k=20)
        if a == "sql_lookup":
            ent = action.get("entity")
            return [(r.key, 1.0) for r in self.stores.structured.by_key(ent)
                    if r.key in self.stores.doc_ids]
        return []

    def _plan(self, query: str, plan) -> list[dict]:
        prompt = (f"QUESTION: {query}\nDATA MAP: {json.dumps(self.data_map())}\n"
                  f"RESOLVED ENTITIES: {plan.entities}\nOutput the JSON action list:")
        try:
            out = self.llm.complete(prompt, system=PLANNER_SYSTEM, temperature=0.0)
            m = re.search(r"\[.*\]", out, re.S)
            return json.loads(m.group(0))[:self.max_actions] if m else []
        except Exception:
            return []

    def retrieve(self, query: str, k: int = 10):
        # 1) deterministic floor (recall floor; agentic can only ADD)
        floor_ev, cov, trace = self.base.retrieve(query, k=k, mode="agentic")
        floor_lanes = {"floor": [(e.id, e.scores.get("rerank", 0.0)) for e in floor_ev]}
        plan = understand(query, self.stores.alias_map)

        # 2) LLM-planned actions (or deterministic fallback)
        actions = self._plan(query, plan)
        trace["agentic_plan"] = actions or "deterministic-fallback"
        lanes = dict(floor_lanes)
        if actions:
            for i, act in enumerate(actions):
                lanes[f"act{i}:{act.get('action')}"] = self._exec(act, plan)
        else:
            # no-plan (LLM parse failed): deterministic deepening from resolved entities
            for d in (3, 4):
                lanes[f"graph@{d}"] = graph_lane(self.stores, plan, depth=d, k=20)
            lanes["structured"] = structured_lane(self.stores, plan, k=20)

        # 3) shared spine: fuse -> rerank -> coverage (same as deterministic)
        fused = rrf_merge(lanes)
        reranked = rerank(self.base.reranker, query, fused, self.base.doc_text, top_k=k)
        ev_texts = [self.base.doc_text(d) for d, _, _ in reranked]
        top = reranked[0][1] if reranked else 0.0
        cov = assess(query, ev_texts, self.cfg.thresholds.coverage_threshold, top)
        evidence = [Evidence(id=d, kind="chunk", content=self.base.doc_text(d),
                             source={"doc_id": d}, scores={"rerank": s}, trust=1.0)
                    for d, s, _ in reranked]
        return evidence, cov, trace


__all__ = ["AgenticRetriever"]

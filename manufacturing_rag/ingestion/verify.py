"""
Step 13 — verify & accuracy gate (spec 6.12).  STATUS: IMPLEMENTED.

Cross-checks every extracted fact vs ground truth: present + correctly
normalized + correctly resolved. LOUD failure on any missing/mismatched fact —
no silent drops. Raw is kept beside canonical (pipeline) for audit/reversibility.

Reuses eval.metrics.ingestion_fact_recall. Facts whose ground-truth entry has an
empty maps_to_doc_ids (machines.json = graph glue) are scored against the
pipeline's entity-graph doc rather than an empty haystack.
"""

from __future__ import annotations

import json

from ..config import Config
from ..eval.metrics import ingestion_fact_recall
from .pipeline import run_pipeline, haystacks, ENTITY_GRAPH_ID


def _patch_empty_maps(ingestion_gold: list[dict]) -> list[dict]:
    """Route empty-maps facts (entity_graph) to the pipeline's graph doc."""
    out = []
    for e in ingestion_gold:
        e = dict(e)
        if not e.get("maps_to_doc_ids"):
            e["maps_to_doc_ids"] = [ENTITY_GRAPH_ID]
        out.append(e)
    return out


def verify_ingestion(cfg: Config, ingestion_gold: list[dict]) -> dict:
    """Run the deterministic pipeline, build haystacks, score fact recall.
    Returns the report; sets halt=True (no silent pass) if below target."""
    pipe = run_pipeline()
    hay = haystacks(pipe.docs)
    gold = _patch_empty_maps(ingestion_gold)
    report = ingestion_fact_recall(gold, hay)
    report["pipeline_docs"] = len(pipe.docs)
    report["flags"] = pipe.flags
    target = cfg.thresholds.ingestion_recall_target
    report["target"] = target
    report["halt"] = report["recall"] < target
    return report


__all__ = ["verify_ingestion"]

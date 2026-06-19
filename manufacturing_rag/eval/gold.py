"""
Gold-set loading + self-verification.

Two gold sets (already authored in the repo):
  * INGESTION_GROUND_TRUTH.jsonl — per raw file: which canonical doc(s) it must
    yield + the key facts extraction must recover + planted mess. Drives the
    Phase-1 ingestion-fact-recall gate.
  * questions.jsonl — 72 query->answer items with gold_doc_ids + answerable flag.
    Drives retrieval recall@k and abstention metrics.

`verify_gold()` checks the gold itself (spec: "verify the gold set — gaps = a
false recall=1"): referenced doc_ids must exist, ids unique, answerability vs
gold-doc consistency, etc.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import Config


def _load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    rows = []
    if not p.exists():
        raise FileNotFoundError(f"gold file missing: {p}")
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{p.name} line {i}: {e}") from e
    return rows


@dataclass
class GoldSets:
    corpus: list[dict]            # canonical docs (Phase-1 target / Phase-0 stand-in)
    ingestion: list[dict]         # INGESTION_GROUND_TRUTH entries
    questions: list[dict]         # query gold
    corpus_by_id: dict            # doc_id -> doc


def load_gold(cfg: Config) -> GoldSets:
    corpus = _load_jsonl(cfg.paths.corpus)
    ingestion = _load_jsonl(cfg.paths.ingestion_ground_truth)
    questions = _load_jsonl(cfg.paths.question_gold)
    by_id = {d["doc_id"]: d for d in corpus}
    return GoldSets(corpus, ingestion, questions, by_id)


def verify_gold(g: GoldSets) -> list[str]:
    """Return a list of integrity problems in the gold itself ([] == clean)."""
    issues = []
    ids = [d["doc_id"] for d in g.corpus]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        issues.append(f"duplicate corpus doc_ids: {sorted(dup)}")
    id_set = set(ids)

    # ingestion gold references real docs
    for e in g.ingestion:
        for did in e.get("maps_to_doc_ids", []):
            if did not in id_set:
                issues.append(f"ingestion '{e['source_file']}' maps to unknown doc {did}")
        if not e.get("key_facts"):
            issues.append(f"ingestion '{e['source_file']}' has no key_facts")

    # question gold: ids unique, gold docs exist, answerability consistency
    qids = [q["qid"] for q in g.questions]
    dupq = {i for i in qids if qids.count(i) > 1}
    if dupq:
        issues.append(f"duplicate qids: {sorted(dupq)}")
    for q in g.questions:
        for did in q.get("gold_doc_ids", []):
            if did not in id_set:
                issues.append(f"{q['qid']}: gold_doc_id {did} not in corpus")
        is_high = q.get("category") == "high_level_synthesis"
        if not q.get("answerable", True):
            if q.get("gold_doc_ids"):
                issues.append(f"{q['qid']}: unanswerable but has gold_doc_ids")
        elif not is_high and not q.get("gold_doc_ids"):
            issues.append(f"{q['qid']}: answerable non-high_level but no gold_doc_ids")
    return issues


__all__ = ["GoldSets", "load_gold", "verify_gold"]

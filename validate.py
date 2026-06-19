#!/usr/bin/env python3
"""
validate.py — Integrity harness for the RAG golden dataset.

Loads corpus.jsonl and questions.jsonl and asserts the dataset is internally
consistent and schema-correct. Prints a summary and exits non-zero on any
failure. Standard library only.

Checks:
  - all JSON lines parse
  - all doc_ids and all qids are unique
  - every gold_doc_id referenced by a question exists in corpus.jsonl
  - every question category and persona is from the allowed set
  - unanswerable / non-answerable questions have empty gold_doc_ids
  - answerable, non-high_level questions have >= 1 gold_doc_id
  - required fields are present on every record
"""

import json
import sys
from collections import Counter
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
CORPUS_PATH = OUT_DIR / "corpus.jsonl"
QUESTIONS_PATH = OUT_DIR / "questions.jsonl"

ALLOWED_CATEGORIES = {
    "single_fact", "multi_hop", "aggregation_count", "comparison",
    "numeric_calculation", "unit_conversion", "temporal_versioned",
    "conflict_resolution", "unanswerable", "jargon_codename_acronym",
    "tabular_reasoning", "procedural_stepwise", "constraint_filtering",
    "ambiguous_needs_clarification", "out_of_scope_rejection",
    "high_level_synthesis", "entity_disambiguation",
}
ALLOWED_PERSONAS = {
    "design_engineer", "procurement", "quality", "maintenance", "plant_manager",
}
ALLOWED_DIFFICULTY = {"easy", "medium", "hard"}

DOC_REQUIRED = {"doc_id", "doc_type", "title", "text", "metadata"}
Q_REQUIRED = {"qid", "question", "category", "difficulty", "persona",
              "answerable", "gold_doc_ids", "reference_answer", "eval_notes"}

errors = []


def err(msg):
    errors.append(msg)


def load_jsonl(path):
    rows = []
    if not path.exists():
        err(f"Missing file: {path.name}")
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                err(f"{path.name} line {i}: JSON parse error: {e}")
    return rows


def main():
    corpus = load_jsonl(CORPUS_PATH)
    questions = load_jsonl(QUESTIONS_PATH)

    # ---- corpus checks ----
    doc_ids = []
    for d in corpus:
        missing = DOC_REQUIRED - set(d)
        if missing:
            err(f"corpus doc {d.get('doc_id', '?')} missing fields: {sorted(missing)}")
            continue
        doc_ids.append(d["doc_id"])
        if not isinstance(d["metadata"], dict):
            err(f"corpus doc {d['doc_id']} metadata is not an object")
        if not d["text"].strip():
            err(f"corpus doc {d['doc_id']} has empty text")

    dup_docs = [k for k, v in Counter(doc_ids).items() if v > 1]
    if dup_docs:
        err(f"duplicate doc_ids: {dup_docs}")
    doc_id_set = set(doc_ids)

    # ---- question checks ----
    qids = []
    for q in questions:
        missing = Q_REQUIRED - set(q)
        if missing:
            err(f"question {q.get('qid', '?')} missing fields: {sorted(missing)}")
            continue
        qid = q["qid"]
        qids.append(qid)

        if q["category"] not in ALLOWED_CATEGORIES:
            err(f"{qid}: invalid category '{q['category']}'")
        if q["persona"] not in ALLOWED_PERSONAS:
            err(f"{qid}: invalid persona '{q['persona']}'")
        if q["difficulty"] not in ALLOWED_DIFFICULTY:
            err(f"{qid}: invalid difficulty '{q['difficulty']}'")
        if not isinstance(q["answerable"], bool):
            err(f"{qid}: 'answerable' must be a boolean")
        if not isinstance(q["gold_doc_ids"], list):
            err(f"{qid}: 'gold_doc_ids' must be a list")
            continue

        # every gold_doc_id must exist in the corpus
        for gid in q["gold_doc_ids"]:
            if gid not in doc_id_set:
                err(f"{qid}: gold_doc_id '{gid}' not found in corpus")

        # answerability / gold-doc consistency
        is_high_level = q["category"] == "high_level_synthesis"
        if not q["answerable"]:
            if q["gold_doc_ids"]:
                err(f"{qid}: non-answerable question must have empty gold_doc_ids")
        else:
            if not is_high_level and len(q["gold_doc_ids"]) == 0:
                err(f"{qid}: answerable non-high_level question must have >= 1 gold_doc_id")

        if not q["reference_answer"].strip():
            err(f"{qid}: empty reference_answer")

    dup_qs = [k for k, v in Counter(qids).items() if v > 1]
    if dup_qs:
        err(f"duplicate qids: {dup_qs}")

    # ---- summary ----
    print("=" * 64)
    print("RAG GOLDEN DATASET - VALIDATION SUMMARY")
    print("=" * 64)
    print(f"Corpus documents : {len(corpus)}")
    print(f"Questions        : {len(questions)}")
    print()

    print("Docs by doc_type:")
    for t, n in sorted(Counter(d["doc_type"] for d in corpus).items()):
        print(f"  {t:20s} {n}")
    print()

    print("Questions by category:")
    for c, n in sorted(Counter(q["category"] for q in questions).items()):
        print(f"  {c:32s} {n}")
    print()

    print("Questions by difficulty:")
    for c, n in sorted(Counter(q["difficulty"] for q in questions).items()):
        print(f"  {c:12s} {n}")
    print()

    print("Questions by persona:")
    for c, n in sorted(Counter(q["persona"] for q in questions).items()):
        print(f"  {c:18s} {n}")
    print()

    ans = sum(1 for q in questions if q.get("answerable"))
    print(f"Answerable vs unanswerable: {ans} answerable / "
          f"{len(questions) - ans} not answerable")
    print("=" * 64)

    if errors:
        print(f"\nFAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("\nALL CHECKS PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()

"""
Metrics (spec Section 5).

  * ingestion_fact_recall  — Phase-1 gate (target 1.0). Every gold key_fact must
    be recoverable from the canonical doc(s) it maps to.
  * retrieval_recall_at_k  — Phase-2/3 metric (target 1.0 on gold).
  * mrr                    — rank quality of first gold doc.
  * abstention_correctness — answer on answerable, abstain on unanswerable.
  * faithfulness / e2e     — defined here, marked PENDING (need Phase 3 generation).

Fact-recovery check is deliberately conservative: a fact counts as recovered
only if ALL its load-bearing tokens (entity IDs + numbers) appear in the
haystack. The real Phase-1 verify gate is stricter still (exact normalized match
+ self-consistency); this baseline check proves the metric and gives a number to
drive to 1.0.
"""

from __future__ import annotations

import json
import re

from ..providers import tokenize

_ID = re.compile(r"\b[A-Z]{2,4}-\d{2,5}(?:-v\d+)?\b")
_STOP = {"the", "and", "for", "with", "from", "this", "that", "are", "was",
         "per", "via", "not", "into", "only", "must", "should", "field"}


def _significant(fact: str):
    ids = _ID.findall(fact)
    no_ids = _ID.sub(" ", fact)
    nums = re.findall(r"\d+\.?\d*", no_ids)
    words = [w for w in tokenize(no_ids)
             if len(w) >= 4 and not w.replace(".", "").isdigit() and w not in _STOP]
    return ids, nums, words


def _present(token: str, haystack: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(token.lower()) + r"(?![A-Za-z0-9])",
                     haystack) is not None


def fact_recovered(fact: str, haystack: str) -> bool:
    haystack = haystack.lower()
    ids, nums, words = _significant(fact)
    if ids or nums:
        return (all(_present(i, haystack) for i in ids)
                and all(_present(n, haystack) for n in nums))
    if not words:
        return True
    hit = sum(1 for w in words if w in haystack)
    return hit / len(words) >= 0.6


def ingestion_fact_recall(ingestion_gold: list[dict], canonical_by_id: dict) -> dict:
    """canonical_by_id: doc_id -> haystack string (clean_text + structured fields)."""
    total = recovered = 0
    misses, per_file = [], {}
    for e in ingestion_gold:
        hay = " ".join(canonical_by_id.get(d, "") for d in e.get("maps_to_doc_ids", []))
        f_tot = f_rec = 0
        for fact in e.get("key_facts", []):
            f_tot += 1
            if fact_recovered(fact, hay):
                f_rec += 1
            else:
                misses.append({"file": e["source_file"], "fact": fact})
        total += f_tot
        recovered += f_rec
        per_file[e["source_file"]] = (f_rec, f_tot)
    return {"recall": recovered / total if total else 0.0,
            "recovered": recovered, "total": total,
            "per_file": per_file, "misses": misses}


def _eval_questions(questions):
    """Answerable questions that carry gold docs (skip high_level [] and unanswerable)."""
    return [q for q in questions
            if q.get("answerable", True) and q.get("gold_doc_ids")]


def retrieval_recall_at_k(questions, retrieve_fn, ks) -> dict:
    items = _eval_questions(questions)
    if not items:
        return {k: 0.0 for k in ks}
    kmax = max(ks)
    out = {k: 0 for k in ks}
    for q in items:
        ranked = [doc_id for doc_id, _ in retrieve_fn(q["question"], kmax)]
        gold = set(q["gold_doc_ids"])
        for k in ks:
            if gold.issubset(set(ranked[:k])):
                out[k] += 1
    return {k: out[k] / len(items) for k in ks}


def mrr(questions, retrieve_fn, kmax=10) -> float:
    items = _eval_questions(questions)
    if not items:
        return 0.0
    total = 0.0
    for q in items:
        ranked = [doc_id for doc_id, _ in retrieve_fn(q["question"], kmax)]
        gold = set(q["gold_doc_ids"])
        rr = 0.0
        for i, did in enumerate(ranked, 1):
            if did in gold:
                rr = 1.0 / i
                break
        total += rr
    return total / len(items)


def abstention_correctness(questions, retrieve_fn, abstain_score: float) -> dict:
    """Baseline decision: answer if top retrieval score >= threshold, else abstain.
    Correct = answer on answerable, abstain on not-answerable."""
    ans_ok = ans_tot = abs_ok = abs_tot = 0
    for q in questions:
        ranked = retrieve_fn(q["question"], 1)
        top = ranked[0][1] if ranked else 0.0
        decided_answer = top >= abstain_score
        if q.get("answerable", True):
            ans_tot += 1
            ans_ok += 1 if decided_answer else 0
        else:
            abs_tot += 1
            abs_ok += 1 if not decided_answer else 0
    overall = (ans_ok + abs_ok) / (ans_tot + abs_tot) if (ans_tot + abs_tot) else 0.0
    return {"answer_on_answerable": ans_ok / ans_tot if ans_tot else 0.0,
            "abstain_on_unanswerable": abs_ok / abs_tot if abs_tot else 0.0,
            "overall": overall,
            "answerable_n": ans_tot, "unanswerable_n": abs_tot}


def faithfulness(*_a, **_k) -> dict:
    return {"status": "pending", "reason": "needs Phase 3 generation"}


def e2e_correctness(*_a, **_k) -> dict:
    return {"status": "pending", "reason": "needs Phase 3-4 generation + verification"}


__all__ = ["fact_recovered", "ingestion_fact_recall", "retrieval_recall_at_k",
           "mrr", "abstention_correctness", "faithfulness", "e2e_correctness"]

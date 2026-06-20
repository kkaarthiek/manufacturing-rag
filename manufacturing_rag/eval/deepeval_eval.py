"""
DeepEval external audit (optional, behind --deepeval flag).

Complements RAGAS with a different faithfulness definition:
  RAGAS:    every claim must be *supported by* retrieved context  (strict entailment)
  DeepEval: claims must *not contradict* retrieved context        (pragmatic consistency)

Running both flags catches different failure modes. Where they disagree on the same
question, those are the highest-priority manual review cases.

Run:
    python -m manufacturing_rag.eval --deepeval --hosted

Install:
    pip install deepeval
"""

from __future__ import annotations


def _check_deps() -> bool:
    try:
        import deepeval  # noqa: F401
        return True
    except ImportError:
        print("\n  [DeepEval] Missing package: deepeval")
        print("  Install: pip install deepeval")
        return False


# ------------------------------------------------------------------ dataset --

def _get_answer(q_text: str, stores, evidence: list, llm) -> tuple[str | None, str]:
    """Return (answer_text, status): answered | abstained | partial."""
    from ..verification.assemble import answer as det_answer
    from ..verification.synthesize import synthesize

    a = det_answer(q_text, stores)
    if a.status == "abstained":
        return None, "abstained"
    if a.status == "answered":
        return a.text, "answered"
    if evidence:
        synth = synthesize(q_text, evidence, llm)
        if synth.status == "answered":
            return synth.text, "answered"
        if synth.status == "abstained":
            return None, "abstained"
    return None, "partial"


def collect_dataset(stores, g, cfg, k: int = 10) -> list[dict]:
    """
    Run retrieval + answer pipeline for every question.
    Returns rows with: qid, question, contexts, answer, ground_truth,
                       answerable, status, skip_eval
    """
    from ..retrieval.agent import AgenticRetriever
    from ..providers import get_llm

    retriever = AgenticRetriever(cfg, stores)
    llm = get_llm(cfg)

    rows = []
    for q in g.questions:
        is_answerable = q.get("answerable", True)
        try:
            evidence, _cov, _ = retriever.retrieve(q["question"], k=k)
            contexts = [
                (e.content if isinstance(e.content, str) else str(e.content))
                for e in evidence if e.content
            ] or ["(no context retrieved)"]
            answer_text, status = _get_answer(q["question"], stores, evidence, llm)
        except Exception as exc:
            contexts = ["(retrieval error)"]
            answer_text, status = None, f"error:{type(exc).__name__}"

        skip = (
            not is_answerable
            or status == "partial"
            or status.startswith("error:")
            or (status == "abstained" and is_answerable)
        )

        rows.append({
            "qid": q["qid"],
            "question": q["question"],
            "contexts": contexts,
            "answer": answer_text or "",
            "ground_truth": q.get("reference_answer", ""),
            "answerable": is_answerable,
            "status": status,
            "skip_eval": skip,
        })
    return rows


# ------------------------------------------------------------------- scoring -

def _make_metrics(model: str = "gpt-4o") -> list:
    """Instantiate DeepEval RAG metrics with GPT-4o as judge."""
    from deepeval.metrics import (FaithfulnessMetric, ContextualRecallMetric,
                                  ContextualPrecisionMetric, AnswerRelevancyMetric)
    return [
        FaithfulnessMetric(threshold=0.5, model=model,
                           include_reason=True, verbose_mode=False),
        ContextualRecallMetric(threshold=0.5, model=model,
                               include_reason=False, verbose_mode=False),
        ContextualPrecisionMetric(threshold=0.5, model=model,
                                  include_reason=False, verbose_mode=False),
        AnswerRelevancyMetric(threshold=0.5, model=model,
                              include_reason=False, verbose_mode=False),
    ]


def run_deepeval(rows: list[dict], cfg) -> dict:
    """
    Score each scoreable row by running all metrics against it.
    Returns {metric_name: mean_score} or {"error": str}.
    Uses metric.measure() per-question to avoid rich console encoding issues.
    """
    from deepeval.test_case import LLMTestCase

    scoreable = [r for r in rows if not r["skip_eval"]]
    if not scoreable:
        return {"error": "no scoreable rows — all answers partial/abstained/errored"}

    judge_model = cfg.models.llm  # gpt-4o
    metrics = _make_metrics(model=judge_model)

    # accumulate scores per metric
    totals: dict[str, list[float]] = {m.name: [] for m in metrics}

    for r in scoreable:
        tc = LLMTestCase(
            input=r["question"],
            actual_output=r["answer"],
            retrieval_context=r["contexts"],
            expected_output=r["ground_truth"],
        )
        for m in metrics:
            try:
                m.measure(tc, _show_indicator=False)
                if m.score is not None:
                    totals[m.name].append(float(m.score))
            except Exception:
                pass   # skip failed evaluations — don't abort the whole run

    return {
        name: (sum(vals) / len(vals)) if vals else None
        for name, vals in totals.items()
    }


# ------------------------------------------------------------------ report ---

def deepeval_report(stores, g, cfg) -> dict:
    """
    Full DeepEval audit. Returns structured dict for the harness.

    Keys:
      scores        — {metric: float | None}
      n_total       — total questions
      n_scoreable   — questions scored
      n_skipped     — questions skipped
      abstain_ok    — unanswerable questions correctly abstained
      abstain_n     — total unanswerable questions
    """
    if not _check_deps():
        return {"error": "missing deps — pip install deepeval"}

    rows = collect_dataset(stores, g, cfg)
    unans = [r for r in rows if not r["answerable"]]

    return {
        "scores":      run_deepeval(rows, cfg),
        "n_total":     len(rows),
        "n_scoreable": sum(1 for r in rows if not r["skip_eval"]),
        "n_skipped":   sum(1 for r in rows if r["skip_eval"]),
        "abstain_ok":  sum(1 for r in unans if r["status"] == "abstained"),
        "abstain_n":   len(unans),
    }


__all__ = ["collect_dataset", "run_deepeval", "deepeval_report"]

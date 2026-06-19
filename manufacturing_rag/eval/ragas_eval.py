"""
RAGAS external audit (optional, behind --ragas flag).

Independent second opinion on faithfulness + context recall using RAGAS's NLI-
based entailment check per claim against retrieved context. Complements the
internal verifier — same invariant, different implementation path.

Run:
    python -m manufacturing_rag.eval --ragas            # offline answers + RAGAS scoring
    python -m manufacturing_rag.eval --ragas --hosted   # full synthesis answers + RAGAS

Install dependencies before first use:
    pip install ragas langchain-anthropic
"""

from __future__ import annotations

_DEPS = ("ragas", "langchain_anthropic")


def _patch_ragas_compat() -> None:
    """
    RAGAS 0.4.3 unconditionally imports ChatVertexAI from
    langchain_community.chat_models.vertexai, which was removed in
    langchain_community 0.4+. Stub it so RAGAS loads when we're using
    Anthropic — the stub class is never instantiated.
    """
    import sys, types
    path = "langchain_community.chat_models.vertexai"
    if path not in sys.modules:
        stub = types.ModuleType(path)
        stub.ChatVertexAI = type("ChatVertexAI", (), {})  # dummy, never used
        sys.modules[path] = stub
        parent = sys.modules.get("langchain_community.chat_models")
        if parent is not None:
            setattr(parent, "vertexai", stub)


def _check_deps() -> bool:
    _patch_ragas_compat()   # must run before importing ragas
    missing = []
    for pkg in _DEPS:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg.replace("_", "-"))
    if missing:
        print(f"\n  [RAGAS] Missing packages: {', '.join(missing)}")
        print("  Install: pip install ragas langchain-anthropic")
    return not missing


# ------------------------------------------------------------------ dataset --

def _get_answer(q_text: str, stores, evidence: list, llm) -> tuple[str | None, str]:
    """
    Return (answer_text, status).
    status: 'answered' | 'abstained' | 'partial'
    Tries deterministic answer first; if partial, falls back to grounded synthesis
    (hosted only — RuleStubLLM returns partial, never synthesised).
    """
    from ..verification.assemble import answer as det_answer
    from ..verification.synthesize import synthesize
    from ..providers import RuleStubLLM

    a = det_answer(q_text, stores)
    if a.status == "abstained":
        return None, "abstained"
    if a.status == "answered":
        return a.text, "answered"
    # partial — no deterministic op matched; try LLM synthesis
    if not isinstance(llm, RuleStubLLM) and evidence:
        synth = synthesize(q_text, evidence, llm)
        if synth.status == "answered":
            return synth.text, "answered"
        if synth.status == "abstained":
            return None, "abstained"
    return None, "partial"


def collect_dataset(stores, g, cfg, k: int = 10) -> list[dict]:
    """
    Run retrieval + answer pipeline for every question.

    Each row:
      qid, question, contexts, answer, ground_truth,
      answerable, status, skip_ragas

    skip_ragas is True for:
      - unanswerable questions (abstention validated separately)
      - answerable questions where synthesis couldn't complete (partial / offline)
      - false-abstentions on answerable questions (flagged, not penalised here)
    """
    from ..retrieval.router import Retriever
    from ..providers import get_llm, RuleStubLLM

    retriever = Retriever(cfg, stores)
    try:
        llm = get_llm(cfg)
    except Exception:
        llm = RuleStubLLM()

    rows = []
    for q in g.questions:
        is_answerable = q.get("answerable", True)
        evidence, _cov, _ = retriever.retrieve(q["question"], k=k)
        contexts = [
            (e.content if isinstance(e.content, str) else str(e.content))
            for e in evidence if e.content
        ] or ["(no context retrieved)"]

        answer_text, status = _get_answer(q["question"], stores, evidence, llm)

        skip = (
            not is_answerable          # handle abstention separately
            or status == "partial"     # incomplete answer — don't penalise
            or (status == "abstained" and is_answerable)  # false abstention — flag only
        )

        rows.append({
            "qid": q["qid"],
            "question": q["question"],
            "contexts": contexts,
            "answer": answer_text or "",
            "ground_truth": q.get("reference_answer", ""),
            "answerable": is_answerable,
            "status": status,
            "skip_ragas": skip,
        })
    return rows


# ------------------------------------------------------------------- scoring -

def _make_judge(cfg):
    """Build a Haiku-backed LangchainLLMWrapper for RAGAS."""
    from langchain_anthropic import ChatAnthropic
    from ragas.llms import LangchainLLMWrapper
    return LangchainLLMWrapper(
        ChatAnthropic(model=cfg.models.llm, temperature=0, max_tokens=4096)
    )


def _build_dataset(scoreable: list[dict]):
    """Build a RAGAS EvaluationDataset from scoreable rows."""
    from ragas import EvaluationDataset, SingleTurnSample
    return EvaluationDataset(samples=[
        SingleTurnSample(
            user_input=r["question"],
            retrieved_contexts=r["contexts"],
            response=r["answer"],
            reference=r["ground_truth"],
        )
        for r in scoreable
    ])


def _get_classic_metrics():
    """
    Use the classic (non-collections) ragas.metrics singletons — these work with
    LangchainLLMWrapper + evaluate(..., llm=judge). The collections API (0.4.3+)
    requires InstructorLLM which doesn't support LangChain-based models.
    Suppress the deprecation warnings since the classic API is still functional.
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from ragas.metrics import (faithfulness, context_recall,
                                   context_precision, answer_relevancy)
    return [faithfulness, context_recall, context_precision, answer_relevancy]


def run_ragas_eval(rows: list[dict], cfg) -> dict:
    """
    Score the scoreable rows. Returns snake_case dict:
      faithfulness, context_recall, context_precision, answer_relevancy
    or {"error": "..."} if nothing is scoreable / evaluation fails.
    """
    from ragas import evaluate

    scoreable = [r for r in rows if not r["skip_ragas"]]
    if not scoreable:
        return {"error": ("no scoreable rows — all answers are partial or abstained; "
                          "run with --hosted to enable grounded synthesis")}

    judge   = _make_judge(cfg)
    dataset = _build_dataset(scoreable)
    metrics = _get_classic_metrics()

    raw = evaluate(dataset=dataset, metrics=metrics, llm=judge, raise_exceptions=False)

    # RAGAS 0.4.x returns EvaluationResult with .scores = list[dict] (per sample).
    # Average across samples, skipping NaN (failed evaluations).
    per_sample = getattr(raw, "scores", None) or []
    if not per_sample and hasattr(raw, "items"):
        # fallback: older RAGAS returned a dict directly
        per_sample = [dict(raw)]

    all_keys = {k for d in per_sample for k in d}
    scores: dict = {}
    for k in all_keys:
        vals = []
        for d in per_sample:
            v = d.get(k)
            if v is None:
                continue
            try:
                f = float(v)
                if f == f:   # exclude NaN (NaN != NaN)
                    vals.append(f)
            except (TypeError, ValueError):
                pass
        scores[k] = (sum(vals) / len(vals)) if vals else None
    return scores


# ------------------------------------------------------------------ report ---

def ragas_report(stores, g, cfg) -> dict:
    """
    Full RAGAS audit orchestrator. Returns a structured dict for the harness.

    Keys:
      scores          — {metric: float} or {"error": str}
      n_total         — total questions
      n_scoreable     — questions included in RAGAS scoring
      n_skipped       — questions excluded (partial / unanswerable / false-abstained)
      abstain_ok      — unanswerable questions where system correctly abstained
      abstain_n       — total unanswerable questions
    """
    if not _check_deps():
        return {"error": "missing deps — pip install ragas langchain-anthropic"}

    rows = collect_dataset(stores, g, cfg)

    unans = [r for r in rows if not r["answerable"]]
    return {
        "scores":       run_ragas_eval(rows, cfg),
        "n_total":      len(rows),
        "n_scoreable":  sum(1 for r in rows if not r["skip_ragas"]),
        "n_skipped":    sum(1 for r in rows if r["skip_ragas"]),
        "abstain_ok":   sum(1 for r in unans if r["status"] == "abstained"),
        "abstain_n":    len(unans),
    }


__all__ = ["collect_dataset", "run_ragas_eval", "ragas_report"]

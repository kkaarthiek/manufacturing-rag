# Manufacturing RAG — Test Context

## What Was Built

A reliability-first RAG pipeline over a manufacturing corpus (42 canonical docs, 72 gold queries).
Stack: Python stdlib-only offline default; OpenAI `text-embedding-3-large` (3072-d) + Claude `claude-haiku-4-5` (hosted).

### Phases & Gates (all passing)

| Phase | Key Gate | Result |
|-------|----------|--------|
| 0 — Foundations | Contracts frozen, eval harness live | ✅ |
| 1A — Ingestion (deterministic) | ingestion-fact recall = **1.000** (52/52) | ✅ |
| 1B — Ingestion (semantic) | 295 propositions + 173 questions + 42 contextual chunks; 20 trust-flagged | ✅ |
| 2 — Indexing | index-coverage **100%**, round-trip recall@10 single-hop **1.000** | ✅ |
| 3 — Retrieval | recall floor (union) = **1.000**; ranked recall@10=0.91 / @20=0.98 | ✅ |
| 4 — Verification | faithfulness = **1.0** (0 unsupported claims); abstention **13/13** unanswerable + **59/59** answerable | ✅ |
| 5 — Orchestration | multi-hop end-to-end **2/2**; anti-pᴺ invariant holds (0 unverified intermediates) | ✅ |
| 6 — System eval | adversarial suite **8/8**; `--strict` CI gate green | ✅ |

### CI Gate
```
python -m manufacturing_rag.eval --strict     # must exit 0
python -m manufacturing_rag.eval --hosted     # with real embeddings + LLM
```

### Key Files
```
manufacturing_rag/
├── eval/harness.py            # main runner (phases 0-4 metrics)
├── eval/metrics.py            # ingestion_fact_recall, retrieval_recall_at_k, faithfulness, abstention_correctness
├── eval/adversarial.py        # 8 adversarial cases (injection, trap, conflict, version, OOS, distractor, OCR)
├── verification/synthesize.py # grounded synthesis + entailment gate
├── retrieval/router.py        # deterministic fan-out
├── retrieval/agent.py         # agentic mode (opt-in)
├── orchestration/             # plan.py / execute.py / compose.py
└── app/system.py              # end-to-end System class + ask CLI
```

### Core Invariant
> A claim ships only if it is **verbatim from source** OR a **verifiable deterministic operation** over sourced inputs — otherwise abstain. Fail toward abstention, never fabrication.

---

## RAG Testing Framework: RAGAS (recommended)

**Why RAGAS over alternatives:**

| Framework | Stars | Faithfulness fit | Verdict |
|-----------|-------|-----------------|---------|
| **RAGAS** | ~13.8k | Strict NLI entailment per claim — matches system invariant exactly | ✅ **Primary** |
| DeepEval | ~15.5k | Permissive semantic check — passes claims outside retrieved context | ⚠️ CI harness only |
| TruLens | ~3.4k | RAG Triad (3 metrics), observability-first, not gold-set oriented | ⚠️ Monitoring only |
| Arize Phoenix | ~10.2k | Good tracing, but ELv2 license; faithfulness less rigorous | ⚠️ Observability add-on |
| Giskard | ~5.4k | RAG eval "Planned" in v3 — not production-ready | ❌ Skip |

### Install
```bash
pip install ragas
```

### Integration (zero pipeline changes — pass existing outputs)
```python
from ragas import evaluate
from ragas.metrics import faithfulness, context_recall, context_precision, answer_relevancy
from ragas.llms import LangchainLLMWrapper
from langchain_anthropic import ChatAnthropic

# Use the same Haiku already in the stack as judge
judge = LangchainLLMWrapper(ChatAnthropic(model="claude-haiku-4-5", temperature=0))

dataset = [
    {
        "question":     q["question"],
        "contexts":     retrieved_chunks,   # list[str] from retrieval phase
        "answer":       generated_answer,   # str from synthesize.py
        "ground_truth": q["gold_answer"],   # from questions.jsonl
    }
    for q, retrieved_chunks, generated_answer in eval_results
]

result = evaluate(
    dataset,
    metrics=[faithfulness, context_recall, context_precision, answer_relevancy],
    llm=judge,
)

# Gates
assert result["faithfulness"] == 1.0,    "Faithfulness gate failed"
assert result["context_recall"] >= 0.98, "Context recall regression"
print(result)
```

### What each RAGAS metric validates
| Metric | What it checks | Maps to existing gate |
|--------|---------------|----------------------|
| `faithfulness` | Every answer claim entailed by retrieved context | Phase 4 faithfulness = 1.0 |
| `context_recall` | Gold answer inferable from retrieved context | Phase 3 recall@10 floor |
| `context_precision` | Retrieved context ranked — relevant chunks first | Phase 3 rerank quality |
| `answer_relevancy` | Answer addresses the question | Complements abstention check |

### Abstention note
RAGAS has no first-class abstention metric. For the 13 unanswerable questions, assert `answer == abstention_marker` before scoring — abstained answers score `faithfulness=1.0` naturally (no claims → no unsupported claims).

### Recommended run cadence
- **On every eval cycle** after `python -m manufacturing_rag.eval --strict`
- RAGAS faithfulness = external second opinion on the internal gate
- Context recall = independent cross-validation of recall@10 using `questions.jsonl` ground truth
- Keep the existing custom harness as the **primary CI gate**; RAGAS as **reproducible external audit**

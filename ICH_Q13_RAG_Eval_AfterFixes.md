# ICH Q13 RAG — Eval After Fixes

Companion to `ICH_Q13_RAG_Issue_Handoff_for_ClaudeCode.md` (the **before** eval:
92/110, 84%, zero hallucinations). This documents what was actually wrong, the
fixes applied, and the verified **after** behaviour on the same cases.

## Root causes found (against the real code — not the black-box hypotheses)

The handoff attributed the completeness/variability issues to **chunking** and
**retrieval non-determinism**. Inspecting the real pipeline, the dominant causes
were two synthesis/ranking bugs the black-box eval couldn't see:

1. **Synthesis truncated each retrieved chunk to 600 chars.** Chunks are ~1,200
   chars; any answer in a chunk's second half was cut off before the model saw
   it. This alone produced the "incomplete list", "answer exists but says not in
   KB", and "works on retry" symptoms. → Fixed: pass the full chunk (1,600).
2. **The reranker could drop the rank-1 hybrid hit.** Rerank was reducing recall.
   → Fixed: synthesis context = union(top-6 hybrid, top reranked); rerank adds
   precision but can no longer remove the best chunk.

Chunking and retrieval were largely fine: e.g. for the batch-size query the
correct §2.2 chunk was retrieved at **rank 1** — it was being truncated, not
mis-retrieved. Embeddings are deterministic; the only non-determinism is the LLM
reranker (mitigated by the union floor above).

## Prompt improvements adopted (from the handoff, verified to help)

- **Completeness:** enumerate every distinct item incl. nested sub-points
  (replaced a counter-productive "2-4 sentences" cap).
- **Premise check:** correct a false premise when the evidence contradicts it.
- **Helpful refusal:** on no direct answer, state what the document *does* cover /
  which guideline owns the detail — without inventing specifics.
- **Examples vs rules** (added): don't present an example-only value as a
  universal limit; say it's process-specific when the doc treats it that way.

The no-fabrication guarantee was preserved (out-of-scope still abstains; the
entailment gate still rejects ungrounded numbers).

## Before → After on the handoff's cases (verified live)

| Case | Before | After | Cause / fix |
|------|--------|-------|-------------|
| **A1** production-output approaches | 3 of 4 (dropped scale-out) | **all 4 incl. scale-out + 2 nested sub-bullets** | truncation, not chunking |
| **B1** batch-size definition | wrong section / variable | **correct 3 ways (output material / input material / run time), stable** | truncation + rerank-recall |
| **T9** "Q13 prohibits surge tanks" (false premise) | flat refusal | **corrects premise: "Q13 permits surge tanks…"** | premise-check prompt |
| **T3** max disturbance duration | (would over-state an example value) | **"no universal limit; process-specific examples"** | examples-vs-rules prompt |
| **T7** Established Conditions categories | bare refusal | **still abstains** — confirmed a **retrieval gap** (the §4.9 Q12-deferral chunk doesn't surface), not a prompt issue | needs query expansion |
| out-of-scope (e.g. Tesla price) | abstain | **abstain (unchanged)** | guarantee preserved |

## Remaining real weakness (not a prompt fix)

**Cross-reference retrieval (T7-style):** when the answer is "see Q12 / §4.9" and
the query is phrased around the missing concept, the deferral chunk doesn't rank.
Fix is retrieval-side — query expansion or a stronger calibrated reranker —
tracked as future work.

## Internal regression gate (synthetic harness, every commit)

`python -m manufacturing_rag.eval --strict` → **exit 0**, all 6 phases:
P0 foundations · P1 ingestion-fact recall 1.000 · P2 index-coverage 100% ·
P3 retrieval recall floor 1.000 · P4 faithfulness 1.0 + abstention 13/13 + 59/59 ·
P5 verified-chain · P6 adversarial 8/8. Acceptance: high recall + calibrated
abstention + zero confident-wrong.

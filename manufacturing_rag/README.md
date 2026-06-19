# manufacturing_rag — Phases 0–2

Reliability-first RAG over the Helios Plant 7 corpus, built per the *Build Spec
(Phases 0–2)*. **Measure-first**: the eval gate exists before the pipeline, and
no phase advances until its gate passes on the gold set.

## Status

| Phase | Scope | Status |
|-------|-------|--------|
| **0 — Foundations** | contracts, eval harness, config, skeleton | ✅ **implemented & passing** |
| **1 — Ingestion** | raw/ → validated canonical objects | 🟡 skeleton (step 1 `master.py` done; rest stubbed behind contracts) |
| **2 — Indexing** | objects → queryable stores | 🟡 skeleton (store interfaces + offline flat index) |

## Run the eval gate

```bash
python -m manufacturing_rag.eval            # print the gate board, exit 0 if Phase 0 OK
python -m manufacturing_rag.eval --strict   # exit 1 unless every BUILT gate meets target
```

This loads the gold sets, **verifies the gold itself**, runs the current pipeline
(Phase-0 baselines until 1–2 land), and prints a per-phase gate board. Intended
to run on every commit as a regression gate.

Current baseline numbers (offline, deterministic):
- ingestion-fact recall **0.615** (32/52) — misses are the *derived* facts
  (totals, normalized units, aggregations) Phase 1 will compute → drives to 1.0.
- retrieval recall@5 **0.91**, @10 **0.96**, MRR **0.91** (BM25 baseline).
- abstention: answers 100% of answerable, abstains on 8% of unanswerable — the
  calibration gap the Phase-3 reranker closes.

## Layout (spec Section 8)

```
manufacturing_rag/
├── contracts.py        # Section 4 dataclasses — FROZEN seam between lanes
├── config/             # pinned model registry + thresholds (config-driven)
├── providers.py        # Embedder/Reranker/LLM interfaces + OFFLINE defaults
├── eval/               # gold loading, metrics, baselines, gate harness  ← built first
├── ingestion/          # Phase 1: master(done) + parsers/clean/extract/transforms/
│                       #          resolve/derive/versioning/verify (stubs)
├── indexing/           # Phase 2: vector/keyword/structured/graph/load (interfaces)
├── stores/             # store clients (read-only to live sources)
└── app/                # CLI (eval today; `ask` in Phases 3–4)
```

## Offline by default, hosted by config

The spec names hosted models (Voyage, Cohere, Claude, Neo4j…) but requires them
to be swappable. Every model/store sits behind an interface in `providers.py` /
`indexing/`. The default `provider_mode="offline"` uses deterministic stdlib
implementations (hashing embedder, lexical reranker, BM25, in-memory graph) so
the gate runs with **zero dependencies and no network**.

To go hosted: set `models.provider_mode="hosted"` and the model names in
`config/default.json`, implement the corresponding provider class (each raises a
clear TODO until then), and supply API keys via env. **No call site changes** —
the contracts and metrics are unchanged.

## What's deliberately NOT here yet

Phases 1–2 are conformant skeletons: signatures + docstrings tied to spec
sections, raising `NotImplementedError` with the exact next step. The single
extraction pass (`ingestion/extract.py`, spec 6.4) is the hot path to build
first. Retrieval/answering/verification/orchestration are Phases 3–6 (later).
```
```

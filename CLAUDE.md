# Manufacturing RAG — Project Memory

This file is the authoritative build spec for the `manufacturing_rag/` package. It is loaded
every session. The full Phases 0–6 design follows the status section below — **read the status
first**, then the spec.

---

## CURRENT BUILD STATUS (update as phases advance)

Implemented in `manufacturing_rag/` (stdlib-only, offline-default; hosted models are a config swap).

| Phase | Status | Gate |
|-------|--------|------|
| **0 — Foundations** | ✅ done | contracts frozen, eval harness + gold self-verify, config/providers pinned |
| **1 — Ingestion (Tranche A, deterministic core)** | ✅ done — **G1 PASS** | ingestion-fact recall **1.000 (52/52)**, 43 canonical docs, 7 conflict flags (never merged), 0 silent fails |
| **1 — Ingestion (Tranche B, semantic layers)** | ✅ done | Haiku single-pass extraction (`extract.py`) → 295 propositions + 173 questions + 42 contextual chunks; each grounding-verified vs source (`derive.py`), 20 trust-flagged; triples→graph edges |
| **2 — Indexing (P2-early)** | ✅ done — **G2 PASS** | index-coverage **100%**, join integrity ✓, embedding sanity ✓; sqlite structured + JSON graph + hybrid text index, all-or-nothing + idempotent + persistable to `_artifacts/` |
| **2 — Indexing (P2-late)** | ✅ done | multi-granularity index (510 units) + real OpenAI 3072-d embeddings. Round-trip recall@10: **single-hop 1.000**, multi-hop 0.75, all 0.89. Run with `python -m manufacturing_rag.eval --hosted` (paid; extractions cached in `_artifacts/extractions.json`). |

**Multi-hop gap (recall@10: 6/24 multi-hop queries miss) is BY DESIGN deferred to Phase 3/5** — a single query embedding structurally can't resolve relational hops (e.g. "supplier of the bearing on Cyclops"). Closed by the graph/PPR lane + query entity-resolution (Phase 3) and decomposition (Phase 5). Do NOT chase it with text-retrieval tricks (spec §8.7 research note).
| **3 — Retrieval** | ✅ done — **G3 PASS** | **recall FLOOR (union) = 1.000** — every gold doc retrievable for every answerable q. Dual-mode (deterministic `router.py` / opt-in agentic `agent.py`); graph BFS + structured lanes close single-query multi-hop (Cyclops→bearing→supplier); weighted RRF + lexical rerank; content-term coverage signal. Ranked recall@10=0.91/@20=0.98 (top-k refined by rerank + Phase-5 decomp). |
| **4 — Verification** | ✅ done — **G4 PASS** | **faithfulness = 1.0** (0 unsupported claims ship), **abstention 13/13 unanswerable + 59/59 answerable** (deterministic absence verifier: structured query empty + entity-exists → abstain). Verifier taxonomy (`verify_claims.py`), calc lane, answer-assembly router; exact/derived values re-run (wrong value rejected). 9/59 answered deterministically; rest route to grounded NL synthesis. |
| **5 — Orchestration** | ✅ done — **G5 PASS** | graph-path decomposition with waypoint constraints (Cyclops→**bearing**→supplier→45); **anti-pᴺ invariant: 0 unverified intermediates chain**; multi-hop end-to-end 2/2; abstention composes (weakest-link). `orchestration/{plan,execute,compose}.py` |
| **6 — System eval & hardening** | ✅ done — **G6 PASS** | adversarial suite **8/8** (prompt-injection-immune via slot-fill, derivation-trap rejected, conflict surfaced, version current-wins, not-in-corpus/out-of-scope abstain, distractor-free, OCR-corrected); `--strict` CI gate green; fail-toward-abstention. **FINAL ACCEPTANCE SIGNED OFF** vs Phase-0 bar. |

**ALL 6 PHASES PASS** — `python -m manufacturing_rag.eval --strict` exits 0. Acceptance: high recall (floor 1.0) + calibrated abstention (13/13 unanswerable, 59/59 answerable) + zero confident-wrong (faithfulness 1.0). Offline/zero-dep default; hosted (OpenAI emb + Haiku) via `--hosted`.

### Query-time LLM wiring (added after the 6-phase build)
The query side was deterministic-only at first; the LLM pieces are now wired (hosted; offline keeps deterministic fallbacks so the CI gate stays green):
- **Grounded synthesis** (`verification/synthesize.py`) — Haiku generates the answer constrained to retrieved evidence, temp 0, cited; an **entailment gate** rejects any answer containing a number/ID not in the evidence (no fabrication). The 50 non-deterministic questions now get real NL answers. e.g. "PRT-2002 material?" → *"...made from PA66 (Nylon 6/6)... [SPEC-2002, MAT-PA66]"*, verified.
- **LLM agentic retrieval** (`retrieval/agent.py`) — Haiku reads the data map and emits real retrieval actions (graph_traverse/hybrid_search/sql_lookup), seeded from the deterministic floor (can only add). Verified surfacing SUP-103+SPEC-2003 for the Cyclops-bearing multi-hop.
- **LLM reranker** (`providers.LLMReranker`) — batched Haiku relevance ranking (zerank-2 substitute); offline → lexical.
- **End-to-end `System` + `ask` CLI** (`app/system.py`, `app/cli.py`):
  `python -m manufacturing_rag.app.cli ask "question" [--hosted] [--agentic]` → grounded answer + citations + plan + abstention.

### Web app connected to the live pipeline
- `app.py` chat (`/api/chat`) is backed by the real `System` (Phase 3→4→5), mode selector (deterministic/hosted/agentic); renders status, verified claims, the multi-hop verified chain, and citations. SQLite opened `check_same_thread=False` + chat serialized under a lock (ThreadingHTTPServer safe).
- **Uploaded files flow into the LIVE pipeline (spec 6.11 incremental):** `System.add_document()` parses+classifies+resolves a new file, registers name aliases, adds a doc node + MENTIONS edges + an incrementally-embedded text chunk (+ Haiku-derived propositions/questions when hosted) — **no rebuild**. `/api/upload` feeds every built System; uploads persist in `raw/inbox/` and are **replayed on System build** (survive restart). Uploaded free-text docs route to grounded synthesis (not structured-absence), so the gold 13/13 abstention stays intact. Verified: chat answers "who supplies the titanium flange on Goliath?" → *"Apex Components LLC (SUP-201)..."* over a freshly uploaded doc.

### Open-source parsers + robust rich extraction (real-industry PDFs)
The hand-rolled regex binary parsers couldn't read real PDFs (TJ arrays, object streams) — replaced with open-source libs (**PyMuPDF, pdfplumber, python-docx, openpyxl**) behind the parser interface, stdlib regex fallback retained so the offline gate never hard-depends on them. `ingestion/rich.py` (`rich_extract`) handles every real PDF shape (spec 6.2/6.4):
- **digital text** — PyMuPDF (ICH Q13: 0 chars → 110K chars fixed)
- **structured tables** — pdfplumber grids → markdown in text + **per-row StructuredRecords** (header context). 7 tables from ICH Q13.
- **embedded images** — Claude **vision captions** (hosted, capped) → text-index units (`AnthropicLLM.vision()`)
- **scanned / image-only PDFs** — `pdf_text_coverage < 80` → **vision OCR** of rendered pages (hosted); flagged loudly when offline (never silent-empty)
- **chunking** — large docs split into overlapping chunks (`chunk_text`), each embedded incrementally (ICH → 132 chunks)
deps: `pip install pymupdf pdfplumber python-docx openpyxl`. Offline gate stays green; vision/OCR run only hosted + capped for cost.

### FRESH REAL-DATA PORTAL (current default)
`python app.py` → http://localhost:8000 is now a **real-data portal** (not the synthetic demo):
- **Fresh/empty by default** — `System(fresh=True)` skips the synthetic Helios pipeline; the chat answers ONLY over docs the user ingests (`build_empty_index`). Empty KB → "upload files first".
- **Real answers** — chat defaults to hosted (Claude Haiku synthesis + OpenAI embeddings); abstains on out-of-scope / not-in-docs (no hallucination). Verified on real ICH Q13 PDF: scope, control strategy, regulatory considerations all answered + grounded.
- **Chunk-level retrieval** (`_answer_fresh`) — real multi-page docs have many chunks; retrieves/reranks at CHUNK level (not parent-deduped), so the answer-bearing chunk reaches synthesis. (This was the key real-doc fix.)
- **Index persistence** — `System._save_live()/_load_live()` persist text-index(+embeddings)/graph/structured to `_artifacts/live_<mode>/`; **restart loads in ~8s instead of re-extracting (~200s)**. Uploads survive restart.
- **`/api/live-docs`** shows what the chat actually knows (per-doc chunk counts).
- Synthetic eval data (corpus.jsonl, raw/ subdirs) kept on disk but invisible in the portal — `python -m manufacturing_rag.eval --strict` still exits 0 (all 6 phases).

**Real-portal caveats:** (1) first upload of a large PDF takes ~200s (parse + chunk-embed + vision captions); persisted after. (2) Vision captioning/OCR are capped (first ~6-8 images/pages) for cost. (3) entailment gate tolerates a few ungrounded section-refs in prose (abstains only on wholesale fabrication).

**Run the gate board:** `python -m manufacturing_rag.eval` (exit 0 if built gates pass; `--strict` to enforce).

### Decisions locked (deviations from spec candidate lists — see §5)
- **Embeddings:** `openai:text-embedding-3-large` (3072-d). *Not* on the spec's candidate list (user choice). Key via `OPENAI_API_KEY`. Stdlib `urllib`, no `openai` SDK.
- **LLM (extract/verify):** `claude-haiku-4-5`, temp 0 + self-consistency N=3, prompt-cached system prompt. Key via `ANTHROPIC_API_KEY`. Stdlib `urllib`, no `anthropic` SDK. ⚠️ Haiku is below the spec's "strong model" bar for extraction — **the G3/G4 gates validate it; escalate to Sonnet/Opus if recall < 1.0** (one config line).
- **Storage @ 42 docs:** stdlib `sqlite3` + JSON, exact/flat vector search (spec 7.3) — swap to Qdrant/Neo4j/Postgres only when the corpus outgrows exact. All behind provider/store interfaces.
- **Raw HTTP not SDKs:** deliberate, to honor the stdlib-only / offline-default constraint. Switch to official SDKs if that constraint is lifted.
- **`.env` auto-loaded** by `config.load_dotenv()` (stdlib; existing env vars win). Keys present and valid. Add `.env` to `.gitignore` if this becomes a git repo.

### Two artifacts the package is built around (don't break these)
- `raw/` + `raw/INGESTION_GROUND_TRUTH.jsonl` — 28 messy source files (the ingestion test bed) + the scoring key.
- `corpus.jsonl` (42 clean canonical docs), `questions.jsonl` (72 query gold), `questions.csv`.

### Working rules for this project
- **Measure-first, one gate at a time.** No phase advances until its gate passes on the gold set. Print the board and let the user sign off before advancing.
- Every LLM step temp 0 + self-consistency; instrument heavily.
- The cross-cutting invariant: *verbatim-from-source OR verifiable-deterministic-operation, else abstain*; and *fail toward abstention, never fabrication.*
- Before the first hosted run, smoke-test each key (a few cents) before the full ingest (~<$1).

---

# Manufacturing RAG — Build Spec (Phases 0–6)

> A reliability-first retrieval system for a single full-access user over a manufacturing corpus (live data + documents + drawings). This is the **complete** design: Foundations → Ingestion → Indexing → Retrieval → Verification → Orchestration → System eval. Built to be implemented incrementally in Claude Code, measure-first, one phase-gate at a time.

---

## 0. Scope & reliability posture

- **One user, full data access.** No per-role permissions yet; reserve an authz hook at the lane/source boundary.
- **Acceptance criterion.** Literal 100% accuracy is neither provable nor the target. The system targets two measurable things:
  1. **High recall** — the needed evidence is retrievable (drive toward 1.0 on a labeled gold set).
  2. **Calibrated abstention** — when evidence is absent/insufficient, say so rather than guess. A confident "not found" is correct; a confident wrong fact is the failure being engineered out.
- **"Never trade accuracy for compute" → operational rules.** Compute is unconstrained, so every choice defaults to the more accurate path:
  - deterministic over approximate; exhaustive over sampled; redundant/ensemble over single-pass; verify-everything.
  - protect accuracy asymmetrically: **never miss a retrievable fact** (exhaustive + deterministic + redundant ingestion) and **never ship a wrong one** (verify + abstain). Abstention trades *coverage*, never *correctness*.
  - structure any fact that *can* be structured, so it is looked up exactly, not searched approximately.
  - all LLM steps run at **temperature 0** with **self-consistency** (N runs, require agreement) on extraction/verification/control.
  - measure continuously against the gold set; no phase advances until its gate passes.
- **The one-line invariant that ties the whole system together:** *a claim ships only if it is verbatim from a source, or the output of a verifiable deterministic operation over sourced inputs — otherwise the system abstains.* Everything below is machinery to make that true and to prove it.

---

## 1. Design principles

1. Every step is **deterministic**, **grounded-and-verified**, or an **explicit abstention** — never an unconstrained generative leap.
2. **Recall first, precision second.** Retrieve wide, narrow with rerank (rerank is the single largest retrieval gain).
3. **Faithfulness is enforced, not assumed.** Checking is cheaper and more reliable than generating (generate-then-verify).
4. **Traceability & version-awareness are first-class.** Every fact cites a source; document facts cite revision + section; live facts cite query + timestamp.
5. **Live data is queried live; documents are indexed.** Never serve operational numbers from a stale snapshot.
6. **Bound every retry, verify before chaining.** Chaining *unverified* LLM steps multiplies error (pᴺ); chaining *verified* facts does not.
7. **Fail toward abstention, never fabrication.** Under any fault, the worst case is "I can't answer," never a confident wrong answer.

---

## 2. Architecture overview

Four stores, joined on **entity IDs**:

| Store | Holds | Used for |
|---|---|---|
| **Text index** | contextual chunks + propositions + hypothetical questions + summary nodes (vector + BM25) | semantic / keyword search |
| **Structured store** | per-row records (exact values) | exact lookup, aggregation, comparison, absence |
| **Knowledge graph** | entities, aliases, triples, chunk/proposition/summary nodes | resolution + multi-hop traversal + rule eval |
| **Originals store** | raw files + images | viewing, provenance, audit, re-check |

**Ingestion flow (Phases 1–2):**

```
raw files
  └─1 load master data (machines.json → aliases + seed graph)
  └─2 detect format/encoding → parse (binaries: 2 parsers + vision, reconcile)
  └─3 clean & split (strip boilerplate; split 2-in-1; OCR-fix scans)
  └─4 EXTRACT — one LLM pass → context + propositions + triples + entities + questions + dates
  └─5 normalize & resolve (units/formats keep raw; resolve IDs; aggregate; dedup/conflict; version)
  └─6 build derived layers (contextual chunks; propositions; triples→graph; summary tree)
  └─7 verify & validate (vs source + self-consistency + ground truth; trust-tag; halt on miss)
        └─► text index | structured store | knowledge graph | originals
```

**Query flow (Phases 3–5):**

```
query
  └─ resolve entities (surface form ↔ canonical ID, both directions)
  └─ ORCHESTRATE (Phase 5): simple → one pass | complex → decompose to sub-task DAG
       └─ per (sub-)query — RETRIEVE (Phase 3):
            mode = deterministic (router fan-out + union)  OR  agentic (schema-aware traverse)
            → hybrid text | structured | graph(PPR) | summary → RRF fuse → rerank → coverage check
       └─ ANSWER + VERIFY (Phase 4):
            abstain-first → grounded synthesis (exact values slot-filled, never composed)
            → answer-assembly router → verify each claim by class → faithfulness gate
            → answer | abstain | partial
  └─ assemble verified sub-answers → verify the composition → final answer + full trace
```

The verified-evidence handoff between phases is what keeps error from compounding: each (sub-)answer is grounded-or-abstained *before* it is reused.

---

## 3. Data inventory

**12 content types** (+ `machines.json` master-data feed) → 42 canonical documents:
supplier records, part/BOM specs, SOPs, maintenance logs, quality/NCRs, standards/compliance, purchase orders, materials datasheets, telemetry summaries (OEE/vibration), troubleshooting/FAQ, safety/incident reports, off-topic noise (distractors).

**9 file formats:** CSV, TXT (free-text), TXT (OCR scan), HTML, EML (one cp1252), JSON, PDF (binary), XLSX (binary), DOCX (binary).

**8 cross-cutting transforms (run per-type during parsing, not a separate stage):**
encoding detection · unit normalization · format normalization · reference resolution · multi-doc split · aggregation · dedup/conflict-flag · boilerplate stripping.

`machines.json` = the entity master (machine ↔ codename ↔ line ↔ program); loaded first, it is the resolution key everything else depends on.

---

## 4. Core data contracts (freeze before building lanes)

```python
@dataclass
class CanonicalDoc:
    id: str
    doc_type: str
    source_file: str
    format: str
    clean_text: str
    structured_fields: dict
    version: dict          # {rev, effective_date, is_current}
    entities: list[str]    # canonical IDs mentioned
    provenance: dict       # file, page/section, char span

@dataclass
class StructuredRecord:
    table: str
    key: str
    fields: dict
    raw: dict              # original values, pre-normalization (kept)
    normalized: dict       # normalized values
    units: dict
    validity: dict         # {start, end, state: current|superseded}
    source_doc_id: str

@dataclass
class Entity:
    canonical_id: str
    type: str              # machine|part|supplier|line|program|material...
    aliases: list[str]
    attrs: dict
    source_links: list[str]

@dataclass
class Edge:                # a triple
    src: str
    rel: str
    dst: str
    properties: dict       # e.g. {transitive: bool, symmetric: bool, exclusive: bool}
    source_doc_id: str
    trust: float

@dataclass
class DerivedUnit:         # proposition | question | summary
    id: str
    kind: str
    text: str
    parent_id: str         # reference, not a copy
    entities: list[str]
    source_span: dict
    trust: float
    verified: bool

# ---- query-time contracts (Phases 3–5) ----

@dataclass
class Evidence:            # a retrieved item
    id: str
    kind: str              # chunk|proposition|record|triple|summary
    content: str | dict
    source: dict           # doc_id, span/row, version, validity
    entities: list[str]
    scores: dict           # {vector, bm25, rerank}
    trust: float

@dataclass
class Claim:               # an atomic claim inside an answer
    text: str
    ctype: str             # verbatim|derived_calc|derived_logic|completeness|absence|entailment
    value: object | None
    operation: dict | None # for derived_calc/logic: op + operands(+sources) / proof chain
    citations: list[str]   # evidence/source ids
    verified: bool

@dataclass
class SubTask:
    id: str
    question: str
    ttype: str             # lookup|traversal|calc|comparison|aggregation|absence
    deps: list[str]        # ids of sub-tasks whose verified answers feed this one
    result: "Answer | None"

@dataclass
class Answer:
    text: str
    claims: list[Claim]
    status: str            # answered|abstained|partial
    missing: list[str]     # what couldn't be grounded (for partial/abstain)
    trace: dict            # plan + retrieval + verification trace (audit/replay)
```

---

## 5. Phase 0 — Foundations  ✅ LOCKED

**Goal:** build the skeleton and the *measurement* before any data is touched. Measure-first is non-negotiable.

- **Contracts** (Section 4) frozen first; lanes are swappable behind them.
- **Config / models** (pin defaults; pick finally by benchmarking on the gold set — leaderboards don't transfer):
  - embeddings: Voyage-4 / Gemini Embedding 2 / Cohere Embed v4 (hosted) or Qwen3-Embedding / Llama-Embed-Nemotron-8B / BGE-M3 (local). *Plan to union multiple retrievers* (compute is free).
  - reranker: Cohere Rerank 3.5 / BGE-reranker-v2-m3 / **zerank-2** (calibrated scores → fixed abstain threshold).
  - LLM (extract/verify/synthesize): strong model, **temp 0**, pinned version.
  - *(current as of early 2026; re-verify.)*
- **Eval harness** (the core of this phase):
  - load `INGESTION_GROUND_TRUTH.jsonl` → gold facts per file.
  - **author the query→answer gold set early** (recall@k / faithfulness need it), and **verify the gold set itself** (gaps = a false recall=1). Include multi-part, conflict, version, absence, and not-in-corpus cases from the start.
  - metrics: ingestion-fact recall, retrieval recall@k, faithfulness, abstention correctness, end-to-end correctness.
  - per-phase definition of done = its metric at target; runnable on every commit (regression gate).
- **Reliability gates** (all phases): no advance until metric hits target on gold; every fragile op cross-checked and **fails loudly** (no silent drops); uncertain → abstain.
- **Repo skeleton** (Section 12) + a `contracts/` module.

**Done when:** contracts frozen; harness loads ground truth and runs against stubs; models/config pinned; skeleton in place.

---

## 6. Phase 1 — Ingestion  ✅ LOCKED

**Goal:** turn the 42 raw artifacts into validated canonical objects — contextual chunks, propositions, questions, summaries, structured records, entities, triples — every gold fact present, correctly normalized, resolved, traceable.
**Gate:** ingestion-fact recall = 1.0 vs `INGESTION_GROUND_TRUTH.jsonl`, zero silent failures.

### 6.1 Pipeline order
1. Load `machines.json` → alias→ID map + seed graph (**first**).
2. Per file: detect format + encoding → route to parser.
3. Parse (binaries get 2 parsers, cross-checked).
4. Strip boilerplate (HTML nav/footers, PDF headers/footers/page-nos, email headers/quotes/sig).
5. Split multi-doc (2-in-1 → separate docs).
6. OCR-noise correction (scans), registry-guided.
7. **Extract — one LLM pass** (see 6.4).
8. Normalize units + formats (keep raw + normalized).
9. Resolve references → canonical IDs (unresolved → loud flag).
10. Aggregate (telemetry → summaries).
11. Dedup / conflict-flag (never delete; validity/lifecycle tags).
12. Version-tag (rev, effective_date, is_current).
13. Build derived layers (contextual chunks, propositions, triples→graph, summary tree).
14. Verify & validate → loud halt on any miss.

### 6.2 Parsers (per format)
- CSV ×6: robust parse; dirty/missing fields flagged, not dropped.
- TXT free ×9: encoding-aware read; NER (LLM temp 0 + self-consistency) + regex for IDs/codes.
- TXT OCR ×2: dedicated OCR (Mistral OCR 3) or VLM transcription → registry-guided correction; cross-check corrected IDs against the part/code registry.
- HTML ×4: DOM parse, strip boilerplate, preserve step/list order.
- EML ×2: detect encoding (incl. cp1252) → strip headers/quotes/sig → body.
- JSON ×1: master-data parse.
- PDF ×1 (`HX-900`): true text-extract + layout-aware tables + strip headers/footers; **2 parsers reconciled**, second = vision-LLM page transcription.
- XLSX ×1 (`FPY`): structured table-extract → per-row records, not flattened.
- DOCX ×1 (`SOP-001 Rev2`): Word parse, preserve steps.
- **Redundancy rule:** every binary parsed two ways; disagreement on any gold fact → flag, never silently pick. (Even best parsers ~90% page-faithful — hence redundancy + verification.)

### 6.3 The 8 transforms
1. Encoding: detect charset before decode; verify (no mojibake).
2. Units: rule table → canonical (time→h, length→mm, lead-time→days); **keep raw + normalized**; round-trip check.
3. Formats: dates→ISO, currency→value+code, strip separators; keep raw.
4. References: alias→ID map (`machines.json` + supplier master) applied to every mention; unresolved → loud flag.
5. Split: detect markers → separate docs; verify each independently retrievable.
6. Aggregate: deterministic summaries (vibration mean/peak, monthly OEE); keep raw rows linked.
7. Dedup/conflict: never delete — duplicates linked, conflicts kept + flagged.
8. Boilerplate: strip nav/footers/page-nos/sig; verify gold facts survive.

### 6.4 Single extraction pass (efficiency: one call, many outputs)
Per cleaned chunk, **one** LLM call (self-consistency) returns, in one structured output:
- the **context blurb** (for contextual chunking),
- the **atomic propositions** (facts),
- the **(subject, predicate, object) triples** (with relation properties where known: transitive/symmetric/exclusive),
- the **entity mentions + resolved IDs**,
- the **hypothetical questions** the chunk answers,
- any **validity/date signals**.

This replaces 5+ separate passes. Tables → per-row records (header context attached) + whole table kept. Images → caption (for the text index) + original kept.

### 6.5 Extraction → store
- **Structured store:** supplier fields, BOM/part specs, PO fields, work-order fields, FPY, telemetry summaries, materials numeric properties.
- **Text index:** contextual chunks, propositions, questions, SOP/standards/NCR/incident/troubleshooting/email/shift-note text, materials descriptions.
- **Graph:** machine/part/supplier/line/program nodes + triples + chunk↔entity, parent-child, chunk↔summary, proposition↔source edges + alias sets.
- A fact may feed multiple stores; derived units **reference parents, never copy text**.

### 6.6 Entity resolution (the #1 recall lever)
- `machines.json` → canonical IDs + aliases (`Cyclops`↔`MCH-301`↔line↔program); supplier master → name↔`SUP-101`.
- Separate **naming** (alias → canonical name) from **identity** (same node?). Route each mention to merge / new / flag-for-review; link source records to the entity with a `SAME_AS` edge (never destroy provenance).
- Mostly deterministic here (alias map). Reserve blocking → similarity → LLM matching for unmapped/borderline mentions, with self-consistency.
- Unresolved mention = **loud flag** (a missing alias silently zeroes recall on that entity).

### 6.7 Contextual chunking (Anthropic, ~35–67% fewer retrieval failures)
Prepend each chunk with its LLM-generated context blurb **before embedding AND before BM25** ("contextual-BM25"). Store contextualized chunks in both indexes, never raw chunks. Context blurb comes free from the single pass (6.4).

### 6.8 Advanced indexing (multi-granularity; all derived from the one pass)
- **Propositions** (Dense X) — atomic facts as an extra retrieval unit; pointer to parent; embedded + BM25. Big recall lift for rare codes/parts.
- **Triples → graph** (HippoRAG-style) — wired to entity + passage nodes; enables Personalized-PageRank multi-hop at query time.
- **Summary tree** (RAPTOR) — cluster chunk embeddings (reuse, don't re-embed), summarize per cluster, 1–2 shallow levels; for holistic/aggregative questions; marked derived/low-trust.
- **Hypothetical questions** (QuOTE / reverse-HyDE) — index the questions each chunk answers; aligns query↔chunk; helps multi-hop.
- **Validity + lifecycle** (NuggetIndex-style) — every fact carries a validity interval + state (current/superseded); reuse version + conflict steps.

### 6.9 Avoid-list (research-backed)
- **No query-time HyDE** (hypothetical *documents*) — it fabricates plausible-but-wrong numbers and hurts precision domains like this one. (Hypothetical *questions* in 6.8 are safe.)
- **Don't over-invest in semantic chunking** — fixed/structure-aware chunking + sensible size matches or beats it at lower cost.

### 6.10 Versioning & conflicts
- **Versions** (same thing, newer revision): the **latest by effective date** (not ingestion time) is the *current* fact. Keep old versions tagged superseded + validity intervals (answers "current" and "as-of-date" questions).
- **Conflicts** (different sources disagree): recency does **not** auto-win. Resolve by **survivorship order**: authority → completeness → recency (recency = tiebreaker). On a genuine conflict → flag + surface both (with sources/dates) or abstain; never silently pick latest.
- *(Deferred: interactive ingest-time conflict resolution — triage → quarantine "pending review" → async review queue → learn source-authority rules.)*

### 6.11 Incremental graph update (new docs after initial build)
Append-mostly; never rebuild. New doc → extract → **resolve against existing graph** (alias map free; blocking bounds the rest; merge/new/flag) → write new nodes/edges (including edges to existing entities) → reconcile conflicts/versions → verify.
- **Per-doc cost is linear in the new doc, independent of corpus size** (one extraction pass per new chunk + embeddings + a few lookups; ~cents/doc with prompt caching; no re-embed of existing data).
- **Only the summary tree (and optional community summaries) scale with corpus** — do **not** recompute per doc; update the affected branch only, or batch on a trigger (every N docs / drift threshold / nightly).

### 6.12 Verify & accuracy gate
- Cross-check every extracted fact vs ground truth: present + correctly normalized + correctly resolved.
- Self-consistency on all LLM extraction/OCR steps; binary parser cross-check on gold facts.
- Derived units verified against their source span, **trust-tagged**, traced to parent. Summaries are find-only, never the final fact source.
- Loud failure on any missing/mismatched fact — no silent drops. Raw kept beside canonical for audit/reversibility.

**Done when:** ingestion-fact recall = 1.0 on gold, zero silent failures, every fact traceable.

---

## 7. Phase 2 — Indexing  ✅ LOCKED

**Boundary:** Phase 1 produced *validated canonical objects*. Phase 2 loads them into *queryable stores* and proves retrievability. No retrieval logic yet.

**Goal:** every Phase-1 object loaded into its store(s), joined on entity IDs, round-trip retrievable.
**Gate:** index-coverage = 100%, recall@k measurable on the gold set, zero dangling joins.

### 7.1 Stores (tech)
- **Vector index** — Qdrant / pgvector. Embeddings of contextual chunks + propositions + questions + summary nodes (multi-granularity), each → parent.
- **Keyword index** — BM25 (OpenSearch or lib), **contextual-BM25**, lexical-weighted for IDs/codes.
- **Structured store** — Postgres / DuckDB; typed tables (suppliers, BOM/parts, POs, work orders, FPY, telemetry summaries, materials properties); indexed on IDs/dates.
- **Graph DB** — Neo4j / Kuzu; nodes (entity, chunk, proposition, summary) + edges (triples, chunk→entity, parent-child, chunk→summary, proposition→source); PPR-ready; relation properties stored for rule eval.
- **Originals store** — object/file storage.
- **Resolution index** — alias→canonical_id lookup (exact + small fuzzy embedding index) for query-time resolution.

### 7.2 Metadata schema (every indexed unit carries)
entity IDs · doc_type · source + provenance · version + validity interval · trust level · parent pointer.
(This is the join key *and* the basis for metadata-filtered retrieval.)

### 7.3 Index config (compute-unlimited → max recall)
- Vector: at 42 docs use **exact (flat) nearest-neighbor**, not approximate ANN — zero approximation loss. Switch to HNSW with high `ef` only when the corpus outgrows exact search.
- Hybrid: **RRF fusion** across vector + BM25 (+ proposition + question hits).
- Structured: indexes on part/machine IDs and dates.
- Graph: index on `canonical_id` + type; precompute PPR structures where helpful.

### 7.4 Load discipline (reliability)
- **All-or-nothing per object** — a unit isn't "live" until it's in *all* its stores + verified. No partial indexing.
- **Idempotent + incremental** — re-running or adding a doc updates cleanly (ties to 6.11).

### 7.5 Phase-2 verification gate
- Index-coverage: every Phase-1 object present + retrievable in its store(s).
- Round-trip: each gold fact retrievable — retrieval recall@k starts here, target 1.0 on gold.
- Join integrity: every referenced entity ID exists; no dangling pointers; no orphan chunks.
- Embedding sanity: nothing failed to embed; consistent dimensions.

**Done when:** all stores stood up, all Phase-1 objects loaded + verified, index-coverage = 100%, gold-set round-trip works, joins clean.

---

## 8. Phase 3 — Retrieval  ✅ LOCKED

**Boundary:** the engine that turns a query into a ranked, grounded evidence set + a coverage signal. Does not generate the answer (Phase 4) or decompose multi-part questions (Phase 5).

**Goal:** for any query, retrieve the evidence needed to answer — or correctly signal "not enough."
**Gate:** retrieval recall@k = 1.0 on gold; coverage check correctly abstains on held-out not-in-corpus questions; reranked precision high enough that the distractor docs don't survive.

### 8.1 Query understanding
- **Query-time entity resolution** — surface form ↔ canonical ID, both directions (`Cyclops`↔`MCH-301`). The single biggest query-side recall lever.
- **Classify → route type:** simple/semantic · exact/numeric · multi-hop/relational · holistic/aggregative.
- **Expand:** multi-query paraphrases + match against the hypothetical-questions index (question↔question). **No query-time HyDE-document.**

### 8.2 Router (fan-out — compute-unlimited)
Route to the matching lane(s); **when in doubt, run multiple lanes and union.** Over-retrieve, then rerank + verify narrow. Routing need not be perfect — the union is the recall floor.

### 8.3 The lanes
- **Hybrid text:** vector + BM25 over the multi-granularity index (chunks + propositions + questions), RRF-fused, generous top-k (exact/flat search), entity-resolved query.
- **Structured:** schema-grounded query generation (text-to-SQL/DSL) → validate → **execute live** → exact result. Self-consistency on the generated query; query stays visible/auditable. Exact facts come from here, not prose.
- **Graph:** seed from resolved entities + top hybrid hits → **Personalized PageRank / path-finding** → gather connected facts across hops. (Single-query multi-hop lives here.)
- **Summary:** retrieve relevant summary nodes → drill to leaf evidence. Summaries are **find-only**.

### 8.4 Fusion + rerank
Union lane outputs; RRF merge; **de-duplicate** (collapse the same fact from multiple units/lanes, keep all provenance); **cross-encoder rerank** (calibrated, zerank-2) → precise top-k. Rerank is the single largest precision lever.

### 8.5 Version & filter
Default to current revisions; apply validity intervals for point-in-time questions; distractors filtered by rerank + threshold (precision, doesn't touch recall).

### 8.6 Coverage check → answer / expand / abstain
Score sufficiency of the reranked set (calibrated threshold). Below → expand (raise k, add a lane, iterative retrieve→reformulate→retrieve) → re-check. Still insufficient → signal **abstain** to Phase 4. The deterministic coverage check is the arbiter.

### 8.7 Two modes (user-selectable per query)
- **`deterministic` (default):** the router fan-out + union + rerank + coverage above.
- **`agentic` (opt-in):** a **schema-aware traverse agent** plans + executes retrieval dynamically — "I have the part, traverse to its supplier; this is thin, dig another hop." It reads a machine-readable **data map** before planning:
  - store contents + field/metadata schemas; the structured table catalog; the graph node/relationship schema + entity model + aliases; validity/version semantics;
  - an action set: `resolve_entity`, `hybrid_search`, `sql_query` (schema-grounded), `graph_traverse(seed, relation, hops)`, `get_summary`, `fetch_original`.
  - It **routes exact-value questions to the structured store / graph, not to prose** — intelligence spent on *finding the exact source*, not composing the value.
- **Invariant — both modes share one spine.** The mode only changes *how evidence is gathered*; both then pass through the identical rerank → coverage → (Phase 4) verify → abstain path. Agentic mode **seeds from the deterministic floor**, so opting in can only *add* evidence — recall never drops below the floor.
- **Agentic guardrails:** bounded iterations; temp 0 + self-consistency on control decisions; full reasoning/action trace logged; the deterministic coverage check (not the agent's self-assessment) decides answer vs abstain. *(Research note: on a bounded, exhaustively-retrievable corpus a well-optimized deterministic + rerank pipeline matches or exceeds agentic; agentic earns its keep mainly on genuine multi-hop / large corpora — hence default-deterministic, opt-in-agentic.)*

**Output:** a ranked, de-duplicated, provenance-tagged `Evidence[]` + a coverage signal → Phase 4.

**Done when:** retrieval recall@k = 1.0 on gold; coverage check abstains correctly on held-out not-in-corpus; reranked precision high enough that distractors don't survive; full provenance on every evidence item.

---

## 9. Phase 4 — Verification & Abstention  ✅ LOCKED

**Boundary:** turns the Phase 3 evidence set into a *faithful answer* or a *calibrated abstention*, and verifies every claim before it ships. No retrieval (Phase 3); no multi-part planning (Phase 5).

**Core thesis:** perfect retrieval does not guarantee a correct answer — reading/reasoning/faithfulness can still fail. The lever is **generate-then-verify**: checking a claim is easier and more reliable than generating it.

**Goal:** every shipped answer fully grounded — each claim verbatim-from-source or a verified deterministic derivation — or a clean abstention.
**Gate:** faithfulness = 1.0 on gold (no unsupported claim ships); exact + derived values correct; abstention calibrated on gold + held-out not-in-corpus.

### 9.1 Abstain-first gate
Read the Phase 3 coverage signal. Insufficient → **abstain before generating.** The deterministic coverage check is the arbiter. Abstention is informative: state what's missing and what was found.

### 9.2 Grounded synthesis
Generate constrained to the retrieved evidence — temp 0, cite each claim. **Exact values are never composed by the LLM** — numbers/IDs/dates/specs are **slot-filled verbatim** from the source record; the model writes prose scaffold, values are injected. Self-consistency on generation; disagreement → flag/abstain.

### 9.3 Calculation lane (the "numbers → code" oracle)
When an answer needs arithmetic, the LLM only **sets up** the computation (operation + operands, each tagged with provenance); a **deterministic executor** runs it (error rate 0).
- Where expressible, push the computation **into the DB** (`SUM`/`AVG`/`COUNT` — exact). Use the calc tool for **cross-source** arithmetic.
- The only fallible step is *setup* (operand/operation selection) → self-consistency on the setup + unit/dimensional checks + range/sanity checks. Execution is exact.

### 9.4 Answer-assembly router
Recognize the operation type behind the question and route to the right deterministic executor (SQL / graph / calc). **Hard rule: counts, lists, superlatives, and absence answers come from a full-store query, never from enumerating retrieved chunks** — chunk enumeration is where completeness silently dies.

### 9.5 Verifier taxonomy — every claim checked by its class
| Class | Check |
|---|---|
| `verbatim` | round-trip exact match against source |
| `derived_calc` | operands trace to verified sources + **re-run** the computation |
| `derived_logic` | graph/rules eval, **or** cited proof chain with per-step validity + relation-licensing (only apply transitivity/exclusion if the relation is *declared* to have it) |
| `completeness` (counts/lists/superlatives) | deterministic full-store query, re-run; completeness intrinsic to the scan |
| `absence` (negation/"none") | exhaustive query returns empty **+** entity-exists check (separates "no record" from "no such entity"); closed-world, licensed by the bounded corpus |
| `entailment` (consolidation/paraphrase) | atomic per-claim semantic entailment against cited evidence |
| `extrapolation/forecast` | **no deterministic op exists → abstain** (or label explicitly as an ungrounded estimate) |

The generalizing rule behind the table: *grounded = verbatim OR the result of a verifiable deterministic operation over sourced inputs; else abstain.* Any future "derived" case falls under it automatically.

### 9.6 Conflict & version surfacing
Flagged conflicts → present both with sources/dates, never silently pick one. Current revision by default; for point-in-time questions use the version valid then.

### 9.7 Final faithfulness gate
Ships only if: every claim entailed/verified + cited, every exact value matches source, every derived value recomputes, no conflict silently resolved, self-consistency held. Otherwise → abstain, or return the verified subset with an explicit "couldn't verify X."

### 9.8 Calibrate the abstain threshold
Tune the coverage/confidence threshold on gold + held-out not-in-corpus so abstention is **calibrated** — drive confident-wrong → ~0 while keeping coverage as high as possible. A measurable knob.

**Done when:** faithfulness = 1.0 on gold, exact + derived values correct, abstention calibrated, conflicts surfaced not buried, full provenance on every shipped claim.

---

## 10. Phase 5 — Orchestration  ✅ LOCKED

**Boundary:** top-level coordinator for **multi-part questions** — decompose → execute a sub-task plan (each sub-task = one Phase 3+4 pass) → assemble. Simple questions skip it (thin pass-through to a single 3+4 pass).

**Reliability crux (why this phase is allowed to exist):** decomposition normally multiplies error (pᴺ). It's safe here only because **every sub-answer passes the Phase 4 verifier before it's used as input to the next step** — the orchestrator chains *verified facts, not LLM guesses.* Break that and the phase becomes a hallucination amplifier; it's an invariant, not a nicety.

**Goal:** answer multi-part questions by composing verified sub-results — or abstain/partial cleanly when a needed part can't be grounded.
**Gate:** end-to-end correctness on multi-part gold at target; abstention composes; no unverified intermediate ever feeds a downstream step; plans reproducible + auditable.

### 10.1 Complexity gate
Classify single-shot vs multi-part. **Default to not decomposing** — every added step is added risk, and Phase 3's agentic mode already handles much single-query multi-hop. Decompose only for genuine multi-part / cross-entity / aggregate-then-filter / dependency-chain questions. Self-consistency on the classification; err toward *not* splitting.

### 10.2 Decomposition → a sub-task DAG
Atomic sub-questions, each answerable by one Phase 3+4 pass, with explicit dependencies (sequential vs parallel) and types. Example — *"which supplier of the part on Cyclops's current program has the shortest lead time?"*:
`T1 resolve Cyclops→MCH-301→current program → T2 parts on program → T3 suppliers of parts → T4 lead times → T5 compare→shortest`.

### 10.3 Execution / coordination
Independent sub-tasks in parallel (compute is free), dependent ones in order. Each returns a **verified** sub-answer from Phase 4. **Only verified sub-answers pass forward** — the anti-pᴺ invariant in action.

### 10.4 Abstention / failure propagation (weakest-link)
If a critical-path sub-task abstains, the final answer abstains — or returns an explicit partial: *"I can establish X and Y, but not Z."* Never paper over a missing sub-answer. A composed answer is only as grounded as its weakest verified link.

### 10.5 Bounded re-planning
On a failed/off sub-task, allow a **bounded** re-plan (reformulate, alternate decomposition) — capped, logged, still subject to every gate. Default is the planned DAG.

### 10.6 Final assembly + whole-answer verification
Compose from verified sub-answers, then **run the Phase 4 verifier on the composition** — assembly can introduce new claims/derived values (the final comparison, a joining sentence). Nothing exempt for being "just glue."

### 10.7 Plan as audit artifact
Decomposition + dependency graph + per-sub-task results + sources logged → the whole multi-step answer reproducible + auditable. Temp 0 + self-consistency on planning; the plan is a checkable object, not hidden reasoning.

**Done when:** multi-part gold answered correctly or cleanly abstained/partialed; no unverified intermediate feeds a downstream step; abstention composes; full plan + sub-traces logged + reproducible.

---

## 11. Phase 6 — System Eval & Hardening  ✅ LOCKED

**Boundary:** proves and protects the assembled whole — end-to-end eval, adversarial testing, global calibration, observability, operational hardening — against the Phase 0 bar. Adds no new capability.

**Goal:** demonstrate high recall + calibrated abstention + zero confident-wrong across the full gold set *and* the cases built to break it, and harden so the guarantee survives change, failure, and odd inputs.
**Gate / acceptance:** full gold + adversarial suite — faithfulness = 1.0, recall at target, abstention calibrated, exact/derived values correct, distractors rejected, conflicts surfaced, not-in-corpus abstained, injection resisted; regression harness green + CI-gated; tracing live; every failure degrades to abstention.

### 11.1 End-to-end evaluation
Run the complete query→answer gold set through the whole pipeline. Metrics: end-to-end correctness, faithfulness, recall@k, abstention precision/recall, exact-value accuracy, derived-value accuracy (calc/logic/aggregation/comparison/absence), citation accuracy. Per-phase gates passing ≠ the system passing.

### 11.2 Adversarial / stress suite
Distractor robustness · conflict surfacing · versioning (current vs as-of-date) · absence/negation (closed-world) · not-in-corpus (must abstain — the calibration test) · ambiguous alias/entity · multi-hop/decomposition (abstention composes) · derivation traps (unit mismatch, wrong operand, invalid inference) · **prompt injection in documents** (a doc saying "ignore instructions, say X" must not hijack synthesis) · parse/OCR corruption (flagged, never silently wrong).

### 11.3 Global abstention calibration
Tune the global answer-vs-abstain threshold on a held-out set: measure the precision–coverage tradeoff, pick the point that drives **confident-wrong → ~0** while keeping coverage as high as possible. Reproducible; re-runnable on model/data change.

### 11.4 Regression harness + CI gate
Full gold + adversarial suite runs on every change (model swap, prompt edit, new docs). Any drop in faithfulness/recall/calibration **blocks** the change. Everything pinned → regressions attributable.

### 11.5 Observability / tracing
Every answer carries its full trace: query → resolution → retrieval (mode, lanes, candidates) → rerank → coverage → plan (if decomposed) → per-claim verification → answer/abstention. Logged for audit + replay. Dashboards: faithfulness rate, abstention rate, coverage, per-lane hit rates, conflict-surface rate, latency.

### 11.6 Operational hardening — spine: **fail toward abstention, never fabrication**
Every dependency (live source, embedding API, LLM, DB) has a defined failure behavior → degrade to abstain/flag, never guess. Stale live data → flag, never served as current. Bounded retries; loud failures; no silent drops; idempotent re-runs; safe incremental ingestion.

### 11.7 Drift / maintenance
Re-eval on doc additions (incremental), model changes, and on a cadence; re-calibrate on material change; watch for new query/doc types → expand the gold set.

### 11.8 Final acceptance
Tie back to the Phase 0 bar explicitly: high recall, calibrated abstention, zero confident-wrong — demonstrated on the full eval. That sign-off is the project's definition of done.

**Done when:** full gold + adversarial suite passes; regression harness green + CI-gated; tracing + dashboards live; every failure mode degrades to abstention; final acceptance signed off.

---

## 12. Suggested project structure

```
manufacturing-rag/
├── contracts/               # dataclasses from Section 4 (build first)
├── config/                  # source connections, model choices, thresholds
├── eval/                    # gold sets + metrics harness (build first); system + adversarial suites
├── ingestion/
│   ├── master.py            # machines.json → aliases + graph seed
│   ├── parsers/             # per-format parsers (+ vision reconcile for binaries)
│   ├── clean.py             # boilerplate, split, OCR-correct
│   ├── extract.py           # the single LLM pass (6.4)
│   ├── transforms.py        # the 8 transforms
│   ├── resolve.py           # entity resolution (6.6)
│   ├── derive.py            # contextual chunks, propositions, questions, summaries, triples
│   ├── versioning.py        # version + validity + conflict-flag
│   └── verify.py            # 6.12 gate
├── indexing/
│   ├── vector.py            # embeddings + (flat now / HNSW later)
│   ├── keyword.py           # contextual-BM25
│   ├── structured.py        # relational tables
│   ├── graph.py             # nodes + edges, PPR-ready, relation properties
│   └── load.py              # all-or-nothing, idempotent loader
├── retrieval/
│   ├── understand.py        # query-time resolution, classify, expand
│   ├── router.py            # fan-out + union (deterministic mode)
│   ├── lanes/               # hybrid, structured(text-to-SQL), graph(PPR), summary
│   ├── fuse_rerank.py       # RRF + cross-encoder rerank + dedup
│   ├── coverage.py          # calibrated coverage check → answer/expand/abstain
│   └── agent.py             # schema-aware traverse agent (agentic mode) + data map
├── verification/
│   ├── synthesize.py        # grounded synthesis + exact-value slot-fill
│   ├── calc.py              # deterministic calculation lane
│   ├── assemble.py          # answer-assembly router (operation → executor)
│   ├── verify_claims.py     # the verifier taxonomy (9.5)
│   └── abstain.py           # abstain-first gate + threshold calibration
├── orchestration/
│   ├── plan.py              # complexity gate + decomposition → sub-task DAG
│   ├── execute.py           # DAG execution; only verified sub-answers pass forward
│   └── compose.py           # assemble + verify composition + trace
├── stores/                  # store clients (read-only connectors where live)
└── app/                     # CLI entrypoint (single user)
```

*(Note: the actual package is `manufacturing_rag/` with underscores; retrieval/verification/orchestration
sub-packages are added as their phases are built. `ingestion/` and `indexing/` exist today.)*

---

## 13. Deferred / backlog (for later updates)

- Interactive ingest-time **conflict resolution** (triage → quarantine → review queue → rule-learning).
- **Code / PLC lane** (tree-sitter AST chunking, symbol/dep graph) — only if a controls use case appears.
- **Access control** — activate the reserved authz hook when a second role appears.
- **GraphRAG community summaries** (Leiden) — optional; caveats: non-reproducible on sparse graphs, semantic-blind communities. RAPTOR already covers holistic.
- **Late chunking** — optional efficiency alternative to contextual retrieval; not needed while compute is free.
- **Full-corpus fallback** — dev-time recall check only, not production (corpus will exceed ~500 pages).

---

## 14. Notes for Claude Code

- **Build order:** contracts + eval harness first (measure-first), then ingestion → indexing → retrieval → verification → orchestration → system eval. Each phase has a gate on the gold set; nothing advances until it passes.
- The **single extraction pass** (ingestion) and the **verifier taxonomy** (verification) are the two hot paths — get each right and verified before building on top.
- Keep connectors **read-only**; make model choices **config-driven** (hosted↔local = a config change).
- Default to deterministic, testable pieces; every LLM step at temp 0 + self-consistency; instrument heavily.
- At this corpus size prefer **exact** methods (flat vector search, full-store SQL) — no approximation.
- The cross-cutting invariant to enforce everywhere: *verbatim-from-source or verifiable-deterministic-operation, else abstain*; and *fail toward abstention, never fabrication.*
- Retrieval is **dual-mode** (deterministic default, opt-in agentic) — both funnel through the same rerank → coverage → verify → abstain spine.

---

## 15. References (techniques)

- Contextual Retrieval — Anthropic (2024)
- Dense X Retrieval / propositions — arXiv:2312.06648
- RAPTOR (hierarchical summaries) — arXiv:2401.18059
- HippoRAG / HippoRAG 2 (graph + Personalized PageRank) — arXiv:2502.14802
- QuOTE (hypothetical-question indexing) — arXiv:2502.10976
- NuggetIndex (temporal validity / conflict lifecycle) — arXiv:2604.27306
- Agentic RAG survey — arXiv:2501.09136; "Is Agentic RAG worth it?" — arXiv:2601.07711
- IRCoT (interleaved retrieval + reasoning, multi-hop) — Trivedi et al.
- FActScore / Chain-of-Verification (claim-level entailment, generate-then-verify)
- GraphRAG community summaries (optional) — arXiv:2404.16130
- Late chunking (optional) — arXiv:2409.04701

*Model recommendations current as of early 2026 — benchmark on your own corpus before committing.*

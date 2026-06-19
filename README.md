# RAG Golden Dataset — Helios Plant 7 (Synthetic Manufacturing World)

A "golden dataset" for stress-testing a Retrieval-Augmented Generation (RAG)
system for the manufacturing domain. Everything is synthetic but forms **one
internally consistent factory world** so that multi-hop questions actually
resolve against the corpus. Built with the Python 3 standard library only
(`json`, `csv`, `pathlib`) — no network access, no third-party packages.

All standards/compliance text is **fully synthetic and paraphrased**; no real
ISO/ASTM/ANSI wording is reproduced.

## Files

| File | What it is |
|------|------------|
| `build_dataset.py` | Generator. Holds the entity graph + all docs/questions as Python literals and emits the three data files. Re-run to regenerate deterministically. |
| `corpus.jsonl` | 42 knowledge-base documents (one JSON object per line) — the **clean canonical target** an ingestion pipeline should approximate. |
| `questions.jsonl` | 72 labelled evaluation questions (one JSON object per line). |
| `questions.csv` | Flat, human-browsable view of the question bank (list fields joined with `;`). |
| `validate.py` | Integrity harness for the clean dataset. |
| `build_raw.py` | Generator for the **raw, pre-ingestion** source tree (messy real-world formats). Emits `raw/` + its ground-truth manifest. |
| `raw/` | 28 raw source files in mixed dirty formats (CSV/HTML/TXT/EML/JSON + real PDF/XLSX/DOCX) — the **input to your ingestion pipeline**. |
| `raw/INGESTION_GROUND_TRUTH.jsonl` | Maps each raw file → canonical doc_id(s) + facts to recover + planted "mess challenges". The scoring key for ingestion. |
| `validate_raw.py` | Integrity harness for the raw layer (manifest ↔ disk ↔ corpus; binary-format validity; encoding trap). |
| `README.md` | This file. |

## The two layers

```
raw/  --[ YOUR INGESTION PIPELINE ]-->  ~corpus.jsonl  --[ retrieve + generate ]-->  answer questions.jsonl
 ^ messy real-world inputs               ^ clean canonical target                     ^ end-to-end eval
 (test ingestion here)                   (compare extraction against this)            (test retrieval+generation here)
```

- **Testing ingestion from scratch?** Start at `raw/`, build your pipeline, and
  score its output against `corpus.jsonl` using `raw/INGESTION_GROUND_TRUTH.jsonl`.
- **Testing retrieval/generation only?** Use the clean `corpus.jsonl` directly.

## How to run

```bash
python build_dataset.py   # (re)generate corpus.jsonl, questions.jsonl, questions.csv
python validate.py        # validate the clean dataset; exits non-zero on failure

python build_raw.py       # (re)generate the raw/ ingestion test bed + manifest
python validate_raw.py    # validate the raw layer; exits non-zero on failure
```

Each validator exits `0` and prints `ALL ... PASSED.` on success, or exits `1`
with a list of errors. Both generators are deterministic (`random.seed(7)`).

---

## The factory world (entity graph)

```
Suppliers  SUP-101..105  --supply-->  Parts PRT-2001..2007  --used on-->  Machines
                                                                           |
  MCH-301 "Cyclops" (CNC lathe)   MCH-302 "Hydra" (injection molder)       |
  MCH-303 "Goliath" (CNC mill)    MCH-304 "Atlas" (assembly robot)  <------+
                                                                           |
Lines:  Line A "PEGASUS" -> program "BLUEBIRD"   (Cyclops + Goliath)       |
        Line B "KRAKEN"  -> program "REDFOX"     (Hydra)            <------+
        Line C "TITAN-LINE" (final assembly)     (Atlas)
```

Shop-floor jargon: **"the squeeze"** = injection molding · **"the dog house"** =
QA hold/quarantine area · **"first-off"** = first-article inspection ·
**"the lathe cell"** = the MCH-301 area.
Acronyms used: **OEE, MTBF, FPY, NCR, LOTO, MOQ**.

---

## Schema — `corpus.jsonl`

One JSON object per line:

```json
{
  "doc_id":   "SPEC-2001",
  "doc_type": "part_spec",
  "title":    "Part Specification — PRT-2001 Drive Shaft",
  "text":     "PRT-2001 Drive Shaft. Material: 4140 alloy steel ...",
  "metadata": { "part_id": "PRT-2001", "supplier_id": "SUP-101",
                "used_on": ["MCH-301"], "source": "PLM", ... }
}
```

- `doc_id` — unique document identifier; this is what `gold_doc_ids` references.
- `doc_type` — one of: `supplier`, `part_spec`, `sop`, `work_order`, `ncr`,
  `quality_report`, `standard`, `purchase_order`, `material_datasheet`,
  `telemetry`, `troubleshooting`, `incident`, `noise`.
- `title` — short human title.
- `text` — the retrievable body (the chunk an embedder would see).
- `metadata` — entity refs (`supplier_id`, `part_id`, `machine_id`, `line`,
  `program`), dates, `version`/`status`/`supersedes`/`superseded_by`,
  `effective_date`, `source`, and type-specific numeric fields.

### Document inventory by type

| doc_type | count | doc_ids |
|----------|-------|---------|
| supplier | 5 | SUP-101 … SUP-105 |
| part_spec | 7 | SPEC-2001 … SPEC-2007 |
| sop | 4 | SOP-001-v1, SOP-001-v2, SOP-010, SOP-020 |
| work_order | 4 | WO-5001 … WO-5004 |
| ncr | 3 | NCR-7001, NCR-7002, NCR-7004 |
| quality_report | 1 | QR-7003 |
| standard | 3 | STD-IS-900, STD-TQ-450, STD-SF-200 |
| purchase_order | 3 | PO-9001 … PO-9003 |
| material_datasheet | 3 | MAT-4140, MAT-PA66, MAT-AL6061 |
| telemetry | 2 | TEL-301, TEL-302 |
| troubleshooting | 2 | TG-001, TG-002 |
| incident | 2 | INC-8001, INC-8002 |
| noise | 3 | NOISE-001, NOISE-002, NOISE-003 |

## Schema — `questions.jsonl` / `questions.csv`

```json
{
  "qid": "Q007",
  "question": "What is the lead time of the supplier that provides the bearing used on the Cyclops lathe?",
  "category": "multi_hop",
  "difficulty": "hard",
  "persona": "procurement",
  "answerable": true,
  "gold_doc_ids": ["SPEC-2003", "SUP-103"],
  "reference_answer": "45 days. Cyclops is MCH-301 -> bearing PRT-2003 -> Vector Bearings (SUP-103) -> 45 days.",
  "eval_notes": "3-hop: machine codename -> part -> supplier -> lead time."
}
```

- `difficulty` ∈ `{easy, medium, hard}`; `persona` ∈ `{design_engineer,
  procurement, quality, maintenance, plant_manager}`.
- `gold_doc_ids` — exact, verifiable supporting-evidence doc_ids. Empty `[]` for
  unanswerable / ambiguous / out-of-scope questions **and** for
  `high_level_synthesis` (whose answer lives in no single document).
- `reference_answer` — the correct answer, or an explicit "Not in the knowledge
  base" / "Out of scope" / "Ambiguous — clarification needed" statement.
- In `questions.csv`, `gold_doc_ids` is rendered as a `;`-joined string and
  `answerable` as `true`/`false`.

---

## Category taxonomy (17 categories)

| Category | One-line definition |
|----------|---------------------|
| `single_fact` | Answer is a single value in one document. |
| `multi_hop` | Requires chaining 2–3+ documents through the entity graph. |
| `aggregation_count` | Count/aggregate entities across several documents. |
| `comparison` | Compare two values/entities and pick one. |
| `numeric_calculation` | Arithmetic over retrieved numbers (sum, product, cost). |
| `unit_conversion` | Convert retrieved values between units (mm↔in, Nm↔ft·lb, g/cm³↔kg/m³). |
| `temporal_versioned` | Reason about dates / which revision is current. |
| `conflict_resolution` | Two sources disagree; return the correct/current value or flag the conflict. |
| `unanswerable` | The fact is genuinely absent from the corpus → must refuse, not hallucinate. |
| `jargon_codename_acronym` | Resolve internal codenames, shop-floor jargon, or acronyms. |
| `tabular_reasoning` | Read/filter/aggregate a literal table in document text. |
| `procedural_stepwise` | Return an ordered procedure from an SOP/guide. |
| `constraint_filtering` | Filter a set by a numeric/categorical constraint. |
| `ambiguous_needs_clarification` | Under-specified; correct behavior is to ask for clarification. |
| `out_of_scope_rejection` | Off-topic for a manufacturing KB; should be refused/redirected. |
| `high_level_synthesis` | Synthesize across many docs; answer is in no single doc (`gold_doc_ids: []`). |
| `entity_disambiguation` | Resolve a name collision between distinct entities. |

---

## Planted edge cases (and where they live)

| Edge case | Where | Notes |
|-----------|-------|-------|
| **Conflicting / versioned facts** | `SOP-001-v1` (85 Nm, superseded) vs `SOP-001-v2` (95 Nm, current) | Resolvable via `status`/`supersedes`/`effective_date`. Current value = **95 Nm**. Tested by Q033, Q034, Q036, Q025, Q029–Q031. |
| **Near-duplicate records** | `NCR-7001` (12 units) vs `NCR-7004` (21 units) | Identical except the `units_affected` field; `NCR-7004` carries a `data_quality_flag`. Tested by Q035 (and counted in Q015). |
| **Real data table** | `QR-7003` (FPY by line), `TEL-301` (OEE breakdown) | Markdown pipe tables embedded in `text`. Tested by Q048–Q051, Q050. |
| **Codenames / jargon / acronyms** | Throughout: PEGASUS/KRAKEN/TITAN-LINE, BLUEBIRD/REDFOX, Cyclops/Hydra/Goliath/Atlas; "the squeeze", "the dog house"; OEE/MTBF/FPY/NCR/LOTO | Tested by Q043–Q047. |
| **Intentionally absent facts** | (no doc) | Warranty terms (Q037), 4140 melting point (Q038 — `MAT-4140` lists mechanical props only), MCH-304 OEE (Q039), PRT-2002 price (Q040), MCH-302 MTBF (Q041), supplier CEO names (Q042). |
| **Entity name collisions** | `SUP-101` "Titan Alloys" vs Line C "TITAN-LINE"; `MCH-304` "Atlas" (assumed supplier); "Vector" Bearings vs Lumen sensors | Tested by Q070–Q072. |
| **Off-topic noise** | `NOISE-001` (cafeteria menu), `NOISE-002` (parking memo), `NOISE-003` (holiday schedule) | Precision/distractor docs; targets of out-of-scope/precision testing. |

---

## Raw ingestion test bed (`raw/`)

These 28 files mirror what a real plant actually emits — heterogeneous formats,
dirty fields, and the kind of mess that breaks naive ingestion. They carry the
**same facts** as the canonical corpus, dirtied. Build your ingestion pipeline
against these and compare its output to `corpus.jsonl`.

### Source formats (forces real format handling)
| Format | Files | Examples | What it exercises |
|--------|-------|----------|-------------------|
| CSV | 6 | `erp/suppliers_master.csv`, `maintenance/cmms_export.csv` | delimited parsing, dirty fields |
| HTML | 4 | `sops/SOP-001_rev1.html`, `kb/troubleshooting.html` | tag stripping, boilerplate removal, list-order preservation |
| TXT | 9 | shift logs, standards, datasheets, incidents, noise | free-text + entity extraction |
| TXT (OCR) | 2 | `quality/NCR-7001_scan.txt` | OCR-noise correction |
| EML | 2 | `quality/ncr7002_email.eml`, `email/vector_bearings_quote.eml` | header/quote/signature stripping |
| JSON | 1 | `mes/machines.json` | structured API payload (the codename graph) |
| **PDF (real binary)** | 1 | `standards/HX-900_excerpt.pdf` | PDF text extraction + header/footer stripping |
| **XLSX (real binary)** | 1 | `quality/Q1_2025_FPY.xlsx` | spreadsheet parsing + table extraction |
| **DOCX (real binary)** | 1 | `sops/SOP-001_Rev2.docx` | Word-doc parsing |

The PDF/XLSX/DOCX are genuine OOXML/PDF binaries (built with stdlib `zipfile` /
hand-rolled PDF) — your pipeline needs *real* parsers for them, not a text read.

### Planted "mess challenges" (what your ingestion must survive)
Each is recorded per-file in `raw/INGESTION_GROUND_TRUTH.jsonl` under
`mess_challenges`. Highlights:

- **Encoding** — `suppliers_master.csv` has a UTF-8 BOM; `vector_bearings_quote.eml`
  is **cp1252** (decoding it as UTF-8 corrupts it — an explicit detection trap).
- **Inconsistent units** — downtime appears as `4.5h` / `360 min` / `3:00` /
  `1h30m` (`cmms_export.csv`); lead time as `days` vs `weeks`; dimensions carry
  units inside the value (`250 mm`).
- **Inconsistent formats** — dates as ISO vs `mm/dd/yyyy`; currency as `$42.50`
  vs `USD 115.00` vs `0.35 USD`; numbers with thousands separators (`5,000`).
- **Reference-by-name vs by-ID** — POs/BOM reference suppliers by name
  (`Titan Alloys`) that must be resolved to `SUP-101`.
- **Duplicates** — a duplicate supplier row (`SUP-104`) differing in one field;
  the near-duplicate NCR pair (`NCR-7001` 12 units vs `NCR-7004` 21 units).
- **Multiple docs per file** — `materials/PA66_AL6061_datasheets.txt` (2 datasheets)
  and `kb/troubleshooting.html` (TG-001 + TG-002) must be **split**.
- **Aggregate-on-ingest** — `telemetry/MCH-301_vibration_2025-05.csv` (96 raw
  samples → mean 3.2 mm/s) and `oee_daily_may2025.csv` (daily components → monthly
  OEE 82.3% / 76.5%, where OEE = A×P×Q).
- **Boilerplate** — HTML nav/footers; PDF running header/footer + page numbers;
  leftover page-number artifacts in extracted-text standards.
- **Version sprawl across systems** — SOP-001 Rev 1 lives in **HTML** (superseded,
  85 Nm) while Rev 2 lives in **DOCX** (current, 95 Nm). Conflict resolution must
  work *across formats and systems*, using the supersession metadata.
- **Deliberate absence** — `4140_steel_datasheet.txt` lists mechanical properties
  only (no melting point), preserving the unanswerable-question test post-ingestion.

### Manifest schema — `raw/INGESTION_GROUND_TRUTH.jsonl`
```json
{
  "source_file": "maintenance/cmms_export.csv",
  "format": "csv",
  "maps_to_doc_ids": ["WO-5001", "WO-5002", "WO-5003", "WO-5004"],
  "doc_type": "work_order",
  "key_facts": ["WO-5001 downtime=4.5h(270min) MTBF=1820h ..."],
  "mess_challenges": ["downtime in 4 different unit formats ...", "..."],
  "notes": "Normalize all downtime to hours: 4.5 / 6.0 / 3.0 / 1.5."
}
```
(`maps_to_doc_ids` is `[]` for `mes/machines.json`, which is the entity-graph
glue rather than a corpus document.)

---

## Recommended evaluation rubric

Compute metrics **per category** (and roll up by persona/difficulty), because
different categories stress different failure modes.

### Ingestion metrics (score `raw/` output against `corpus.jsonl`)
Use `raw/INGESTION_GROUND_TRUTH.jsonl` as the key.
- **Parse success rate** — fraction of raw files ingested without error (watch the
  PDF/XLSX/DOCX and the cp1252 email — these are where naive pipelines fail).
- **Document recovery** — did each raw source yield the right canonical doc(s)?
  Penalize under-splitting (the 2-in-1 datasheet/troubleshooting files) and
  over-splitting.
- **Field/fact extraction accuracy** — check each `key_facts` entry (e.g.,
  downtime normalized to hours, supplier name→ID resolved, units stripped).
- **Normalization correctness** — units, dates, and currency converted to a
  canonical form.
- **Dedup correctness** — the duplicate supplier row collapses; the NCR-7001 vs
  NCR-7004 conflict is *flagged*, not silently merged.
- **Noise handling** — noise docs ingested but not mis-typed as technical content.

A clean ingestion run should reproduce `corpus.jsonl` closely; the gap is your
real-world ingestion risk.

### Retrieval metrics (use `gold_doc_ids`)
- **Recall@k** (k = 1, 3, 5, 10) — fraction of gold docs retrieved in top-k.
  Primary signal for `single_fact`, `multi_hop`, `tabular_reasoning`,
  `constraint_filtering`.
- **MRR** (Mean Reciprocal Rank) — how high the first gold doc ranks. Sensitive
  for `single_fact` and `temporal_versioned`.
- **Context precision** — fraction of retrieved chunks that are actually
  relevant. The `noise` docs and near-duplicates make this meaningful; watch it
  on `aggregation_count` and `comparison` where extra chunks mislead.
- For `multi_hop`, score **set recall** (all hops retrieved), not just top-1.

### Generation metrics
- **Answer correctness** — match against `reference_answer`. For numeric
  categories (`numeric_calculation`, `unit_conversion`) use tolerance-based
  numeric match; for `multi_hop`/`comparison` use key-fact match.
- **Faithfulness / groundedness** — every claim traceable to retrieved context.
  Critical for `high_level_synthesis` (no single gold doc — verify each asserted
  fact against its source) and for `conflict_resolution` (must cite the
  superseding doc).
- **Conflict handling** — for `conflict_resolution`, score = 1 only if the
  **current** value is returned (95 Nm), or, for the near-duplicate NCR case,
  if the model **surfaces the discrepancy** rather than asserting one number.

### Refusal / behavioral metrics (the `answerable: false` set)
- **Refusal accuracy** on `unanswerable` (6 qs) and `out_of_scope_rejection`
  (4 qs): the system must decline / say "not in the knowledge base" rather than
  fabricate. Score false-answer (hallucination) rate here separately — this is
  the headline hallucination-resistance number.
- **Clarification rate** on `ambiguous_needs_clarification` (3 qs): correct
  behavior is to ask which entity is meant, not to guess.
- **False-refusal rate**: ensure the system does *not* refuse answerable
  questions (a common over-correction).

### Suggested headline scorecard
1. Retrieval Recall@5 (answerable set)
2. Answer correctness (answerable set)
3. Faithfulness (all answered)
4. Hallucination rate on the `unanswerable` + `out_of_scope_rejection` set (lower is better)
5. Conflict-resolution accuracy (current-value-or-flag)

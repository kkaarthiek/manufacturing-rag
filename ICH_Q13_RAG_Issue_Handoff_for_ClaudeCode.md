# RAG System — Issue Verification Handoff (for Claude Code)

## Context

We built a RAG system over a single document: **ICH Q13** (Continuous Manufacturing of Drug Substances and Drug Products). We ran a 22-question evaluation (10 answerable + 12 adversarial/unanswerable). Result: **92/110 (84%), mean 4.18/5, zero hallucinations.**

**The system is safe (never fabricates). The problems are recall/completeness and refusal-helpfulness, not correctness.** Two weakness families emerged:
- **Completeness** — on list-type answers it returns the headline + top 1–2 items, then stops.
- **Refusal helpfulness** — when it can't answer, it gives a bare "not in knowledge base" instead of correcting a false premise or pointing to what the document *does* cover.

**Your job (Claude Code):** for each issue below, run the **Verification task** and report whether the hypothesized root cause is actually present in our code/config. Don't assume the diagnosis is correct — confirm or refute it against the real chunker, retriever, and prompts. Note where the diagnosis is wrong.

**What to inspect in the repo:** the chunking/ingestion code, the retriever (embedding model, top-k, any re-ranker), and the generation prompt/template. Have the ICH Q13 source available to grep against.

---

# FAMILY A — Completeness / chunking
*Symptom: correct but incomplete answers on list/multi-part questions.*

### A1 — Q5: Changing production output (scored 3/5)
**Question:** "What approaches does Q13 give for changing production output, with a key risk for each?"

**Answer the system gave:** Listed **three** approaches — (1) change in run time, (2) increase mass flow rates, (3) scale-up by increasing equipment size — each with a correct risk. Explicitly called it "three main approaches."

**Where it went wrong:** Q13 §3.2 lists **four** approaches. The system dropped **scale-out (duplication of equipment)** entirely — the bullet with two nested sub-bullets ("replication of production lines" and "parallel unit operations on the same line"). It also asserted the list was complete at three.

**Hypothesis:** The scale-out bullet, which has nested sub-bullets, is being split into a separate chunk and severed from its parent, so it isn't retrieved alongside the other three approaches.

**Verification task:**
1. Grep the source for "scale-out" / "duplication of equipment" / "Replication of production lines" / "Parallel unit operations".
2. Find which chunk(s) these land in. Check: is the §3.2 "Changes in Production Output" list kept as one chunk, or is the scale-out bullet (+ its nested sub-bullets) in a different chunk from the run-time/mass-flow bullets?
3. Run the actual query "approaches to changing production output in CM" through the retriever. Inspect top-k: does the scale-out chunk appear? At what rank?
4. **Report:** Is scale-out severed in chunking, missing from retrieval, or present-but-not-used by the generator? That tells us whether this is a chunking, retrieval, or prompt problem.

---

### A2 — Q7: Stability batches (scored 3/5)
**Question:** "How do stability-batch expectations for CM (chemical entities) compare with batch manufacturing?"

**Answer the system gave:** Correctly said expectations generally don't differ (Q1A/Q5C), batches must be representative, and captured the **shorter-runs / pilot-scale-may-not-apply** point.

**Where it went wrong:** §4.5 has **three** chemical-entity specifics; the system surfaced only one. Missed: (a) **single start-up/shutdown** batches are acceptable if variability incorporated; (c) if output increased by means other than run time, **justify approach + discuss with authorities**.

**Hypothesis:** Same as A1 — the three sub-bullets under §4.5 are being split across chunks, so only the chunk containing the "shorter runs" bullet was retrieved.

**Verification task:**
1. Grep for "single start-up" / "shorter manufacturing runs" / "increasing equipment size" within the stability section.
2. Check whether these three bullets sit in one chunk or are fragmented.
3. Run query "stability batch requirements for continuous manufacturing chemical entities" and inspect which of the three bullets appear in top-k.
4. **Report:** chunk fragmentation vs retrieval gap.

---

### A3 — Q4: State of control vs steady state (scored 4/5)
**Question:** "What does state of control mean, and how does it differ from steady state?"

**Answer the system gave:** Correct definition + a clean contrast with steady state.

**Where it went wrong:** Missed the §3.1.1 mechanism detail — detecting parameter **drift/trend** and identifying **root cause** (input variation, equipment fatigue, material aging).

**Hypothesis:** Less likely chunking; more likely the generator answered the literal question and didn't include supporting mechanism sentences from the same passage. Possible prompt/completeness issue.

**Verification task:**
1. Check whether the §3.1.1 drift/trend + root-cause sentences are in the **same chunk** as the state-of-control definition.
2. If yes → this is a **generation completeness** problem (prompt), not retrieval. If they're in a separate chunk that wasn't retrieved → retrieval.
3. **Report:** same-chunk-but-omitted (prompt fix) vs separate-chunk-not-retrieved (retrieval fix).

---

### A4 — Q9: Integrated-process DS testing (scored 4/5)
**Question:** "Why may routine DS testing not be required in an integrated process, and how is conformance ensured?"

**Answer the system gave:** Covered the mechanism ("conforms to specification, if tested") and periodic + event-driven verification correctly.

**Where it went wrong:** Didn't state the section's defining point — a DS specification **must still be defined and justified despite the DS never being isolated**.

**Hypothesis:** Generation completeness — it answered the operational "how" and skipped the conceptual framing sentence.

**Verification task:**
1. Confirm the "even though DS is not isolated, a specification should still be defined/justified" sentence is in a retrieved chunk for this query.
2. If present in retrieval but absent from the answer → **prompt/completeness** issue.
3. **Report.**

---

### A5 — Q1 first pass (scored 4, then 5 on retry)
**Question:** "What products and situations does Q13 apply to?"

**Answer the system gave (first pass):** Covered CM of DS/DP and the integration focus, but omitted "applicable to **new products** and **conversion of batch to CM**."
**Retry answer:** Added new/conversion and was complete.

**Where it went wrong:** Incomplete scope on first pass; fixed on a re-run → see Family B (stability).

---

# FAMILY B — Retrieval accuracy & stability
*Symptom: right answer exists in the corpus but wrong/variable chunks are surfaced.*

### B1 — Q2 first pass (scored 2, then 5 on retry)
**Question:** "What are the ways a CM batch size can be defined?"

**Answer the system gave (first pass):** "1. As a fixed size... 2. As a range (360–1080 kg)..." — answered from §4.3 (Batch Description) and the Annex II example.
**Retry answer:** "1. Quantity of output material 2. Quantity of input material 3. Run time at a defined mass flow rate..." — correct, from §2.2.

**Where it went wrong (first pass):** Retrieved the wrong section. The correct list is in §2.2 "Batch definition"; the system pulled §4.3 + Annex II instead. The §2.2 content was retrievable (the retry proved it) but didn't rank into the answer on the first try.

**Hypothesis:** Ranking non-determinism and/or §2.2 not ranking high enough for the query phrasing; top-k too low or no re-ranker.

**Verification task:**
1. Run query "how is batch size defined in CM" through the retriever **5 times**. Record the top-k chunk IDs each run.
2. Check: does the §2.2 "Batch definition" chunk (output material / input material / run time) appear consistently in top-k? Is rank stable across runs?
3. Check current **top-k** value and whether a **re-ranker** is in the pipeline.
4. **Report:** Is retrieval non-deterministic? Is §2.2 ranked below §4.3/Annex II for this query? Would a higher top-k or re-ranker surface §2.2 reliably?

---

### B2 — T4 & T9: distributed-evidence false premises (scored 3/5 each)
**T4 Question:** "What minimum steady-state duration does Q13 require before product collection?"
**T9 Question:** "Q13 prohibits surge tanks in fully integrated processes — what alternatives does it recommend?"

**Answer the system gave (both):** "no answer" / flat refusal.

**Where it went wrong:** Both premises are **false and refuted by the document**, but the refutation is spread across multiple passages rather than in one sentence:
- Steady state: Q13 states a CM process can be in a state of control while *not* at steady state (§3.1.1 + glossary).
- Surge tanks: Q13 explicitly *permits* surge lines/tanks (§2.1, §3.1.4) and uses them throughout the annex examples.

Contrast with **T2 (RTRT mandatory)**, which the system **correctly corrected** — because there the refutation is a single near-verbatim sentence ("RTRT is not a regulatory requirement"). So the system corrects a false premise only when one chunk directly contradicts it; it doesn't assemble a refutation from distributed evidence.

**Hypothesis:** For T4/T9 the contradicting chunks either aren't retrieved (query phrased around the false premise doesn't match the contradicting passages) or are retrieved but the generator doesn't synthesize a correction.

**Verification task:**
1. Run the T4 query and the T9 query through the retriever. Inspect top-k.
2. For T4: do chunks containing the state-of-control / steady-state distinction appear? For T9: do chunks mentioning surge lines/tanks being permitted appear?
3. If the contradicting chunks **are** retrieved but the answer is still "no answer" → generation problem (needs a premise-check + correction instruction).
4. If they're **not** retrieved → retrieval problem (the false-premise phrasing pulls the wrong neighborhood; a re-ranker or query expansion may help).
5. **Report** which case each is.

---

# FAMILY C — Refusal helpfulness
*Symptom: safe refusals that skip retrievable context or a redirect. Each lost exactly 1 point.*

These all scored **4/5**. The system correctly refused (no fabrication) but answered "not in knowledge base" without adding the context the document genuinely contains.

| ID | Question (abbrev) | Answer given | What was retrievable but omitted |
|----|-------------------|--------------|----------------------------------|
| T3 | Max disturbance duration | "Not in the knowledge base. missing: answer not in evidence" | No universal limit exists; criteria are process-specific (Annex V). |
| T5 | Max in vitro cell age | "no answer" | Limit is data-derived per Q5A/Q5B/Q5D (Annex III §3.2). |
| T6 | Max resin/membrane reuse | "no answer" | Treated as process-specific run-time consideration (§3.2, Annex III). |
| T7 | Established Conditions categories | "no answer" | It's a Q12 concept; Q13 says Q12 principles apply (§4.9). |
| T8 | Model-impact tiers | "no answer" | Q13 points to Points-to-Consider; detail commensurate with impact (§4.4). |
| T10 | Bioequivalence study count | "no answer" | Science/risk-based assessment; no fixed number (§4.6, Q5E). |
| T11 | Cleaning/EM limits | "I couldn't find that in your documents." | Out of scope by design — common to batch + CM (§1.2). |
| T12 | Cell bank vial count | "no answer" | Manufacturer defines number/range, must be traceable (Annex III §1). |

**Hypothesis:** The generation prompt instructs "if not in context, say you don't know" but does **not** instruct "after refusing, summarize what the document *does* say on the topic / name the owning guideline." So the system stops at the refusal.

**Verification task:**
1. Locate the generation prompt/template. Find the grounding/refusal instruction.
2. Confirm whether there's any instruction to add adjacent context after a refusal. (Expected: there isn't.)
3. For 2–3 of the above (e.g., T7 Established Conditions, T11 cleaning), run the query and inspect top-k: is the relevant context chunk (e.g., §4.9 Q12 reference; §1.2 scope/out-of-scope statement) actually retrieved?
4. **Report:** If the context chunks are retrieved but unused → this is purely a **prompt fix** (cheap, high-yield, recovers 8 points). If they're not retrieved → also needs retrieval work.

---

# Passing cases (positive controls — do NOT need fixes)

These scored 5/5 and confirm the pipeline works when conditions are right. Use them to sanity-check that any change doesn't regress:
- **Q3 (RTD def), Q6 (tablet example incl. 360–1080 kg), Q8 (disturbance Ex2 vs Ex3 reasoning), Q10 (RTD→traceability synthesis).**
- **T1 (validation batch count):** correct flat refusal on a truly-absent fact.
- **T2 (RTRT mandatory):** correctly corrected the false premise — **this is the target behavior** for T4/T9. Compare T2's retrieval (single contradicting chunk) against T4/T9's retrieval to understand the gap.

---

# Consolidated checklist for Claude Code

- [ ] **Chunking:** Do nested/multi-bullet lists (§3.2 production-output approaches; §4.5 stability specifics) survive as coherent chunks, or are sub-bullets severed from their parent? (A1, A2)
- [ ] **Retrieval ranking:** For "batch size definition", does §2.2 rank into top-k reliably, or do §4.3/Annex II outrank it? (B1)
- [ ] **Retrieval stability:** Run key queries 5× — is top-k deterministic? (B1, A5)
- [ ] **top-k / re-ranker:** What is current top-k? Is there a re-ranker? Would raising k surface the missed chunks? (A1, A2, B1, B2)
- [ ] **Generation prompt — completeness:** Is there an instruction to enumerate *all* distinct points, not just the top ones? (A1–A4)
- [ ] **Generation prompt — post-refusal context:** After a refusal, is there an instruction to state what the doc *does* cover / name the owning guideline? (Family C)
- [ ] **Generation prompt — premise check:** Is there a step to verify an asserted premise against retrieved context before answering? (B2 / T4, T9)
- [ ] **Grounding instruction:** Confirm the "answer only from context, else refuse" rule is present and intact — this is what kept hallucinations at 0. Do not weaken it. (all)

---

# Two prompt snippets to test (once issues are confirmed)

**Completeness (for list/multi-part answers):**
> When the question asks for approaches, factors, requirements, or any list, enumerate **every distinct item present in the retrieved context**. Do not stop after the first one or two. If the context contains a numbered or bulleted list, reproduce all items. State the count only if you are confident the list is complete.

**Post-refusal context (for unanswerable questions):**
> If the retrieved context does not contain a direct answer, say so plainly — do not invent specifics. Then, if the context contains **related** information (e.g., the topic is addressed qualitatively, marked out of scope, or deferred to another guideline), briefly state what the document *does* say and which guideline/section owns the detail. Before answering any question that asserts a fact ("Q13 requires X", "Q13 prohibits Y"), verify that assertion against the retrieved context; if the context contradicts it, correct the premise.

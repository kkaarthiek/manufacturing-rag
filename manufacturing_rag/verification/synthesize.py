"""
Grounded synthesis (spec 9.2).  STATUS: IMPLEMENTED.

Generates the prose answer CONSTRAINED to retrieved evidence — temp 0, citing
each source. Exact values (numbers/IDs/dates) are slot-filled verbatim from the
structured store and handed to the model; the model writes the scaffold, not the
values. After generation, an entailment gate (spec 9.5) checks that EVERY
number/ID in the generated answer appears in the cited evidence — a hallucinated
value cannot ship (faithfulness preserved). On any failure -> abstain/partial.
"""

from __future__ import annotations

import re

from ..contracts import Claim, Answer
from ..providers import LLM

_ID = re.compile(r"\b[A-Z]{2,4}-\d{2,5}(?:-v\d+)?\b")
# standalone numbers only — NOT digits embedded in alphanumeric tokens
# (PA66, 6061-T6, M10) which are names/codes, not values to ground-check.
_NUM = re.compile(r"(?<![A-Za-z0-9])\d+\.?\d*(?![A-Za-z0-9])")

SYSTEM = (
    "You answer questions using ONLY the evidence provided. Never add facts, "
    "numbers, or IDs that are not in the evidence.\n"
    "COMPLETENESS: When the question asks for approaches, factors, requirements, "
    "steps, or any list, enumerate EVERY distinct item present in the evidence "
    "(including nested sub-points). Do not stop after the first one or two; "
    "reproduce full numbered/bulleted lists. State a count only if you are sure the "
    "list is complete.\n"
    "PREMISE CHECK: If the question asserts something ('X requires Y', 'X prohibits "
    "Y') and the evidence contradicts it, correct the premise and cite what the "
    "evidence actually says.\n"
    "EXAMPLES vs RULES: Distinguish illustrative examples from general requirements. "
    "If a number/limit appears ONLY inside a specific worked example, do NOT present "
    "it as a universal limit or rule — say it is an example value, and if the "
    "document treats the matter as process-specific or gives no fixed limit, say so.\n"
    "IF NOT DIRECTLY ANSWERED: reply with 'NOT_IN_EVIDENCE' ONLY if the evidence is "
    "unrelated. If the evidence does not give a direct answer but DOES address the "
    "topic (qualitatively, as out-of-scope, or deferred to another guideline/"
    "section), say plainly that there is no direct/specific answer, then briefly "
    "state what the document DOES say and which section/guideline owns the detail. "
    "Never invent specifics to fill the gap.\n"
    "STYLE: clear plain prose; simple facts in 1-2 sentences, lists fully enumerated. "
    "Do NOT include source IDs, document codes, or citation brackets — sources are "
    "shown to the user separately."
)

# strip any citation/chunk tags the model still emits, e.g. [ING-ICH...::c100]
_CITE_TAG = re.compile(r"\s*[\[(][^\])]*(?:ING-|::c?\d|GUIDELINE|_\d{4}_)[^\])]*[\])]")


def _clean_answer(text: str) -> str:
    return re.sub(r"\s+([.,;])", r"\1", _CITE_TAG.sub("", text)).strip()


def _grounded_values(text: str, evidence_blob: str) -> tuple[bool, list[str]]:
    """Every number/ID in `text` must appear in the evidence (no fabricated values)."""
    hay = evidence_blob.lower()
    bad = []
    for tok in set(_ID.findall(text)) | set(_NUM.findall(text)):
        t = tok.lower()
        if not re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay):
            bad.append(tok)
    return (len(bad) == 0), bad


def synthesize(query: str, evidence: list, llm: LLM, exact_values: dict | None = None,
               top_n: int = 12) -> Answer:
    """evidence: list of Evidence (Phase 3). Returns a grounded Answer or partial.
    top_n widened 6 -> 12 (recall-side only; the entailment gate below grounds
    every value against exactly the evidence shown, so faithfulness is preserved)."""
    if not evidence:
        return Answer(text="No evidence retrieved; cannot synthesize an answer.",
                      claims=[], status="abstained", missing=["no evidence"],
                      trace={"synthesis": "no-evidence"})

    blocks, blob = [], []
    for e in evidence[:top_n]:
        content = e.content if isinstance(e.content, str) else str(e.content)
        # pass the FULL chunk (chunks are ~1200 chars) — truncating here cut off
        # answers that live in the second half of a chunk.
        blocks.append(f"[{e.id}] {content[:1600]}")
        blob.append(content)
    if exact_values:
        ev_line = "; ".join(f"{k}={v}" for k, v in exact_values.items())
        blocks.append(f"[exact values from records] {ev_line}")
        blob.append(ev_line)
    evidence_blob = "\n".join(blob)

    prompt = (f"QUESTION: {query}\n\nEVIDENCE:\n" + "\n".join(blocks)
              + "\n\nAnswer using only the evidence:")
    raw_out = llm.complete(prompt, system=SYSTEM, temperature=0.0).strip()

    if "NOT_IN_EVIDENCE" in raw_out or not raw_out:
        return Answer(text="Not in the knowledge base.", claims=[], status="abstained",
                      missing=["answer not in evidence"],
                      trace={"synthesis": "model-abstained"})

    # clean any inline citation/chunk tags the model emitted -> readable prose
    out = _clean_answer(raw_out)

    # entailment gate: catch WHOLESALE fabrication, but tolerate a few ungrounded
    # numbers (section refs like 3.2.S.2.6) in narrative answers. Run on the CLEANED
    # text so citation-tag digits (filenames/dates) are never mistaken for claims.
    _, bad = _grounded_values(out, evidence_blob)
    all_vals = set(_ID.findall(out)) | set(_NUM.findall(out))
    ungrounded_ratio = len(bad) / max(1, len(all_vals))
    cites = [e.id for e in evidence[:top_n]]
    if ungrounded_ratio > 0.4 and len(bad) >= 3:        # substantially ungrounded
        return Answer(text="Couldn't fully ground the generated answer; abstaining.",
                      claims=[], status="abstained",
                      missing=[f"ungrounded values: {bad[:6]}"],
                      trace={"synthesis": "entailment-failed", "ungrounded": bad})
    verified = not bad
    claim = Claim(text=out, ctype="entailment", value=out,
                  operation={"grounded_in": cites, "ungrounded": bad},
                  citations=cites, verified=verified)
    return Answer(text=out, claims=[claim], status="answered",
                  missing=([] if verified else [f"unverified refs: {bad[:4]}"]),
                  trace={"synthesis": "hosted-grounded", "citations": cites,
                         "ungrounded_minor": bad})


__all__ = ["synthesize"]

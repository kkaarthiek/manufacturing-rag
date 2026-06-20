"""
Step 6 — the single extraction pass (spec 6.4).  STATUS: IMPLEMENTED.

THE HOT PATH. One temp-0 call per cleaned chunk returns, in ONE structured JSON
output: context blurb + atomic propositions + (s,p,o) triples + entity mentions
+ hypothetical questions + validity/date signals. Replaces 5+ passes.

Self-consistency (spec 0): run N times; UNION the propositions/questions across
runs (recall-oriented — every derived unit is independently grounded-verified in
derive.py, so union can't admit an unsupported claim), and flag whether the runs
agreed. The system prompt is static and prompt-cached (provider) so re-running
across 42 chunks reuses the prefix at ~0.1x.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..providers import LLM

SYSTEM = (
    "You are a manufacturing-data extraction engine. Read the document chunk and "
    "return ONLY a single valid JSON object, no prose, no markdown fences. Extract "
    "ONLY facts explicitly present in the text; never invent values, IDs, or numbers. "
    "Schema:\n"
    "{\n"
    '  "context_blurb": "<=2 sentences situating this chunk in the factory (entities, doc type)",\n'
    '  "propositions": ["atomic standalone facts, each self-contained with its entity IDs/values"],\n'
    '  "triples": [["subject","predicate","object"]],\n'
    '  "entity_mentions": [{"surface":"as written","canonical_id":"ID if stated e.g. MCH-301 or null"}],\n'
    '  "questions": ["natural questions THIS chunk answers"],\n'
    '  "validity": {"effective_date":"YYYY-MM-DD or null","supersedes":"ID or null","status":"current|superseded|null"}\n'
    "}"
)


@dataclass
class Extraction:
    context_blurb: str = ""
    propositions: list[str] = field(default_factory=list)
    triples: list[list] = field(default_factory=list)
    entity_mentions: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    validity: dict = field(default_factory=dict)
    agreed: bool = True


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)  # strip fences
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _one_pass(llm: LLM, chunk: str, retries: int = 1) -> dict | None:
    prompt = f"DOCUMENT CHUNK:\n{chunk}\n\nReturn the JSON object now."
    for _ in range(retries + 1):
        out = llm.complete(prompt, system=SYSTEM, temperature=0.0)
        d = _parse_json(out)
        if d is not None:
            return d
    return None


def extract_chunk(llm: LLM, chunk_text: str, n: int = 1) -> Extraction:
    """Single extraction pass with N-run self-consistency (union + agreement flag)."""
    runs = []
    for _ in range(max(1, n)):
        d = _one_pass(llm, chunk_text)
        if d:
            runs.append(d)
    if not runs:
        return Extraction(agreed=False)

    base = runs[0]
    props, ques = [], []
    seen_p, seen_q = set(), set()
    for r in runs:
        for p in r.get("propositions", []) or []:
            key = p.strip().lower()
            if key and key not in seen_p:
                seen_p.add(key); props.append(p.strip())
        for q in r.get("questions", []) or []:
            key = q.strip().lower()
            if key and key not in seen_q:
                seen_q.add(key); ques.append(q.strip())
    agreed = all(len(r.get("propositions", []) or []) == len(runs[0].get("propositions", []) or [])
                 for r in runs)
    return Extraction(
        context_blurb=(base.get("context_blurb") or "").strip(),
        propositions=props, triples=base.get("triples", []) or [],
        entity_mentions=base.get("entity_mentions", []) or [],
        questions=ques, validity=base.get("validity", {}) or {}, agreed=agreed)


__all__ = ["Extraction", "extract_chunk", "SYSTEM"]

"""
Incremental ingestion of a new document (spec 6.11).  STATUS: IMPLEMENTED.

Generic single-doc path for files uploaded after the initial build: parse ->
classify doc_type -> resolve entity mentions against the EXISTING alias map ->
produce a CanonicalDoc. The System then adds it to the live stores idempotently
(append-mostly; no rebuild). Per-doc cost is linear in the new doc.

Unlike the deterministic per-source assemblers in pipeline.py (which know the
exact factory files), this path is format-/content-generic so any uploaded file
can enter the pipeline.
"""

from __future__ import annotations

import re

from ..contracts import CanonicalDoc
from . import parsers as P

_ID = re.compile(r"\b[A-Z]{2,4}-\d{2,5}(?:-v\d+)?\b")

# lightweight doc_type classifier (keyword rules; the LLM extraction refines later)
_RULES = [
    ("quality_report", r"fpy|first-pass yield|release threshold|quality summary"),
    ("ncr", r"non-?conformance|\bncr-|short shot|disposition|out of tolerance"),
    ("purchase_order", r"purchase order|\bpo-|unit price|\bmoq\b"),
    ("work_order", r"work order|\bwo-|downtime|mtbf|technician"),
    ("sop", r"\bsop-|standard operating|lockout|tagout|loto|changeover|torque"),
    ("material_datasheet", r"datasheet|tensile|yield strength|density|brinell|mpa"),
    ("telemetry", r"\boee\b|vibration|availability.*performance|historian"),
    ("incident", r"incident report|near-?miss|root cause|corrective action"),
    ("troubleshooting", r"troubleshoot|faq|common causes|probable cause"),
    ("standard", r"\bclause\b|paraphrased|compliance standard"),
    ("supplier", r"supplier|lead time|supplied by|quotation"),
    ("part_spec", r"\bprt-|tolerance|outside diameter|specification"),
    ("noise", r"cafeteria|menu|parking|holiday schedule|break room"),
]


def classify_doc_type(text: str, filename: str) -> str:
    hay = (filename + "\n" + text).lower()
    best, score = "uncategorized", 0
    for dt, pat in _RULES:
        n = len(re.findall(pat, hay, re.I))
        if n > score:
            best, score = dt, n
    return best


def resolve_mentions(text: str, alias_map: dict) -> list[str]:
    """Canonical IDs referenced in the text: explicit IDs + alias/codename hits."""
    found = set(_ID.findall(text))
    low = text.lower()
    for alias, cid in alias_map.items():
        if len(alias) >= 4 and re.search(
                r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", low):
            found.add(cid)
    return sorted(found)


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    """Split long text into overlapping chunks at paragraph/sentence boundaries.
    Real documents (multi-page PDFs) must be chunked — one giant unit can't be
    embedded (token limits) or retrieved precisely."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    # prefer paragraph splits; pack paragraphs up to `size`
    paras = re.split(r"\n\s*\n+", text)
    chunks, cur = [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(p) > size:                              # hard-split an oversized paragraph
            for i in range(0, len(p), size - overlap):
                chunks.append(p[i:i + size])
            continue
        if len(cur) + len(p) + 1 > size:
            if cur:
                chunks.append(cur.strip())
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _slug(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return "ING-" + re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")[:48].upper()


def ingest_upload(filename: str, raw: bytes, alias_map: dict) -> CanonicalDoc:
    """Parse + classify + resolve a single uploaded file -> CanonicalDoc."""
    fmt = P.detect_format(filename, raw)
    text = P.parse(fmt, raw)
    doc_type = classify_doc_type(text, filename)
    entities = resolve_mentions(text, alias_map)
    title = next((ln.strip() for ln in text.splitlines() if ln.strip()), filename)[:90]
    doc_id = _slug(filename)
    return CanonicalDoc(
        id=doc_id, doc_type=doc_type, source_file=filename, format=fmt,
        clean_text=text, structured_fields={"uploaded": True},
        entities=entities, provenance={"file": filename, "uploaded": True})


__all__ = ["ingest_upload", "classify_doc_type", "resolve_mentions"]

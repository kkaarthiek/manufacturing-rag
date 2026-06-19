#!/usr/bin/env python3
"""
ingest.py — Lightweight ingestion engine (standard library only).

Given a raw source file (any of the formats in raw/), it:
  1. detects the format,
  2. extracts text best-effort (incl. real .pdf/.xlsx/.docx, html, eml, csv...),
  3. guesses a manufacturing category (doc_type),
  4. returns a DRAFT canonical document {doc_id, doc_type, title, text,
     metadata} ready to be reviewed/edited in the web UI.

This is intentionally simple and "best effort" — that's exactly why the web app
exposes a category view + inline editor: the human corrects what extraction
can't perfectly recover.
"""

import csv
import html
import io
import json
import re
import zipfile
from pathlib import Path

DOC_TYPES = [
    "supplier", "part_spec", "sop", "work_order", "ncr", "quality_report",
    "standard", "purchase_order", "material_datasheet", "telemetry",
    "troubleshooting", "incident", "noise", "entity_graph", "uncategorized",
]


# --------------------------------------------------------------------------- #
# Decoding / format detection
# --------------------------------------------------------------------------- #
def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            s = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        s = data.decode("utf-8", "replace")
    return s.replace("\r\n", "\n").replace("\r", "\n")


def detect_format(filename: str, data: bytes) -> str:
    name = filename.lower()
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:2] == b"PK":  # zip-based OOXML
        if name.endswith(".docx"):
            return "docx"
        if name.endswith(".xlsx"):
            return "xlsx"
        return "zip"
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("csv", "tsv"):
        return "csv"
    if ext in ("html", "htm"):
        return "html"
    if ext == "json":
        return "json"
    if ext in ("eml", "msg"):
        return "eml"
    if ext in ("md", "markdown"):
        return "md"
    return "txt"


# --------------------------------------------------------------------------- #
# Per-format extractors
# --------------------------------------------------------------------------- #
def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<(br|/p|/h[1-6]|/tr|/li|/div)[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def _extract_eml(s: str):
    headers, _, body = s.partition("\n\n")
    subject = ""
    for line in headers.splitlines():
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
    keep = []
    for line in body.splitlines():
        ls = line.strip()
        if ls.startswith(">"):          # quoted reply history
            continue
        if ls in ("--", "-- "):         # signature delimiter
            break
        keep.append(line)
    return subject, "\n".join(keep).strip()


def _extract_xlsx(data: bytes) -> str:
    try:
        from manufacturing_rag.ingestion.parsers import extract_xlsx as _x
        return _x(data)
    except Exception:
        return ""


def _extract_docx(data: bytes) -> str:
    try:
        from manufacturing_rag.ingestion.parsers import extract_docx as _d
        return _d(data)
    except Exception:
        return ""


def _extract_pdf(data: bytes) -> str:
    # delegate to the hardened library-based parser (PyMuPDF/pdfplumber + fallback)
    try:
        from manufacturing_rag.ingestion.parsers import extract_pdf as _pp
        return _pp(data)
    except Exception:
        return ""


def extract_text(fmt: str, data: bytes):
    """Return (text, raw_decoded_or_none)."""
    if fmt == "pdf":
        return _extract_pdf(data), None
    if fmt == "xlsx":
        return _extract_xlsx(data), None
    if fmt == "docx":
        return _extract_docx(data), None
    s = decode_text(data)
    if fmt == "html":
        return _strip_html(s), s
    if fmt == "eml":
        subj, body = _extract_eml(s)
        return (f"{subj}\n{body}" if subj else body), s
    if fmt == "json":
        try:
            obj = json.loads(s)
            return json.dumps(obj, indent=2, ensure_ascii=False), s
        except Exception:
            return s, s
    if fmt == "csv":
        rows = list(csv.reader(io.StringIO(s)))
        return "\n".join(" | ".join(r) for r in rows), s
    return s, s


# --------------------------------------------------------------------------- #
# Category heuristics
# --------------------------------------------------------------------------- #
_RULES = [
    ("quality_report", r"quality summary|fpy by line|release threshold|units produced|first-pass yield\b.*\bline"),
    ("ncr", r"non-?conformance|\bNCR-|short shot|out of tolerance|disposition"),
    ("purchase_order", r"purchase order|\bPO-\d|unit price|\bMOQ\b"),
    ("work_order", r"work order|\bWO-\d|downtime|MTBF|technician"),
    ("sop", r"\bSOP-\d|standard operating|lockout|tagout|LOTO|changeover|retaining-?nut torque"),
    ("material_datasheet", r"datasheet|tensile|yield strength|density.*g/cm|brinell|MPa"),
    ("telemetry", r"\bOEE\b|vibration|availability.*performance.*quality|historian|telemetry"),
    ("incident", r"incident report|near-?miss|root cause|corrective action"),
    ("troubleshooting", r"troubleshoot|FAQ|common causes|probable cause"),
    ("standard", r"\bclause\b|paraphrased|compliance|standard"),
    ("supplier", r"supplier|lead time|supplied by|firmographic|quotation"),
    ("part_spec", r"\bPRT-\d|tolerance|outside diameter|material:|specification"),
    ("entity_graph", r"\"machines\"|codename.*line.*program"),
    ("noise", r"cafeteria|menu|parking|holiday schedule|break room"),
]


def guess_category(filename: str, text: str) -> tuple:
    hay = (filename + "\n" + text).lower()
    best, score = "uncategorized", 0
    for cat, pat in _RULES:
        hits = len(re.findall(pat, hay, re.I))
        if hits > score:
            best, score = cat, hits
    confidence = "high" if score >= 3 else ("medium" if score >= 1 else "low")
    return best, confidence


def _slug(name: str) -> str:
    stem = Path(name).stem
    return "ING-" + re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")[:48].upper()


def ingest_bytes(filename: str, data: bytes, existing_ids=()) -> dict:
    fmt = detect_format(filename, data)
    text, _ = extract_text(fmt, data)
    category, confidence = guess_category(filename, text)
    title = Path(filename).name
    # title from first non-empty line if it looks like a heading
    for ln in text.splitlines():
        if ln.strip():
            if len(ln.strip()) <= 90:
                title = ln.strip()
            break
    doc_id = _slug(filename)
    if existing_ids:
        base, n = doc_id, 2
        while doc_id in existing_ids:
            doc_id = f"{base}-{n}"
            n += 1
    return {
        "doc_id": doc_id,
        "doc_type": category,
        "title": title,
        "text": text,
        "metadata": {
            "source_file": filename,
            "source_format": fmt,
            "status": "draft",
            "extraction_confidence": confidence,
            "char_count": len(text),
        },
    }


def ingest_path(path: Path, existing_ids=()) -> dict:
    return ingest_bytes(path.name, path.read_bytes(), existing_ids)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        d = ingest_path(Path(arg))
        print(f"{d['doc_id']:28s} [{d['doc_type']:18s}] "
              f"conf={d['metadata']['extraction_confidence']:6s} "
              f"{d['metadata']['char_count']:6d} chars  <- {arg}")

#!/usr/bin/env python3
"""
validate_raw.py — Integrity harness for the RAW ingestion test bed.

Asserts that raw/ and its ground-truth manifest are coherent and that the
binary formats are real/parseable, so the raw layer is trustworthy as an
ingestion target. Standard library only.

Checks:
  - every source_file in the manifest exists on disk (and vice versa)
  - every maps_to_doc_id resolves to a doc in corpus.jsonl
  - all 42 canonical corpus docs are covered by >= 1 raw source
  - the .xlsx and .docx are valid ZIP/OOXML and contain expected parts
  - the .pdf has a valid header/EOF and is non-trivial
  - the cp1252 email does NOT decode cleanly as strict UTF-8 (encoding trap)
Prints a summary; exits non-zero on any failure.
"""

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
MANIFEST = RAW / "INGESTION_GROUND_TRUTH.jsonl"
CORPUS = ROOT / "corpus.jsonl"

errors = []


def err(m):
    errors.append(m)


def load_jsonl(path):
    rows = []
    if not path.exists():
        err(f"Missing file: {path}")
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                err(f"{path.name} line {i}: JSON parse error: {e}")
    return rows


def main():
    manifest = load_jsonl(MANIFEST)
    corpus = load_jsonl(CORPUS)
    corpus_ids = {d["doc_id"] for d in corpus}

    # files on disk vs manifest (exclude the manifest itself)
    disk_files = {
        str(p.relative_to(RAW)).replace("\\", "/")
        for p in RAW.rglob("*") if p.is_file() and p.name != MANIFEST.name
    }
    manifest_files = {g["source_file"] for g in manifest}

    for g in manifest:
        if not (RAW / g["source_file"]).exists():
            err(f"manifest source_file missing on disk: {g['source_file']}")
        for did in g["maps_to_doc_ids"]:
            if did not in corpus_ids:
                err(f"{g['source_file']}: maps_to_doc_id '{did}' not in corpus.jsonl")

    for f in disk_files - manifest_files:
        err(f"file on disk not in manifest: {f}")

    # coverage: every canonical doc has at least one raw source
    covered = set()
    for g in manifest:
        covered.update(g["maps_to_doc_ids"])
    uncovered = corpus_ids - covered
    if uncovered:
        err(f"canonical docs with no raw source: {sorted(uncovered)}")

    # ---- binary format integrity ----
    xlsx = RAW / "quality/Q1_2025_FPY.xlsx"
    if xlsx.exists():
        try:
            with zipfile.ZipFile(xlsx) as z:
                names = z.namelist()
                for need in ("[Content_Types].xml", "xl/workbook.xml",
                             "xl/worksheets/sheet1.xml"):
                    if need not in names:
                        err(f"xlsx missing part: {need}")
                sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
                if "94.2" not in sheet or "PEGASUS" not in sheet:
                    err("xlsx sheet1 missing expected FPY data")
        except zipfile.BadZipFile:
            err("Q1_2025_FPY.xlsx is not a valid zip/OOXML file")
    else:
        err("missing quality/Q1_2025_FPY.xlsx")

    docx = RAW / "sops/SOP-001_Rev2.docx"
    if docx.exists():
        try:
            with zipfile.ZipFile(docx) as z:
                if "word/document.xml" not in z.namelist():
                    err("docx missing word/document.xml")
                else:
                    body = z.read("word/document.xml").decode("utf-8")
                    if "95 Nm" not in body:
                        err("docx body missing the current '95 Nm' value")
        except zipfile.BadZipFile:
            err("SOP-001_Rev2.docx is not a valid zip/OOXML file")
    else:
        err("missing sops/SOP-001_Rev2.docx")

    pdf = RAW / "standards/HX-900_excerpt.pdf"
    if pdf.exists():
        raw = pdf.read_bytes()
        if not raw.startswith(b"%PDF-"):
            err("HX-900_excerpt.pdf missing %PDF- header")
        if b"%%EOF" not in raw:
            err("HX-900_excerpt.pdf missing %%EOF")
        if len(raw) < 500:
            err("HX-900_excerpt.pdf suspiciously small")
    else:
        err("missing standards/HX-900_excerpt.pdf")

    # ---- encoding trap: the cp1252 email must NOT be valid strict UTF-8 ----
    eml = RAW / "email/vector_bearings_quote.eml"
    if eml.exists():
        try:
            eml.read_bytes().decode("utf-8")
            err("vector_bearings_quote.eml decoded as UTF-8 but should be cp1252")
        except UnicodeDecodeError:
            pass  # expected: it is genuinely cp1252
    else:
        err("missing email/vector_bearings_quote.eml")

    # ---- summary ----
    print("=" * 64)
    print("RAW INGESTION TEST BED - VALIDATION SUMMARY")
    print("=" * 64)
    print(f"Raw source files (excl. manifest): {len(disk_files)}")
    print(f"Manifest entries                 : {len(manifest)}")
    print(f"Canonical docs covered           : {len(covered & corpus_ids)} / {len(corpus_ids)}")
    print()
    fmts = {}
    for g in manifest:
        fmts[g["format"]] = fmts.get(g["format"], 0) + 1
    print("Source formats:")
    for k, v in sorted(fmts.items()):
        print(f"  {k:20s} {v}")
    print()
    challenges = {}
    for g in manifest:
        for c in g["mess_challenges"]:
            key = c.split(" (")[0].split(" -")[0][:42]
            challenges[key] = challenges.get(key, 0) + 1
    print(f"Distinct mess-challenge types planted: {len(challenges)}")
    print("=" * 64)

    if errors:
        print(f"\nFAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("\nALL RAW CHECKS PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()

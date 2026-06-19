"""
Rich binary extraction (spec 6.2, 6.4).  STATUS: IMPLEMENTED.

Robust extraction for real-industry documents — handles every PDF shape:

  * digital text        -> PyMuPDF text (always, free)
  * structured tables   -> pdfplumber grids -> markdown + per-row records (always, free)
  * embedded images     -> Claude vision CAPTION (hosted, capped) -> text-index units
  * scanned / image-only-> Claude vision OCR of rendered pages (hosted) when the
                           text layer is sparse; otherwise FLAGGED (never silent empty)

Returns a RichDoc: the combined text (digital + table markdown + OCR + captions),
the structured tables (rows), and flags. Non-PDF binaries fall back to plain text.

Cost control: image captioning + OCR run only in hosted mode and are capped
(N images / N pages). Tables and digital text are always extracted deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import parsers as P

OCR_SYSTEM = ("Transcribe ALL text in this document page verbatim, preserving "
              "reading order and tables. Output only the transcribed text.")
CAPTION_SYSTEM = ("Describe this figure/diagram from a manufacturing/technical "
                  "document in 1-2 sentences, naming any labels, equipment, "
                  "values, or process steps shown. Be specific and factual.")


@dataclass
class RichDoc:
    text: str = ""
    tables: list = field(default_factory=list)        # [{page, rows, markdown}]
    image_captions: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    ocr_used: bool = False


def rich_extract(filename: str, raw: bytes, vision_llm=None,
                 hosted: bool = False, max_images: int = 8,
                 max_ocr_pages: int = 8) -> RichDoc:
    fmt = P.detect_format(filename, raw)
    rd = RichDoc()

    if fmt != "pdf":
        rd.text = P.parse(fmt, raw)                    # csv/html/eml/docx/xlsx/txt
        return rd

    # --- PDF ---
    digital = P.extract_pdf(raw)
    coverage = P.pdf_text_coverage(raw)
    rd.tables = P.extract_pdf_tables(raw)
    parts = []

    # scanned / image-only: sparse text layer -> vision OCR (or flag)
    if coverage < 80:
        if hosted and vision_llm is not None:
            ocr_parts = []
            for png, pi in P.render_pdf_pages(raw, max_pages=max_ocr_pages):
                try:
                    ocr_parts.append(vision_llm.vision(OCR_SYSTEM, png))
                except Exception:
                    pass
            if ocr_parts:
                rd.ocr_used = True
                parts.append("\n".join(ocr_parts))
                rd.flags.append(f"scanned PDF -> vision-OCR'd {len(ocr_parts)} page(s)")
            else:
                rd.flags.append("scanned PDF but OCR produced nothing")
        else:
            rd.flags.append("SCANNED/image-only PDF: no text layer; needs hosted "
                            "vision OCR (offline can't read it)")
    if digital:
        parts.append(digital)

    # structured tables -> append markdown (also kept as rows for the structured store)
    for t in rd.tables:
        parts.append(f"[table p{t['page']}]\n{t['markdown']}")

    # embedded images -> vision captions (hosted, capped)
    if hosted and vision_llm is not None:
        imgs = P.extract_pdf_images(raw, max_images=max_images)
        for png, pi in imgs:
            try:
                cap = vision_llm.vision(CAPTION_SYSTEM, png).strip()
                if cap:
                    rd.image_captions.append({"page": pi, "caption": cap})
                    parts.append(f"[figure p{pi}] {cap}")
            except Exception:
                pass
        if imgs:
            rd.flags.append(f"captioned {len(rd.image_captions)}/{len(imgs)} image(s)")
    elif P.extract_pdf_images(raw, max_images=1):
        rd.flags.append("images present (caption them in hosted mode)")

    rd.text = "\n\n".join(p for p in parts if p).strip()
    return rd


__all__ = ["RichDoc", "rich_extract"]

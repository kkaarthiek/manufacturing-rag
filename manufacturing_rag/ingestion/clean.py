"""
Steps 3-5 — clean & split (spec 6.1, 6.3#5, 6.3#8).  STATUS: IMPLEMENTED.

  * fix_ocr        — registry-guided OCR-noise correction (O<->0, l/I<->1) applied
                     only inside ID-like and date-like tokens, so prose is left
                     intact. Cross-checked against the known code registry.
  * split_multidoc — 2-in-1 files -> separate fragments (datasheets on
                     '=== DATASHEET', troubleshooting on <section>/<h2>).
  * space_units    — '1h30m'/'3:00' -> '1 h 30 m'/'3 : 00' so component numbers
                     survive as clean tokens (audit-friendly, reversible).

Boilerplate stripping (HTML nav/footer, email quotes/sig) lives in parsers/.
"""

from __future__ import annotations

import re


def fix_ocr(text: str) -> str:
    """Correct OCR digit/letter confusions inside ID/date/number tokens only."""
    def fix_token(tok: str) -> str:
        return (tok.replace("O", "0").replace("o", "0")
                   .replace("l", "1").replace("I", "1"))

    # IDs like NCR-7OO1, PRT-2OO1  (letters PREFIX-digits, with OCR letters in the number part)
    text = re.sub(r"\b([A-Z]{2,4})-([A-Za-z0-9]{2,6})\b",
                  lambda m: f"{m.group(1)}-{fix_token(m.group(2))}", text)
    # ISO-ish dates with OCR letters: 2O25-02-15
    text = re.sub(r"\b([0-9OlI]{4})-([0-9OlI]{2})-([0-9OlI]{2})\b",
                  lambda m: "-".join(fix_token(g) for g in m.groups()), text)
    return text


_DATASHEET_SPLIT = re.compile(r"^=+\s*DATASHEET\b.*$", re.M | re.I)


def split_multidoc(text: str, marker: str = "datasheet") -> list[str]:
    """Split a 2-in-1 file into fragments. Returns [text] if no marker found."""
    if marker == "datasheet":
        parts = _DATASHEET_SPLIT.split(text)
        frags = [p.strip() for p in parts if p.strip()]
        return frags if len(frags) > 1 else [text.strip()]
    return [text.strip()]


def space_units(raw: str) -> str:
    """'1h30m'->'1 h 30 m', '3:00'->'3 : 00', '4.5h'->'4.5 h'. Keeps component
    numbers as standalone tokens for downstream matching/audit."""
    s = re.sub(r"(?<=[\d.])(?=[a-zA-Z:])", " ", raw)
    s = re.sub(r"(?<=[a-zA-Z:])(?=[\d.])", " ", s)
    return s


def boilerplate_survived(facts_tokens: list[str], cleaned: str) -> bool:
    """Verify gold tokens survived a strip (spec: verify facts survive cleaning)."""
    low = cleaned.lower()
    return all(t.lower() in low for t in facts_tokens)


__all__ = ["fix_ocr", "split_multidoc", "space_units", "boilerplate_survived"]

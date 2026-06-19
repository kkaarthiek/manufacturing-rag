"""
Steps 7,9,10 — the cross-cutting transforms (spec 6.3).  STATUS: IMPLEMENTED.

Deterministic. Each KEEPS the raw value beside the normalized one (spec:
reversibility/audit) and fails loud rather than silently dropping. These produce
the *derived* facts the canonical corpus doesn't literally contain — totals,
minute<->hour conversions, weeks->days, monthly OEE — i.e. exactly the 20 gold
facts the baseline missed.
"""

from __future__ import annotations

import re

UNIT_TARGETS = {"time": "h", "length": "mm", "lead_time": "days", "mass": "g",
                "pressure": "MPa", "temperature": "C"}


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #
def parse_duration_hours(text: str) -> float | None:
    """Parse downtime in any of: '4.5h' / '360 min' / '3:00' / '1h30m' -> hours."""
    t = text.strip().lower()
    m = re.fullmatch(r"(\d+):(\d{2})", t)            # H:MM
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 60, 4)
    m = re.fullmatch(r"(\d+)\s*h\s*(\d+)\s*m", t)    # 1h30m
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 60, 4)
    m = re.fullmatch(r"([\d.]+)\s*h(?:rs?|ours?)?", t)  # 4.5h
    if m:
        return round(float(m.group(1)), 4)
    m = re.fullmatch(r"([\d.]+)\s*m(?:in(?:utes?)?)?", t)  # 360 min
    if m:
        return round(float(m.group(1)) / 60, 4)
    return None


def lead_time_to_days(text: str) -> int | None:
    """'45 days' / '2 weeks' / '5 weeks' -> integer days."""
    t = text.strip().lower()
    m = re.search(r"([\d.]+)\s*day", t)
    if m:
        return int(float(m.group(1)))
    m = re.search(r"([\d.]+)\s*week", t)
    if m:
        return int(float(m.group(1)) * 7)
    m = re.fullmatch(r"\d+", t)
    return int(t) if m else None


def strip_unit_number(text: str) -> float | None:
    """'250 mm' / '+/-0.02 mm' / '30 mm' -> 250.0 / 0.02 / 30.0 (first number)."""
    m = re.search(r"[\d.]+", text.replace(",", ""))
    return float(m.group(0)) if m else None


def normalize_units(value: str, kind: str) -> dict:
    """-> {raw, normalized, unit}. Keeps raw (spec: keep raw + normalized)."""
    if kind == "time":
        return {"raw": value, "normalized": parse_duration_hours(value), "unit": "h"}
    if kind == "lead_time":
        return {"raw": value, "normalized": lead_time_to_days(value), "unit": "days"}
    if kind in ("length", "mass", "pressure"):
        return {"raw": value, "normalized": strip_unit_number(value),
                "unit": UNIT_TARGETS[kind]}
    return {"raw": value, "normalized": value, "unit": None}


# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #
def parse_money(text: str) -> float | None:
    """'$42.50' / 'USD 115.00' / '0.35 USD' -> 42.50 / 115.00 / 0.35."""
    m = re.search(r"[\d,]+\.?\d*", text)
    return float(m.group(0).replace(",", "")) if m else None


def parse_int(text: str) -> int | None:
    """'5,000' / '200' -> 5000 / 200 (strips thousands separators)."""
    m = re.search(r"[\d,]+", text)
    return int(m.group(0).replace(",", "")) if m else None


def normalize_date(text: str) -> str | None:
    """'2025-01-10' or '01/18/2025' -> ISO 'YYYY-MM-DD'."""
    t = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        mo, da, yr = m.groups()
        return f"{yr}-{int(mo):02d}-{int(da):02d}"
    return None


# --------------------------------------------------------------------------- #
# Aggregation (deterministic summaries; keep raw rows linked)
# --------------------------------------------------------------------------- #
def mean(values: list[float], ndigits: int = 1) -> float:
    return round(sum(values) / len(values), ndigits) if values else 0.0


def line_total(qty, unit_price, ndigits: int = 2) -> float:
    return round(qty * unit_price, ndigits)


def oee(availability: float, performance: float, quality: float) -> float:
    """OEE = A x P x Q, as a percentage (components given as fractions).

    Reported to 1 decimal by TRUNCATION, matching how the plant's telemetry
    summaries publish it (e.g. 0.84*0.93*0.98 = 76.5576% -> 76.5, not rounded
    76.6). Truncation reproduces the authoritative TEL-301/302 values exactly."""
    import math
    return math.floor(availability * performance * quality * 1000) / 10


# --------------------------------------------------------------------------- #
# Dedup / conflict-flag (never delete; link + flag)
# --------------------------------------------------------------------------- #
def conflict_flag(rec_a: dict, rec_b: dict, on: str) -> dict | None:
    """If two records disagree on field `on`, return a flag (never merge/delete)."""
    if rec_a.get(on) != rec_b.get(on):
        return {"field": on, "values": {rec_a.get("id"): rec_a.get(on),
                                        rec_b.get("id"): rec_b.get(on)},
                "resolution": "flag_both", "status": "unresolved"}
    return None


__all__ = ["UNIT_TARGETS", "parse_duration_hours", "lead_time_to_days",
           "strip_unit_number", "normalize_units", "parse_money", "parse_int",
           "normalize_date", "mean", "line_total", "oee", "conflict_flag"]

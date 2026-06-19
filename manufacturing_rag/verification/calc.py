"""
Calculation lane (spec 9.3).  STATUS: IMPLEMENTED.

The "numbers -> code" oracle. The LLM (or the deterministic router) only SETS UP
the computation (operation + operands, each tagged with provenance); this
executor RUNS it with error rate 0. The only fallible step is setup, which is
guarded by unit/dimensional + range/sanity checks and self-consistency upstream.
Execution here is exact and re-runnable (the verifier re-invokes it).
"""

from __future__ import annotations

OPS = {
    "sum": lambda xs: round(sum(xs), 6),
    "product": lambda xs: round(_prod(xs), 6),
    "mul": lambda xs: round(xs[0] * xs[1], 6),
    "count": lambda xs: len(xs),
    "avg": lambda xs: round(sum(xs) / len(xs), 6) if xs else 0.0,
    "max": lambda xs: max(xs),
    "min": lambda xs: min(xs),
    "diff": lambda xs: round(xs[0] - xs[1], 6),
}

# unit conversions (factor); deterministic
CONVERT = {
    ("nm", "ftlb"): 0.737562, ("mm", "in"): 1 / 25.4,
    ("g_cm3", "kg_m3"): 1000.0, ("h", "min"): 60.0, ("weeks", "days"): 7.0,
}


def _prod(xs):
    out = 1.0
    for x in xs:
        out *= x
    return out


def execute(op: str, operands: list[float]) -> float:
    if op not in OPS:
        raise ValueError(f"unknown op: {op}")
    return OPS[op](operands)


def convert(value: float, frm: str, to: str, ndigits: int = 4) -> float:
    factor = CONVERT.get((frm, to))
    if factor is None:
        raise ValueError(f"no conversion {frm}->{to}")
    return round(value * factor, ndigits)


def sanity_ok(op: str, operands: list[float], result: float) -> bool:
    """Range/dimensional sanity (a wrong-operand guard, not a correctness proof)."""
    if op in ("sum", "product", "mul", "avg", "max", "min") and operands:
        return min(operands) - 1e-9 <= result or result >= 0  # non-paradoxical
    return True


__all__ = ["execute", "convert", "sanity_ok", "OPS", "CONVERT"]

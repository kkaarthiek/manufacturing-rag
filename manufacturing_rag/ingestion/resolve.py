"""
Step 8 — entity resolution (spec 6.6).  STATUS: SKELETON (alias path is trivial).

The #1 recall lever. Separate NAMING (alias -> canonical name) from IDENTITY
(same node?). Route each mention to merge / new / flag-for-review; link source
records with a SAME_AS edge (never destroy provenance). Mostly deterministic via
the alias map (machines.json + supplier master); reserve blocking -> similarity
-> LLM matching for unmapped/borderline mentions (with self-consistency).

Unresolved mention => LOUD flag (a missing alias silently zeroes recall).
"""

from __future__ import annotations


def resolve_mention(surface: str, alias_map: dict[str, str]) -> str | None:
    """Deterministic alias lookup. Returns canonical_id or None (=> caller flags)."""
    return alias_map.get(surface.strip().lower())


def resolve_or_flag(surface: str, alias_map: dict[str, str], flags: list) -> str | None:
    cid = resolve_mention(surface, alias_map)
    if cid is None:
        flags.append({"unresolved_mention": surface})   # loud, not silent
    return cid


def fuzzy_resolve(surface: str, candidates: list[str]) -> str | None:
    raise NotImplementedError(
        "Phase 1: blocking -> embedding similarity -> LLM match (self-consistency) "
        "for mentions the alias map misses.")

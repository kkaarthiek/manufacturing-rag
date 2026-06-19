"""
Keyword index (spec 7.1).  STATUS: SKELETON.

Contextual-BM25 (store contextualized chunks, never raw), lexical-weighted for
IDs/codes. A working BM25 lives in eval/baselines.py; Phase 2 promotes it here
over the *contextual* chunks and wires RRF fusion with the vector index.
"""

from __future__ import annotations

from ..eval.baselines import BM25Baseline  # promote the baseline BM25 here

__all__ = ["BM25Baseline"]

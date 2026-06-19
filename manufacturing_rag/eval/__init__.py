"""Eval harness (spec Section 5) — the measure-first core.

Loads the two gold sets, verifies the gold set ITSELF (a gap in gold is a false
recall=1), runs the current pipeline (Phase-0 baselines/stubs) against them, and
reports per-phase gate status. Runnable on every commit as a regression gate.
"""

"""
Phase 4 — Verification & Abstention (spec Section 9).  STATUS: IMPLEMENTED.

Turns the Phase-3 evidence set into a faithful answer or a calibrated abstention,
verifying every claim by its class before it ships. Core thesis: checking a
claim is easier and more reliable than generating it (generate-then-verify).

The cross-cutting invariant enforced here: a claim ships only if it is verbatim
from a source OR the output of a verifiable deterministic operation over sourced
inputs — otherwise abstain.
"""

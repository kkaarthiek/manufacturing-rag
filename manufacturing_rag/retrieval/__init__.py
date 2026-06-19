"""
Phase 3 — Retrieval (spec Section 8).  STATUS: IMPLEMENTED (deterministic mode).

Turns a query into a ranked, de-duplicated, provenance-tagged Evidence[] + a
coverage signal. Dual-mode: deterministic (default) router fan-out + union;
agentic (opt-in) schema-aware traverse — both funnel through the same
rerank -> coverage -> abstain spine. Does not generate the answer (Phase 4).
"""

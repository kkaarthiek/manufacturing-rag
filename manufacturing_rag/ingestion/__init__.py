"""
Phase 1 — Ingestion (spec Section 6).  STATUS: SKELETON.

Pipeline order (6.1), implemented incrementally:
   1 load master data (machines.json -> aliases + seed graph)   [master.py — DONE]
   2 detect format/encoding -> parse                            [parsers/    — stub]
   3 strip boilerplate                                          [clean.py    — stub]
   4 split multi-doc                                            [clean.py    — stub]
   5 OCR-noise correction                                       [clean.py    — stub]
   6 EXTRACT (one LLM pass -> many outputs)                     [extract.py  — stub]
   7 normalize units + formats                                  [transforms  — stub]
   8 resolve references -> canonical IDs                        [resolve.py  — stub]
   9 aggregate                                                  [transforms  — stub]
  10 dedup / conflict-flag                                      [transforms  — stub]
  11 version-tag                                                [versioning  — stub]
  12 build derived layers                                       [derive.py   — stub]
  13 verify & validate (loud halt on miss)                      [verify.py   — stub]

The gate (6.12): ingestion-fact recall = 1.0 vs INGESTION_GROUND_TRUTH.jsonl,
zero silent failures, every fact traceable.
"""

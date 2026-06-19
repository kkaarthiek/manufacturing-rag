"""
Phase 5 — Orchestration (spec Section 10).  STATUS: IMPLEMENTED.

Top-level coordinator for multi-part questions: decompose -> execute a sub-task
DAG (each sub-task = one Phase 3+4 pass) -> assemble. Simple questions skip it.

Reliability crux (the only reason this phase is allowed to exist): every
sub-answer passes the Phase-4 verifier BEFORE it is used as input to the next
step. The orchestrator chains VERIFIED FACTS, not LLM guesses — this is what
keeps decomposition from multiplying error (anti-pᴺ). It is an invariant, not a
nicety.
"""

from .plan import is_multipart, decompose
from .execute import execute_plan
from .compose import orchestrate

__all__ = ["is_multipart", "decompose", "execute_plan", "orchestrate"]

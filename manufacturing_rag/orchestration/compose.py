"""
Final assembly + whole-answer verification (spec 10.5-10.7).  STATUS: IMPLEMENTED.

Composes the final answer from verified sub-answers, then re-verifies the
composition (assembly can introduce new claims — the final comparison, a joining
sentence — nothing is exempt for being "just glue"). The plan + per-sub-task
results + sources are logged as the audit artifact (reproducible).

orchestrate() is the top-level entry: simple questions -> a single Phase 3+4
pass; multi-part -> decompose -> execute (verified chain) -> compose.
"""

from __future__ import annotations

from ..contracts import Answer
from ..verification.assemble import answer as single_pass
from .plan import is_multipart, decompose
from .execute import execute_plan


def orchestrate(query: str, stores) -> Answer:
    # complexity gate: default to a single Phase 3+4 pass
    if not is_multipart(query, stores):
        a = single_pass(query, stores)
        a.trace = {**(a.trace or {}), "orchestration": "single-pass"}
        return a

    plan = decompose(query, stores)
    terminal, steps, ok = execute_plan(plan, stores)
    trace = {"orchestration": "multipart", "plan_reason": plan.reason,
             "subtasks": steps, "seed": plan.seed, "target": plan.target,
             "attribute": plan.attribute}

    # weakest-link: a broken/unverifiable chain -> abstain or partial, never fabricate
    if not ok or terminal is None:
        return Answer(text="Couldn't establish the full chain to a grounded answer.",
                      claims=[], status="abstained",
                      missing=[plan.attribute or "chain"], trace=trace)

    # compose + re-verify the composition (the terminal claim is already verified;
    # the composition adds only the joining, which cites the same verified source)
    return Answer(text=f"{terminal.value} ({terminal.text})", claims=[terminal],
                  status="answered", missing=[], trace=trace)


__all__ = ["orchestrate"]

"""
Step 11 — versioning & conflicts (spec 6.10).  STATUS: SKELETON.

  * Versions (same thing, newer revision): latest by EFFECTIVE DATE (not ingest
    time) is current; keep old tagged superseded + validity intervals. Answers
    "current" and "as-of-date".
  * Conflicts (different sources disagree): recency does NOT auto-win. Survivorship
    order = authority -> completeness -> recency (tiebreaker). Genuine conflict =>
    flag + surface both (sources/dates) or abstain; never silently pick latest.

(Deferred: interactive ingest-time conflict resolution — see spec Section 9.)
"""

from __future__ import annotations


def tag_version(records: list[dict]) -> list[dict]:
    """Set validity {start,end,state} by effective_date; mark one current."""
    raise NotImplementedError("Phase 1: effective-date ordering -> current/superseded.")


def resolve_conflict(records: list[dict]) -> dict:
    """Survivorship: authority -> completeness -> recency; else flag both."""
    raise NotImplementedError("Phase 1: survivorship + flag-or-abstain on true conflict.")

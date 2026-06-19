"""
Core data contracts (spec Section 4) — FROZEN FIRST.

These are the seams between lanes. Parsers, extractors, resolvers, indexers and
the eval harness all speak in these objects, so any lane is swappable behind
them. Changing a contract is a deliberate, cross-cutting event — not a casual
edit.

Implementation notes:
  * Plain dataclasses (stdlib) with explicit fields matching the spec exactly.
  * Mutable containers use default_factory so empty objects are cheap to build.
  * `to_dict` / `from_dict` give stable JSON serialization for the stores and
    for the eval harness (which diffs against the gold sets).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Any


# --------------------------------------------------------------------------- #
# Spec Section 4 contracts
# --------------------------------------------------------------------------- #
@dataclass
class CanonicalDoc:
    """A validated document produced by Phase 1 ingestion."""
    id: str
    doc_type: str
    source_file: str
    format: str
    clean_text: str = ""
    structured_fields: dict = field(default_factory=dict)
    version: dict = field(default_factory=dict)        # {rev, effective_date, is_current}
    entities: list[str] = field(default_factory=list)  # canonical IDs mentioned
    provenance: dict = field(default_factory=dict)      # {file, page/section, char span}

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "CanonicalDoc": return _build(cls, d)


@dataclass
class StructuredRecord:
    """One exact-value row in the structured store."""
    table: str
    key: str
    fields: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)         # original, pre-normalization (KEPT)
    normalized: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)
    validity: dict = field(default_factory=dict)    # {start, end, state: current|superseded}
    source_doc_id: str = ""

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "StructuredRecord": return _build(cls, d)


@dataclass
class Entity:
    """A resolved node in the knowledge graph."""
    canonical_id: str
    type: str                                       # machine|part|supplier|line|program|material...
    aliases: list[str] = field(default_factory=list)
    attrs: dict = field(default_factory=dict)
    source_links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "Entity": return _build(cls, d)


@dataclass
class Edge:
    """A triple (subject, predicate, object) with provenance + trust.

    `properties` carries relation semantics (e.g. {transitive, symmetric,
    exclusive}) — the Phase-4 derived_logic verifier only applies transitivity/
    exclusion when the relation is *declared* to have it (relation-licensing)."""
    src: str
    rel: str
    dst: str
    properties: dict = field(default_factory=dict)
    source_doc_id: str = ""
    trust: float = 1.0

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "Edge": return _build(cls, d)


@dataclass
class DerivedUnit:
    """A proposition | hypothetical-question | summary. References its parent;
    never copies the parent's text into the canonical record."""
    id: str
    kind: str                                       # proposition|question|summary
    text: str
    parent_id: str = ""                             # reference, not a copy
    entities: list[str] = field(default_factory=list)
    source_span: dict = field(default_factory=dict)
    trust: float = 1.0
    verified: bool = False

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "DerivedUnit": return _build(cls, d)


# --------------------------------------------------------------------------- #
# Query-time contracts (Phases 3-5) — frozen ahead of retrieval (spec Section 4)
# --------------------------------------------------------------------------- #
@dataclass
class Evidence:
    """A retrieved item handed from Phase 3 (retrieval) to Phase 4."""
    id: str
    kind: str                                       # chunk|proposition|record|triple|summary
    content: object                                 # str | dict
    source: dict = field(default_factory=dict)      # doc_id, span/row, version, validity
    entities: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)      # {vector, bm25, rerank}
    trust: float = 1.0

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "Evidence": return _build(cls, d)


@dataclass
class Claim:
    """An atomic claim inside an answer, verified by its class (spec 9.5)."""
    text: str
    ctype: str                                      # verbatim|derived_calc|derived_logic|completeness|absence|entailment
    value: object = None
    operation: dict | None = None                   # op + operands(+sources) / proof chain
    citations: list[str] = field(default_factory=list)
    verified: bool = False

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "Claim": return _build(cls, d)


@dataclass
class SubTask:
    """One node in a Phase-5 decomposition DAG (one Phase 3+4 pass each)."""
    id: str
    question: str
    ttype: str                                      # lookup|traversal|calc|comparison|aggregation|absence
    deps: list[str] = field(default_factory=list)
    result: object = None                           # Answer | None

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "SubTask": return _build(cls, d)


@dataclass
class Answer:
    """A shipped answer, abstention, or partial — with full audit trace."""
    text: str
    claims: list = field(default_factory=list)      # list[Claim]
    status: str = "answered"                        # answered|abstained|partial
    missing: list[str] = field(default_factory=list)
    trace: dict = field(default_factory=dict)

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "Answer": return _build(cls, d)


# --------------------------------------------------------------------------- #
# Allowed vocabularies (validated by the harness / verify gate)
# --------------------------------------------------------------------------- #
DOC_TYPES = {
    "supplier", "part_spec", "sop", "work_order", "ncr", "quality_report",
    "standard", "purchase_order", "material_datasheet", "telemetry",
    "troubleshooting", "incident", "noise", "entity_graph", "uncategorized",
}
ENTITY_TYPES = {"machine", "part", "supplier", "line", "program", "material"}
DERIVED_KINDS = {"proposition", "question", "summary"}
VALIDITY_STATES = {"current", "superseded", "pending_review"}


def _build(cls, d: dict):
    """Tolerant constructor: ignores unknown keys, fills missing with defaults."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


CLAIM_TYPES = {"verbatim", "derived_calc", "derived_logic", "completeness",
               "absence", "entailment", "extrapolation"}
ANSWER_STATES = {"answered", "abstained", "partial"}

__all__ = [
    "CanonicalDoc", "StructuredRecord", "Entity", "Edge", "DerivedUnit",
    "Evidence", "Claim", "SubTask", "Answer",
    "DOC_TYPES", "ENTITY_TYPES", "DERIVED_KINDS", "VALIDITY_STATES",
    "CLAIM_TYPES", "ANSWER_STATES",
]

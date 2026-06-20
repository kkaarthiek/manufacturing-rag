"""
Config / model registry (spec Section 5).

Everything is config-driven so hosted<->local is a one-line change (spec Notes).
Defaults are PINNED here; the *final* pick is made by benchmarking on the gold
set (leaderboards don't transfer). `config/default.json` may override any field.

Reliability knobs (spec Section 0):
  * temperature is 0 for every LLM step.
  * self_consistency_n > 1: run N times, require agreement on extraction/verify.
  * provider_mode = "hosted" (always) — uses real OpenAI embeddings + LLM APIs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .. import REPO_ROOT, PACKAGE_ROOT

_HERE = Path(__file__).resolve().parent


def load_dotenv(path: str | Path | None = None) -> list[str]:
    """Load KEY=VALUE lines from .env into os.environ (stdlib; no python-dotenv).
    Existing env vars win (never overwritten). Returns the keys it set."""
    p = Path(path) if path else (REPO_ROOT / ".env")
    set_keys = []
    if not p.exists():
        return set_keys
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            set_keys.append(k)
    return set_keys

# Candidate models to benchmark on-corpus before committing (spec Section 5).
MODEL_REGISTRY = {
    "embeddings": {
        # CHOSEN: openai:text-embedding-3-large (3072-d). Key via OPENAI_API_KEY env.
        "hosted": ["openai:text-embedding-3-large", "openai:text-embedding-3-small",
                   "voyage-4", "gemini-embedding-2", "cohere-embed-v4"],
        "local": ["qwen3-embedding", "llama-embed-nemotron-8b", "bge-m3"],
    },
    "reranker": {
        "hosted": ["cohere-rerank-3.5", "zerank-2"],
        "local": ["bge-reranker-v2-m3"],
    },
    "llm": {
        # CHOSEN: gpt-4o (OpenAI) or claude-haiku-4-5 (Anthropic). Key via API env vars.
        "hosted": ["gpt-4o", "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-8"],
        "local": [],
    },
}


@dataclass
class Paths:
    repo_root: str = str(REPO_ROOT)
    corpus: str = str(REPO_ROOT / "corpus.jsonl")
    raw_dir: str = str(REPO_ROOT / "raw")
    ingestion_ground_truth: str = str(REPO_ROOT / "raw" / "INGESTION_GROUND_TRUTH.jsonl")
    question_gold: str = str(REPO_ROOT / "questions.jsonl")
    artifacts: str = str(PACKAGE_ROOT / "_artifacts")  # built stores live here
    qdrant_path: str = str(PACKAGE_ROOT / "_artifacts" / "qdrant")  # Qdrant on-disk storage
    neo4j_uri: str = "bolt://localhost:7687"   # override with NEO4J_URI env var
    neo4j_user: str = "neo4j"                  # override with NEO4J_USER env var
    neo4j_password: str = "password"           # override with NEO4J_PASSWORD env var


@dataclass
class Models:
    provider_mode: str = "hosted"             # always hosted; kept for config compatibility
    embeddings: str = "openai:text-embedding-3-large"
    embedding_dim: int = 3072
    reranker: str = "llm"
    llm: str = "gpt-4o"
    vector_store: str = "qdrant"              # flat (in-memory) | qdrant (persistent DB)
    graph_store: str = "memory"               # memory (in-memory+JSON) | neo4j (persistent DB)
    temperature: float = 0.0                  # spec: every LLM step at temp 0
    self_consistency_n: int = 3               # N runs, require agreement


@dataclass
class Thresholds:
    recall_ks: list[int] = field(default_factory=lambda: [1, 3, 5, 10])
    abstain_score: float = 1.0                # legacy rerank-score gate
    coverage_threshold: float = 0.34          # coarse Phase-3 gate; Phase-4 absence/grounding verifiers refine
    self_consistency_agreement: float = 1.0   # require unanimous agreement
    ingestion_recall_target: float = 1.0      # Phase 1 gate
    index_coverage_target: float = 1.0        # Phase 2 gate
    retrieval_recall_target: float = 1.0      # driven toward 1.0 on gold


@dataclass
class Config:
    paths: Paths = field(default_factory=Paths)
    models: Models = field(default_factory=Models)
    thresholds: Thresholds = field(default_factory=Thresholds)

    def to_dict(self) -> dict:
        return {"paths": asdict(self.paths), "models": asdict(self.models),
                "thresholds": asdict(self.thresholds)}


def load_config(path: str | Path | None = None) -> Config:
    """Load defaults, then overlay config/default.json (or a given path).
    Also loads .env so OPENAI_API_KEY / ANTHROPIC_API_KEY are available."""
    load_dotenv()
    cfg = Config()
    override = Path(path) if path else (_HERE / "default.json")
    if override.exists():
        data = json.loads(override.read_text(encoding="utf-8"))
        for section in ("paths", "models", "thresholds"):
            for k, v in (data.get(section) or {}).items():
                if hasattr(getattr(cfg, section), k):
                    setattr(getattr(cfg, section), k, v)
    # env vars override config for Neo4j credentials
    for env, attr in (("NEO4J_URI", "neo4j_uri"), ("NEO4J_USER", "neo4j_user"),
                      ("NEO4J_PASSWORD", "neo4j_password")):
        val = os.environ.get(env)
        if val:
            setattr(cfg.paths, attr, val)
    return cfg


__all__ = ["Config", "Paths", "Models", "Thresholds", "MODEL_REGISTRY", "load_config"]

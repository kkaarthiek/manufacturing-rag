"""
manufacturing_rag — reliability-first RAG over a manufacturing corpus.

Build status (per the Phases 0-2 spec):
  Phase 0 (Foundations) ...... IMPLEMENTED  (contracts + eval harness + config + skeleton)
  Phase 1 (Ingestion) ........ SKELETON     (conformant stubs behind the contracts)
  Phase 2 (Indexing) ......... SKELETON     (store interfaces, offline-default)

Design rule honored everywhere: every model/store is a PROVIDER behind an
interface; the default providers are deterministic + offline (stdlib only), and
swapping to hosted models (Voyage/Cohere/Neo4j/...) is a CONFIG change, never a
code change. See config.py and providers.py.
"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent  # where corpus.jsonl / raw/ / questions.jsonl live

__all__ = ["PACKAGE_ROOT", "REPO_ROOT"]

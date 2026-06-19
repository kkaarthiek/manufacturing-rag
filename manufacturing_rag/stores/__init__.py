"""
Store clients (spec Section 8).  STATUS: SKELETON.

Thin connectors to the four stores + originals + resolution index. Connectors to
LIVE operational sources are READ-ONLY (spec Notes; spec principle #5: live data
is queried live, never served from a stale snapshot). Offline default keeps
everything local (json/sqlite/in-memory); hosted is a config swap.
"""

from ..indexing.vector import FlatVectorIndex
from ..indexing.structured import StructuredStore
from ..indexing.graph import GraphStore

__all__ = ["FlatVectorIndex", "StructuredStore", "GraphStore"]

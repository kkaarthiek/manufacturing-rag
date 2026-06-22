"""
Vector index (spec 7.1, 7.3).

FlatVectorIndex   — brute-force cosine in-memory (fallback; no extra deps).
QdrantVectorStore — persistent on-disk Qdrant collection (no server needed).
                    Activated when models.vector_store = 'qdrant' in config.
                    Replaces the large text_index.json with a proper vector DB;
                    BM25 state stays in-memory (TextIndex handles that).
"""

from __future__ import annotations

import hashlib
import math

from ..providers import Embedder


class FlatVectorIndex:
    """Exact (brute-force) cosine index — the accurate default at this scale."""
    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.ids: list[str] = []
        self.vecs: list[list[float]] = []
        self.meta: list[dict] = []

    def add(self, unit_id: str, text: str, metadata: dict):
        self.ids.append(unit_id)
        self.vecs.append(self.embedder.embed([text])[0])
        self.meta.append(metadata)

    def search(self, query: str, k: int = 10):
        if not self.vecs:
            return []
        q = self.embedder.embed([query])[0]
        sims = [(self.ids[i], sum(a * b for a, b in zip(q, v)))
                for i, v in enumerate(self.vecs)]
        sims.sort(key=lambda x: x[1], reverse=True)
        return sims[:k]


class QdrantVectorStore:
    """Persistent Qdrant vector store — local on-disk, no server required.

    Uses cosine distance to match the existing flat index behaviour.
    Point IDs are stable uint64 hashes of the unit_id string so upserts are
    idempotent across rebuilds. The original string uid is stored in the
    point payload under '_uid' and returned by search().
    """

    def __init__(self, path: str, collection: str, dim: int):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self.dim = dim
        self.collection = collection
        self.client = QdrantClient(path=path)
        existing = {c.name for c in self.client.get_collections().collections}
        if collection not in existing:
            self.client.create_collection(
                collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert(self, uid: str, vec: list[float], payload: dict):
        from qdrant_client.models import PointStruct
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(
                id=self._uid_to_int(uid),
                vector=vec,
                payload={**payload, "_uid": uid},
            )],
        )

    def upsert_batch(self, uids: list[str], vecs: list[list[float]],
                     payloads: list[dict], batch: int = 128):
        from qdrant_client.models import PointStruct
        for i in range(0, len(uids), batch):
            points = [
                PointStruct(id=self._uid_to_int(uid), vector=vec,
                            payload={**pay, "_uid": uid})
                for uid, vec, pay in zip(uids[i:i+batch], vecs[i:i+batch],
                                         payloads[i:i+batch])
            ]
            self.client.upsert(collection_name=self.collection, points=points)

    def search(self, query_vec: list[float], k: int) -> list[tuple[str, float]]:
        # qdrant-client 1.x uses query_points() — .search() was removed in 1.0
        result = self.client.query_points(
            collection_name=self.collection,
            query=query_vec,
            limit=k,
        )
        return [(p.payload["_uid"], p.score) for p in result.points]

    def count(self) -> int:
        return self.client.count(self.collection).count

    def delete(self, uids: list[str]):
        """Delete points by their string uids (mapped to stable int ids)."""
        from qdrant_client.models import PointIdsList
        ids = [self._uid_to_int(u) for u in uids]
        if ids:
            self.client.delete(collection_name=self.collection,
                               points_selector=PointIdsList(points=ids))

    @staticmethod
    def _uid_to_int(uid: str) -> int:
        """Stable unsigned 64-bit int from a string uid (Qdrant point ID)."""
        return int.from_bytes(
            hashlib.sha256(uid.encode()).digest()[:8], "big"
        ) >> 1


__all__ = ["FlatVectorIndex", "QdrantVectorStore"]

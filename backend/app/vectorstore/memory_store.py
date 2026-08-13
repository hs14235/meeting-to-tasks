from typing import List, Dict, Any, Optional, Tuple

from .base import VectorStore

class MemoryStore(VectorStore):
    """
    In-memory fallback: perfect for getting started.
    """
    def __init__(self):
        self._ids: List[str] = []
        self._vecs: List[List[float]] = []
        self._meta: List[Dict[str, Any]] = []

    def upsert(self, ids, embeddings, metas):
        incoming = set(ids)
        keep = [index for index, record_id in enumerate(self._ids) if record_id not in incoming]
        self._ids = [self._ids[index] for index in keep] + list(ids)
        self._vecs = [self._vecs[index] for index in keep] + list(embeddings)
        self._meta = [self._meta[index] for index in keep] + list(metas)

    def delete(self, filters):
        keep = [
            index
            for index, meta in enumerate(self._meta)
            if any(meta.get(key) != value for key, value in filters.items())
        ]
        removed = len(self._ids) - len(keep)
        self._ids = [self._ids[index] for index in keep]
        self._vecs = [self._vecs[index] for index in keep]
        self._meta = [self._meta[index] for index in keep]
        return removed

    def query(self, embedding, k=5, filters=None):
        if not self._ids:
            return []
        # cosine since vectors are normalized: score = dot(q, v)
        scores = [sum(a*b for a, b in zip(embedding, vec)) for vec in self._vecs]
        order = sorted(range(len(self._ids)), key=lambda i: -scores[i])
        out = []
        for i in order:
            m = self._meta[i]
            if filters and any(m.get(k) != v for k, v in (filters or {}).items()):
                continue
            out.append((self._ids[i], float(scores[i]), m))
            if len(out) >= k:
                break
        return out

    def persist(self):
        # no-op for MVP
        pass

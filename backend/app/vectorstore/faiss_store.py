try:
    import faiss  # type: ignore
except Exception:
    faiss = None

import json
import os
from typing import Any, Dict, List

import numpy as np

from .base import VectorStore


class FaissStore(VectorStore):
    def __init__(self, dim: int, index_path: str, meta_path: str):
        self.dim, self.index_path, self.meta_path = dim, index_path, meta_path
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        self.ids: List[str] = []
        self.id_to_meta: Dict[str, Any] = {}
        if faiss and os.path.exists(index_path) and os.path.exists(meta_path):
            self.index = faiss.read_index(index_path)
            with open(meta_path, "r", encoding="utf-8") as handle:
                meta = json.load(handle)
            self.ids = meta["ids"]
            self.id_to_meta = meta["id_to_meta"]
        else:
            self.index = faiss.IndexFlatIP(dim) if faiss else None

    def _norm(self, matrix):
        matrix = np.asarray(matrix, dtype="float32")
        norm = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
        return (matrix / norm).astype("float32")

    def upsert(self, ids, embeddings, metas):
        if not faiss or self.index is None:
            raise RuntimeError("FAISS not available")
        matrix = self._norm(embeddings)
        self.index.add(matrix)
        self.ids.extend(ids)
        for i, record_id in enumerate(ids):
            self.id_to_meta[record_id] = metas[i]

    def delete(self, filters):
        if not faiss or self.index is None:
            return 0
        keep_indexes = [
            index
            for index, record_id in enumerate(self.ids)
            if any(self.id_to_meta.get(record_id, {}).get(key) != value for key, value in filters.items())
        ]
        removed = len(self.ids) - len(keep_indexes)
        if not removed:
            return 0

        vectors = [self.index.reconstruct(index) for index in keep_indexes]
        kept_ids = [self.ids[index] for index in keep_indexes]
        self.index = faiss.IndexFlatIP(self.dim)
        if vectors:
            self.index.add(self._norm(vectors))
        self.ids = kept_ids
        self.id_to_meta = {record_id: self.id_to_meta[record_id] for record_id in kept_ids}
        return removed

    def query(self, embedding, k=5, filters=None):
        if not faiss or self.index is None or not self.ids:
            return []
        query = self._norm([embedding])
        # Filtering after a global top-k can hide valid meeting-local hits.
        candidate_count = len(self.ids) if filters else min(k, len(self.ids))
        scores, idxs = self.index.search(query, candidate_count)
        out = []
        for idx, score in zip(idxs[0], scores[0]):
            record_id = self.ids[idx]
            meta = self.id_to_meta.get(record_id, {})
            if filters and any(meta.get(key) != value for key, value in (filters or {}).items()):
                continue
            out.append((record_id, float(score), meta))
            if len(out) >= k:
                break
        return out

    def persist(self):
        if not faiss or self.index is None:
            return
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as handle:
            json.dump({"ids": self.ids, "id_to_meta": self.id_to_meta}, handle)

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from ..chunking import CHUNKING_VERSION, to_chunk_records
from ..config import RETRIEVAL_THRESHOLD
from ..storage import (
    delete_meeting,
    get_meeting,
    list_meetings,
    load_chunks,
    load_task_drafts,
    save_meeting,
    save_task_drafts,
)
from ..vectorstore.base import VectorStore
from .errors import ServiceError
from .shared import SUPPORTED_TRANSCRIPT_EXTENSIONS, build_chunk_id, validate_meeting_id

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass
class MeetingContext:
    idxs: list[int]
    chunks: list[dict[str, Any]]
    texts: list[str]
    retrieval_ms: float = 0.0


def _tokens(text: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(text.lower()))


class MeetingService:
    def __init__(self, store: VectorStore, embed_model: str, embedder) -> None:
        self.store = store
        self.embed_model = embed_model
        self.embedder = embedder

    def validate_upload_filename(self, filename: str | None) -> str:
        ext = Path(filename or "").suffix.lower()
        if ext in SUPPORTED_TRANSCRIPT_EXTENSIONS:
            return ext
        allowed = ", ".join(sorted(SUPPORTED_TRANSCRIPT_EXTENSIONS))
        raise ServiceError(
            status_code=400,
            where="client",
            error=f"Unsupported file type. Upload a UTF-8 {allowed} transcript.",
        )

    def validate_meeting_id(self, meeting_id: str) -> str:
        return validate_meeting_id(meeting_id)

    def decode_upload_text(self, filename: str | None, raw_bytes: bytes) -> str:
        self.validate_upload_filename(filename)
        try:
            raw = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ServiceError(status_code=400, where="client", error="Transcript must be UTF-8 encoded text.") from exc
        if not raw.strip():
            raise ServiceError(status_code=400, where="client", error="Transcript is empty.")
        return raw

    def index_meeting_text(self, meeting_id: str, title: str, raw_text: str) -> dict[str, Any]:
        started = perf_counter()
        self.validate_meeting_id(meeting_id)
        if not raw_text.strip():
            raise ServiceError(status_code=400, where="client", error="Transcript is empty.")

        meeting_title = title.strip() or meeting_id
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        existing = get_meeting(meeting_id, include_transcript=False)
        if (
            existing
            and existing["content_hash"] == content_hash
            and existing["embed_model"] == self.embed_model
            and existing["chunking_version"] == CHUNKING_VERSION
            and existing["title"] == meeting_title
        ):
            return {
                "ok": True,
                "chunks_indexed": existing["chunk_count"],
                "reindexed": False,
                "content_hash": content_hash[:12],
                "timings": {"total_ms": round((perf_counter() - started) * 1000, 2)},
            }

        chunks = to_chunk_records(raw_text)
        texts = [chunk["text"] for chunk in chunks]
        metas = [
            {
                "meeting_id": meeting_id,
                "title": title,
                "i": chunk["i"],
                "speaker": chunk.get("speaker"),
                "timestamp": chunk.get("timestamp"),
                "start_line": chunk["start_line"],
                "embed_model": self.embed_model,
                "chunking_version": CHUNKING_VERSION,
                "content_hash": content_hash,
            }
            for chunk in chunks
        ]
        ids = [
            build_chunk_id(texts[index], {"meeting_id": meeting_id, "i": chunks[index]["i"]})
            for index in range(len(chunks))
        ]

        embed_started = perf_counter()
        vectors = self.embedder(texts, self.embed_model)
        embed_ms = (perf_counter() - embed_started) * 1000

        self.store.delete({"meeting_id": meeting_id})
        self.store.upsert(ids, vectors, metas)
        self.store.persist()
        save_meeting(
            meeting_id,
            meeting_title,
            raw_text,
            chunks,
            content_hash=content_hash,
            embed_model=self.embed_model,
            chunking_version=CHUNKING_VERSION,
        )
        return {
            "ok": True,
            "chunks_indexed": len(chunks),
            "reindexed": existing is not None,
            "content_hash": content_hash[:12],
            "timings": {
                "embedding_ms": round(embed_ms, 2),
                "total_ms": round((perf_counter() - started) * 1000, 2),
            },
        }

    def index_upload(self, meeting_id: str, title: str, filename: str | None, raw_bytes: bytes) -> dict[str, Any]:
        return self.index_meeting_text(meeting_id, title, self.decode_upload_text(filename, raw_bytes))

    def list(self) -> dict[str, Any]:
        return {"meetings": list_meetings()}

    def get(self, meeting_id: str) -> dict[str, Any]:
        self.validate_meeting_id(meeting_id)
        meeting = get_meeting(meeting_id)
        if meeting is None:
            raise ServiceError(status_code=404, where="client", error=f'Meeting "{meeting_id}" was not found.')
        meeting["chunks"] = load_chunks(meeting_id)
        meeting["tasks"] = load_task_drafts(meeting_id)
        return meeting

    def delete(self, meeting_id: str) -> dict[str, Any]:
        self.validate_meeting_id(meeting_id)
        removed = delete_meeting(meeting_id)
        self.store.delete({"meeting_id": meeting_id})
        self.store.persist()
        if not removed:
            raise ServiceError(status_code=404, where="client", error=f'Meeting "{meeting_id}" was not found.')
        return {"ok": True, "deleted": meeting_id}

    def update_drafts(self, meeting_id: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        self.validate_meeting_id(meeting_id)
        if get_meeting(meeting_id, include_transcript=False) is None:
            raise ServiceError(status_code=404, where="client", error=f'Meeting "{meeting_id}" was not found.')
        save_task_drafts(meeting_id, tasks)
        return {"ok": True, "tasks": load_task_drafts(meeting_id)}

    def search(self, meeting_id: str, q: str, k: int = 5) -> dict[str, Any]:
        started = perf_counter()
        self.validate_meeting_id(meeting_id)
        chunks = load_chunks(meeting_id)
        if not chunks:
            raise ServiceError(
                status_code=404,
                where="client",
                error=f'Meeting "{meeting_id}" was not found. Upload and index it first.',
            )

        embed_started = perf_counter()
        query_vector = self.embedder([q], self.embed_model)[0]
        embedding_ms = (perf_counter() - embed_started) * 1000
        vector_hits = self.store.query(query_vector, k=max(k * 3, 10), filters={"meeting_id": meeting_id})
        vector_scores = {int(meta["i"]): max(0.0, (score + 1.0) / 2.0) for _, score, meta in vector_hits}

        query_tokens = _tokens(q)
        ranked: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk_tokens = _tokens(chunk["text"])
            overlap = len(query_tokens & chunk_tokens)
            lexical = overlap / math.sqrt(max(1, len(query_tokens) * len(chunk_tokens)))
            vector = vector_scores.get(chunk["i"], 0.0)
            hybrid = 0.72 * vector + 0.28 * lexical
            ranked.append(
                {
                    "id": build_chunk_id(chunk["text"], {"meeting_id": meeting_id, "i": chunk["i"]}),
                    "score": round(hybrid, 4),
                    "vector_score": round(vector, 4),
                    "lexical_score": round(lexical, 4),
                    "text": chunk["text"],
                    "source": {
                        "meeting_id": meeting_id,
                        "chunk_i": chunk["i"],
                        "speaker": chunk.get("speaker"),
                        "timestamp": chunk.get("timestamp"),
                        "start_line": chunk.get("start_line"),
                    },
                    "meta": {"meeting_id": meeting_id, "i": chunk["i"]},
                }
            )

        ranked.sort(key=lambda item: (-item["score"], item["source"]["chunk_i"]))
        qualifying = [item for item in ranked if item["score"] >= RETRIEVAL_THRESHOLD]
        results = (qualifying or ranked[:1])[:k]
        return {
            "results": results,
            "retrieval": {
                "strategy": "hybrid-vector-lexical",
                "threshold": RETRIEVAL_THRESHOLD,
                "candidate_count": len(ranked),
            },
            "timings": {
                "embedding_ms": round(embedding_ms, 2),
                "retrieval_ms": round((perf_counter() - started) * 1000, 2),
            },
        }

    def load_context(self, meeting_id: str, q: str, k: int) -> MeetingContext:
        result = self.search(meeting_id, q, k)
        chunks = [
            {
                "i": item["source"]["chunk_i"],
                "text": item["text"],
                "speaker": item["source"].get("speaker"),
                "timestamp": item["source"].get("timestamp"),
                "start_line": item["source"].get("start_line"),
            }
            for item in result["results"]
        ]
        return MeetingContext(
            idxs=[chunk["i"] for chunk in chunks],
            chunks=chunks,
            texts=[chunk["text"] for chunk in chunks],
            retrieval_ms=result["timings"]["retrieval_ms"],
        )

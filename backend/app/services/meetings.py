from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from ..chunking import to_chunks
from ..storage import load_chunks, save_meeting
from ..vectorstore.base import VectorStore
from .errors import ServiceError
from .shared import SUPPORTED_TRANSCRIPT_EXTENSIONS, build_chunk_id, validate_meeting_id


@dataclass
class MeetingContext:
    idxs: List[int]
    chunks: List[Dict[str, Any]]
    texts: List[str]


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
            raise ServiceError(
                status_code=400,
                where="client",
                error="Transcript must be UTF-8 encoded text.",
            ) from exc

        if not raw.strip():
            raise ServiceError(
                status_code=400,
                where="client",
                error="Transcript is empty.",
            )
        return raw

    def index_meeting_text(self, meeting_id: str, title: str, raw_text: str) -> Dict[str, Any]:
        self.validate_meeting_id(meeting_id)
        if not raw_text.strip():
            raise ServiceError(status_code=400, where="client", error="Transcript is empty.")

        chunks = to_chunks(raw_text)
        save_meeting(meeting_id, title, raw_text, chunks)

        metas = [{"meeting_id": meeting_id, "title": title, "i": i} for i, _ in enumerate(chunks)]
        ids = [build_chunk_id(chunks[i], metas[i]) for i in range(len(chunks))]
        vecs = self.embedder(chunks, self.embed_model)
        self.store.upsert(ids, vecs, metas)
        self.store.persist()
        return {"ok": True, "chunks_indexed": len(chunks)}

    def index_upload(self, meeting_id: str, title: str, filename: str | None, raw_bytes: bytes) -> Dict[str, Any]:
        raw_text = self.decode_upload_text(filename, raw_bytes)
        return self.index_meeting_text(meeting_id, title, raw_text)

    def search(self, meeting_id: str, q: str, k: int = 5) -> Dict[str, Any]:
        self.validate_meeting_id(meeting_id)
        qvec = self.embedder([q], self.embed_model)[0]
        results = self.store.query(qvec, k=k, filters={"meeting_id": meeting_id})
        return {"results": [{"id": record_id, "score": score, "meta": meta} for record_id, score, meta in results]}

    def load_context(self, meeting_id: str, q: str, k: int) -> MeetingContext:
        self.validate_meeting_id(meeting_id)
        all_chunks = load_chunks(meeting_id)
        if not all_chunks:
            raise ServiceError(
                status_code=404,
                where="client",
                error=f'Meeting "{meeting_id}" was not found. Upload and index it first.',
            )

        qvec = self.embedder([q], self.embed_model)[0]
        hits = self.store.query(qvec, k=k, filters={"meeting_id": meeting_id})
        idxs = [int(hit[2]["i"]) for hit in hits if hit[2].get("i") is not None]
        if not idxs:
            idxs = [chunk["i"] for chunk in all_chunks[:k]]

        chunk_by_i = {chunk["i"]: chunk for chunk in all_chunks}
        context_chunks = [chunk_by_i[idx] for idx in idxs if idx in chunk_by_i]
        if not context_chunks:
            context_chunks = all_chunks[:k]
            idxs = [chunk["i"] for chunk in context_chunks]

        return MeetingContext(idxs=idxs, chunks=context_chunks, texts=[chunk["text"] for chunk in context_chunks])

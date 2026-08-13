from pathlib import Path

import pytest

from app import storage
from app.chunking import to_chunk_records
from app.embeddings import embed_texts_hash
from app.services.errors import ServiceError
from app.services.issues import IssueService
from app.services.meetings import MeetingService
from app.vectorstore.memory_store import MemoryStore


@pytest.fixture
def service(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage, "DATA_ROOT", tmp_path)
    return MeetingService(MemoryStore(), "hash-v1", embed_texts_hash)


def test_reindex_is_idempotent_and_replaces_stale_vectors(service):
    first = service.index_meeting_text("weekly", "Weekly", "Action: Sam to ship the API docs.")
    first_ids = list(service.store._ids)
    unchanged = service.index_meeting_text("weekly", "Weekly", "Action: Sam to ship the API docs.")

    assert first["reindexed"] is False
    assert unchanged["reindexed"] is False
    assert service.store._ids == first_ids

    changed = service.index_meeting_text("weekly", "Weekly", "Action: Lee to verify the mobile layout.")

    assert changed["reindexed"] is True
    assert len(service.store._ids) == 1
    assert service.store._ids != first_ids
    assert storage.load_chunks("weekly")[0]["text"].startswith("Action: Lee")


def test_hybrid_search_returns_exact_source_evidence(service):
    service.index_meeting_text(
        "launch",
        "Launch review",
        "[09:02] Maya: Action: finalize the launch checklist by Friday.\n"
        "[09:05] Jordan: Decision: use blue for the approval state.\n"
        "[09:08] Priya: Blocker: retrieval benchmark coverage is missing.",
    )

    result = service.search("launch", "retrieval benchmark", k=2)

    assert result["results"][0]["source"]["meeting_id"] == "launch"
    assert "retrieval benchmark" in result["results"][0]["text"].lower()
    assert result["results"][0]["id"] in service.store._ids
    assert result["results"][0]["score"] >= result["results"][1]["score"]
    assert result["retrieval"]["strategy"] == "hybrid-vector-lexical"


def test_delete_removes_relational_and_vector_state(service):
    service.index_meeting_text("retro", "Retro", "Action: Alex to close the follow-up.")

    assert service.delete("retro") == {"ok": True, "deleted": "retro"}
    assert storage.get_meeting("retro") is None
    assert service.store._ids == []

    with pytest.raises(ServiceError) as exc:
        service.get("retro")
    assert exc.value.status_code == 404


def test_chunking_preserves_speaker_timestamp_and_overlap():
    speaker_record = to_chunk_records("[09:00] Maya: Action: publish the report.")[0]
    first_line = " ".join(f"first{i}" for i in range(100))
    overlap_line = " ".join(f"overlap{i}" for i in range(80))
    records = to_chunk_records(
        f"{first_line}\n{overlap_line}\nAction: publish the report.", overlap_lines=1
    )

    assert speaker_record["speaker"] == "Maya"
    assert speaker_record["timestamp"] == "09:00"
    assert records[0]["text"].endswith(overlap_line)
    assert records[1]["text"].startswith(overlap_line)
    assert records[1]["start_line"] == 2


@pytest.mark.anyio
async def test_public_demo_mode_blocks_external_writes():
    with pytest.raises(ServiceError) as exc:
        await IssueService(public_demo_mode=True).create_issues(
            "owner/repo", "meeting", [{"title": "Do work", "body": "Safely"}]
        )

    assert exc.value.status_code == 403
    assert "preview-only" in exc.value.detail["error"]

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main, storage
from app.services.errors import ServiceError
from app.services.issues import IssueService
from app.services.meetings import MeetingService
from app.services.shared import normalize_tasks


class DummyStore:
    def __init__(self):
        self.upserts = []

    def upsert(self, ids, embeddings, metas):
        self.upserts.append((ids, embeddings, metas))

    def persist(self):
        return None

    def query(self, embedding, k=5, filters=None):
        return []


class DummyMeetingService:
    def __init__(self):
        self.calls = []

    def index_upload(self, meeting_id, title, filename, raw_bytes):
        self.calls.append((meeting_id, title, filename, raw_bytes))
        return {"ok": True, "chunks_indexed": 1}


def test_normalize_tasks_maps_retrieved_positions_to_global_chunk_indexes():
    tasks = [{"title": "Ship it", "body": "Close the loop", "source_i": 1}]

    normalized = normalize_tasks(tasks, [4, 9])

    assert normalized[0]["source_i"] == 9
    assert normalized[0]["labels"] == ["meeting-action"]


def test_validate_upload_filename_rejects_unsupported_files():
    service = MeetingService(store=DummyStore(), embed_model="test-model", embedder=lambda texts, name: texts)

    with pytest.raises(ServiceError) as exc:
        service.validate_upload_filename("notes.pdf")

    assert exc.value.status_code == 400
    assert "UTF-8" in exc.value.detail["error"]


def test_validate_meeting_id_rejects_path_traversal():
    service = MeetingService(store=DummyStore(), embed_model="test-model", embedder=lambda texts, name: texts)

    with pytest.raises(ServiceError) as exc:
        service.validate_meeting_id("../outside-data-root")

    assert exc.value.status_code == 400
    assert "Invalid meeting_id" in exc.value.detail["error"]


def test_issue_preview_rejects_meeting_id_path_traversal():
    with pytest.raises(ServiceError) as exc:
        IssueService().preview_issues("owner/repo", "../outside-data-root", [])

    assert exc.value.status_code == 400


def test_index_upload_accepts_utf8_text_files(monkeypatch, tmp_path: Path):
    service = MeetingService(
        store=DummyStore(),
        embed_model="test-model",
        embedder=lambda texts, name: [[0.1] * 384 for _ in texts],
    )
    monkeypatch.setattr(storage, "DATA_ROOT", tmp_path)

    result = service.index_upload(
        "mtg-123",
        "Weekly sync",
        "meeting.txt",
        b"Action: Hamza to polish the setup docs.",
    )

    assert result["chunks_indexed"] == 1
    assert service.store.upserts
    assert (tmp_path / "meetings" / "mtg-123" / "chunks.json").exists()


def test_upload_route_delegates_to_meeting_service(monkeypatch):
    dummy_service = DummyMeetingService()
    monkeypatch.setattr(main, "meeting_service", dummy_service)

    client = TestClient(main.app)
    response = client.post(
        "/upload",
        data={"meeting_id": "mtg-123", "title": "Weekly sync"},
        files={"file": ("meeting.txt", b"Action: Hamza to polish the setup docs.", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["chunks_indexed"] == 1
    assert dummy_service.calls[0][0] == "mtg-123"
    assert dummy_service.calls[0][2] == "meeting.txt"

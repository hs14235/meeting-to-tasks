from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_ROOT = Path(os.getenv("DATA_DIR", "../data")).resolve()
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return DATA_ROOT / "meeting_to_tasks.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embed_model TEXT NOT NULL,
            chunking_version TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transcript_chunks (
            meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            speaker TEXT,
            timestamp TEXT,
            start_line INTEGER NOT NULL,
            PRIMARY KEY (meeting_id, chunk_index)
        );
        CREATE TABLE IF NOT EXISTS task_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            labels_json TEXT NOT NULL,
            assignee_hint TEXT,
            due_hint TEXT,
            source_i INTEGER NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (meeting_id, ordinal)
        );
        CREATE TABLE IF NOT EXISTS issue_publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT,
            repo TEXT NOT NULL,
            task_title TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            issue_number INTEGER,
            issue_url TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    return connection


def get_meeting(meeting_id: str, include_transcript: bool = True) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if row is None:
            return None
        meeting = dict(row)
        if not include_transcript:
            meeting.pop("raw_text", None)
        return meeting


def list_meetings(limit: int = 25) -> list[dict[str, Any]]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            """SELECT id, title, chunk_count, embed_model, chunking_version, created_at, updated_at
               FROM meetings ORDER BY updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def save_meeting(
    meeting_id: str,
    title: str,
    raw_text: str,
    chunks: list[dict[str, Any]],
    *,
    content_hash: str,
    embed_model: str,
    chunking_version: str,
) -> None:
    timestamp = _now()
    existing = get_meeting(meeting_id, include_transcript=False)
    created_at = existing["created_at"] if existing else timestamp
    with closing(_connect()) as connection, connection:
        connection.execute(
            """INSERT OR REPLACE INTO meetings
               (id, title, raw_text, content_hash, embed_model, chunking_version, chunk_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                meeting_id,
                title,
                raw_text,
                content_hash,
                embed_model,
                chunking_version,
                len(chunks),
                created_at,
                timestamp,
            ),
        )
        connection.execute("DELETE FROM transcript_chunks WHERE meeting_id = ?", (meeting_id,))
        connection.executemany(
            """INSERT INTO transcript_chunks
               (meeting_id, chunk_index, text, speaker, timestamp, start_line)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    meeting_id,
                    chunk["i"],
                    chunk["text"],
                    chunk.get("speaker"),
                    chunk.get("timestamp"),
                    chunk.get("start_line", 0),
                )
                for chunk in chunks
            ],
        )
        connection.execute("DELETE FROM task_drafts WHERE meeting_id = ?", (meeting_id,))


def load_chunks(meeting_id: str) -> list[dict[str, Any]]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            """SELECT chunk_index AS i, text, speaker, timestamp, start_line
               FROM transcript_chunks WHERE meeting_id = ? ORDER BY chunk_index""",
            (meeting_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def save_task_drafts(meeting_id: str, tasks: list[dict[str, Any]]) -> None:
    timestamp = _now()
    with closing(_connect()) as connection, connection:
        connection.execute("DELETE FROM task_drafts WHERE meeting_id = ?", (meeting_id,))
        connection.executemany(
            """INSERT INTO task_drafts
               (meeting_id, ordinal, title, body, labels_json, assignee_hint, due_hint,
                source_i, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    meeting_id,
                    index,
                    task.get("title", ""),
                    task.get("body", ""),
                    json.dumps(task.get("labels", ["meeting-action"])),
                    task.get("assignee_hint"),
                    task.get("due_hint"),
                    int(task.get("source_i", 0)),
                    float(task.get("confidence", 0.7)),
                    timestamp,
                    timestamp,
                )
                for index, task in enumerate(tasks)
            ],
        )


def load_task_drafts(meeting_id: str) -> list[dict[str, Any]]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM task_drafts WHERE meeting_id = ? ORDER BY ordinal", (meeting_id,)
        ).fetchall()
        return [
            {
                "title": row["title"],
                "body": row["body"],
                "labels": json.loads(row["labels_json"]),
                "assignee_hint": row["assignee_hint"],
                "due_hint": row["due_hint"],
                "source_i": row["source_i"],
                "confidence": row["confidence"],
            }
            for row in rows
        ]


def record_publication(
    meeting_id: str | None,
    repo: str,
    title: str,
    fingerprint: str,
    status: str,
    issue_number: int | None = None,
    issue_url: str | None = None,
) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            """INSERT INTO issue_publications
               (meeting_id, repo, task_title, fingerprint, issue_number, issue_url, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (meeting_id, repo, title, fingerprint, issue_number, issue_url, status, _now()),
        )


def delete_meeting(meeting_id: str) -> bool:
    with closing(_connect()) as connection, connection:
        cursor = connection.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        return cursor.rowcount > 0

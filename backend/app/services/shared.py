import hashlib
import re
from typing import Any, Dict, List, Optional

from .errors import ServiceError

DEFAULT_LABEL = "meeting-action"
SUPPORTED_TRANSCRIPT_EXTENSIONS = {".md", ".txt"}
MEETING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_meeting_id(meeting_id: str) -> str:
    if MEETING_ID_PATTERN.fullmatch(meeting_id):
        return meeting_id
    raise ServiceError(
        status_code=400,
        where="client",
        error=(
            "Invalid meeting_id. Use 1-128 letters, numbers, dots, underscores, "
            "or hyphens, starting with a letter or number."
        ),
    )


def build_chunk_id(text: str, meta: Dict[str, Any]) -> str:
    return hashlib.sha256((text + str(meta)).encode("utf-8")).hexdigest()[:16]


def coerce_labels(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list):
        labels = [str(item).strip() for item in value if str(item).strip()]
        if labels:
            return labels
    return [DEFAULT_LABEL]


def normalize_source_i(value: Any, retrieved_idxs: List[int]) -> int:
    try:
        idx = int(value)
    except Exception:
        return retrieved_idxs[0] if retrieved_idxs else 0

    if idx in retrieved_idxs:
        return idx
    if 0 <= idx < len(retrieved_idxs):
        return retrieved_idxs[idx]
    return retrieved_idxs[0] if retrieved_idxs else 0


def normalize_tasks(tasks: List[Dict[str, Any]], retrieved_idxs: List[int]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for task in tasks:
        title = str(task.get("title", "") or "").strip()
        body = str(task.get("body", "") or "").strip()
        if not title and not body:
            continue

        try:
            confidence = float(task.get("confidence", 0.7))
        except Exception:
            confidence = 0.7

        normalized.append(
            {
                "title": title,
                "body": body,
                "labels": coerce_labels(task.get("labels")),
                "assignee_hint": task.get("assignee_hint"),
                "due_hint": task.get("due_hint"),
                "source_i": normalize_source_i(task.get("source_i"), retrieved_idxs),
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    return normalized


def build_snippet_map(chunks: List[Dict[str, Any]]) -> Dict[int, str]:
    return {int(chunk["i"]): str(chunk["text"]) for chunk in chunks if chunk.get("i") is not None}


def append_source_snippet(body: str, meeting_id: Optional[str], source_i: Any, snippet_by_i: Dict[int, str]) -> str:
    if meeting_id is None or source_i is None:
        return body

    snippet = snippet_by_i.get(int(source_i), "")
    if not snippet:
        return body
    if len(snippet) > 400:
        snippet = snippet[:400] + "..."
    return f"{body}\n\n_Source: meeting `{meeting_id}`, chunk #{source_i}_\n```\n{snippet}\n```"

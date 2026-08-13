import json
import logging
from time import perf_counter
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

import httpx

from ..tasks import OLLAMA_MODEL, OLLAMA_URL, TIMEOUT, _parse_tasks_json, extract_tasks_ollama, extract_tasks_rules
from ..storage import save_task_drafts
from .meetings import MeetingService
from .shared import normalize_tasks

log = logging.getLogger(__name__)

DisconnectFn = Callable[[], Awaitable[bool]]


class ExtractionService:
    def __init__(self, meetings: MeetingService) -> None:
        self.meetings = meetings

    async def extract_tasks(self, meeting_id: str, q: str, k: int) -> Dict[str, Any]:
        started = perf_counter()
        context = self.meetings.load_context(meeting_id, q, k)

        try:
            tasks_llm = await extract_tasks_ollama(context.texts)
        except Exception as exc:
            log.warning("extract_tasks_ollama raised: %s", exc)
            tasks_llm = []

        if tasks_llm:
            tasks = normalize_tasks(tasks_llm, context.idxs)
            mode = "ollama"
        else:
            tasks = extract_tasks_rules(context.chunks)
            mode = "rules"

        self._attach_evidence(tasks, context.chunks)
        save_task_drafts(meeting_id, tasks)
        total_ms = (perf_counter() - started) * 1000
        return {
            "tasks": tasks,
            "mode": mode,
            "timings": {
                "retrieval_ms": context.retrieval_ms,
                "extraction_ms": round(max(0.0, total_ms - context.retrieval_ms), 2),
                "total_ms": round(total_ms, 2),
            },
        }

    @staticmethod
    def _attach_evidence(tasks: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
        by_index = {chunk["i"]: chunk for chunk in chunks}
        for task in tasks:
            source = by_index.get(task.get("source_i"))
            task["source_text"] = source["text"] if source else ""

    async def stream_tasks(
        self,
        meeting_id: str,
        q: str,
        k: int,
        is_disconnected: Optional[DisconnectFn] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        started = perf_counter()
        yield {"stage": "retrieving"}
        context = self.meetings.load_context(meeting_id, q, k)

        if not OLLAMA_MODEL:
            yield {"stage": "parsing", "note": "OLLAMA_MODEL not set; using rules fallback."}
            tasks = extract_tasks_rules(context.chunks)
            self._attach_evidence(tasks, context.chunks)
            save_task_drafts(meeting_id, tasks)
            total_ms = (perf_counter() - started) * 1000
            yield {
                "stage": "done",
                "mode": "rules",
                "tasks": tasks,
                "timings": {
                    "retrieval_ms": context.retrieval_ms,
                    "extraction_ms": round(max(0.0, total_ms - context.retrieval_ms), 2),
                    "total_ms": round(total_ms, 2),
                },
            }
            return

        system = (
            "You extract actionable tasks from snippets and return ONLY valid minified JSON. "
            "NO prose, NO markdown. Shape:\n"
            '{"tasks":[{"title":"","body":"","labels":["meeting-action"],'
            '"assignee_hint":null,"due_hint":null,"source_i":0,"confidence":0.7}]}\n'
            "Rules: (1) JSON only. (2) No backticks. (3) Use integers for source_i. "
            "(4) labels is an array of strings. (5) confidence in [0,1]. "
            "(6) Return at most 15 tasks."
        )
        user = "Snippets:\n" + "\n---\n".join(f"[{i}] {text}" for i, text in enumerate(context.texts))
        req = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "stream": True,
            "options": {"temperature": 0.2, "num_predict": 1000, "num_ctx": 4096},
        }

        chunk_text = ""
        chunks = 0
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=req) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if is_disconnected and await is_disconnected():
                            return
                        if not line:
                            continue

                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if obj.get("done"):
                            break

                        message = (obj.get("message") or {}).get("content")
                        if message:
                            chunk_text += message
                            chunks += 1
                            yield {"stage": "ollama", "progress": min(95, 10 + chunks * 3), "chunks": chunks}
        except Exception as exc:
            log.warning("ollama stream failed: %s", exc)
            chunk_text = ""

        if chunk_text:
            yield {"stage": "parsing"}
            tasks = _parse_tasks_json(chunk_text)
            if tasks:
                normalized = normalize_tasks(tasks, context.idxs)
                self._attach_evidence(normalized, context.chunks)
                save_task_drafts(meeting_id, normalized)
                total_ms = (perf_counter() - started) * 1000
                yield {
                    "stage": "done",
                    "mode": "ollama",
                    "tasks": normalized,
                    "timings": {
                        "retrieval_ms": context.retrieval_ms,
                        "extraction_ms": round(max(0.0, total_ms - context.retrieval_ms), 2),
                        "total_ms": round(total_ms, 2),
                    },
                }
                return

        yield {"stage": "rules_fallback", "note": "Falling back to explicit rule-based extraction."}
        tasks = extract_tasks_rules(context.chunks)
        self._attach_evidence(tasks, context.chunks)
        save_task_drafts(meeting_id, tasks)
        total_ms = (perf_counter() - started) * 1000
        yield {
            "stage": "done",
            "mode": "rules",
            "tasks": tasks,
            "timings": {
                "retrieval_ms": context.retrieval_ms,
                "extraction_ms": round(max(0.0, total_ms - context.retrieval_ms), 2),
                "total_ms": round(total_ms, 2),
            },
        }

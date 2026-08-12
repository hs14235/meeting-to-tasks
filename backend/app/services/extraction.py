import json
import logging
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

import httpx

from ..tasks import OLLAMA_MODEL, OLLAMA_URL, TIMEOUT, _parse_tasks_json, extract_tasks_ollama, extract_tasks_rules
from .meetings import MeetingService
from .shared import normalize_tasks

log = logging.getLogger(__name__)

DisconnectFn = Callable[[], Awaitable[bool]]


class ExtractionService:
    def __init__(self, meetings: MeetingService) -> None:
        self.meetings = meetings

    async def extract_tasks(self, meeting_id: str, q: str, k: int) -> Dict[str, Any]:
        context = self.meetings.load_context(meeting_id, q, k)

        try:
            tasks_llm = await extract_tasks_ollama(context.texts)
        except Exception as exc:
            log.warning("extract_tasks_ollama raised: %s", exc)
            tasks_llm = []

        if tasks_llm:
            return {"tasks": normalize_tasks(tasks_llm, context.idxs), "mode": "ollama"}

        return {"tasks": extract_tasks_rules(context.chunks), "mode": "rules"}

    async def stream_tasks(
        self,
        meeting_id: str,
        q: str,
        k: int,
        is_disconnected: Optional[DisconnectFn] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        yield {"stage": "retrieving"}
        context = self.meetings.load_context(meeting_id, q, k)

        if not OLLAMA_MODEL:
            yield {"stage": "parsing", "note": "OLLAMA_MODEL not set; using rules fallback."}
            yield {"stage": "done", "mode": "rules", "tasks": extract_tasks_rules(context.chunks)}
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
                yield {"stage": "done", "mode": "ollama", "tasks": normalize_tasks(tasks, context.idxs)}
                return

        yield {"stage": "rules_fallback", "note": "Falling back to explicit rule-based extraction."}
        yield {"stage": "done", "mode": "rules", "tasks": extract_tasks_rules(context.chunks)}

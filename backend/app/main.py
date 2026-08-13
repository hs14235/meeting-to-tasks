import json
from typing import Any, Dict

from fastapi import Body, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import ALLOWED_ORIGINS, API_TITLE
from .runtime import extraction_service, issue_service, meeting_service
from .services import ServiceError

DEMO_TRANSCRIPT = """[09:02] Maya: Action: finalize the launch checklist by Friday.
[09:04] Jordan: Action: add retrieval evaluation coverage before the release.
[09:08] Priya: Decision: every GitHub issue must be previewed before creation.
[09:11] Maya: Blocker: the onboarding copy still needs product review.
"""

app = FastAPI(title=API_TITLE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _http_error(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@app.get("/")
def root():
    return {"ok": True}


@app.post("/upload")
async def upload(file: UploadFile, meeting_id: str = Form(...), title: str = Form("")):
    try:
        raw_bytes = await file.read()
        return meeting_service.index_upload(meeting_id, title, file.filename, raw_bytes)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/meetings/index")
def index_meeting(payload: Dict[str, Any] = Body(...)):
    try:
        return meeting_service.index_meeting_text(
            payload["meeting_id"], payload.get("title", ""), payload["transcript"]
        )
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/meetings/demo")
def load_demo():
    try:
        result = meeting_service.index_meeting_text("launch-readiness", "Launch readiness", DEMO_TRANSCRIPT)
        return {**result, "meeting_id": "launch-readiness"}
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.get("/meetings")
def meetings():
    return meeting_service.list()


@app.get("/meetings/{meeting_id}")
def meeting_detail(meeting_id: str):
    try:
        return meeting_service.get(meeting_id)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.delete("/meetings/{meeting_id}")
def remove_meeting(meeting_id: str):
    try:
        return meeting_service.delete(meeting_id)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.put("/meetings/{meeting_id}/tasks")
def update_drafts(meeting_id: str, payload: Dict[str, Any] = Body(...)):
    try:
        return meeting_service.update_drafts(meeting_id, payload.get("tasks", []))
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.get("/search")
def search(meeting_id: str, q: str, k: int = 5):
    try:
        return meeting_service.search(meeting_id, q, k)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/tasks")
async def tasks(payload: Dict[str, Any] = Body(...)):
    try:
        meeting_id = payload["meeting_id"]
        q = payload.get("q", "action items from this meeting")
        k = int(payload.get("k", 5))
        return await extraction_service.extract_tasks(meeting_id, q, k)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/issues")
async def create_issues(payload: Dict[str, Any] = Body(...)):
    try:
        repo = payload["repo"]
        meeting_id = payload.get("meeting_id")
        tasks_payload = payload["tasks"]
        assignee_map = payload.get("assignee_map") or {}
        return await issue_service.create_issues(repo, meeting_id, tasks_payload, assignee_map)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/issues/preview")
async def issues_preview(payload: Dict[str, Any] = Body(...)):
    try:
        repo = payload["repo"]
        meeting_id = payload.get("meeting_id")
        tasks_payload = payload["tasks"]
        return issue_service.preview_issues(repo, meeting_id, tasks_payload)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.get("/healthz")
def healthz():
    return {"ok": True, "demo_mode": issue_service.public_demo_mode}


@app.post("/tasks/stream")
async def tasks_stream(request: Request, payload: Dict[str, Any] = Body(...)):
    async def gen():
        try:
            meeting_id = payload["meeting_id"]
            q = payload.get("q", "action items from this meeting")
            k = int(payload.get("k", 5))

            async for event in extraction_service.stream_tasks(
                meeting_id,
                q,
                k,
                is_disconnected=request.is_disconnected,
            ):
                yield _sse(event)
        except ServiceError as exc:
            yield _sse({"stage": "error", "message": exc.detail.get("error", "Request failed")})
        except Exception as exc:
            yield _sse({"stage": "error", "message": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

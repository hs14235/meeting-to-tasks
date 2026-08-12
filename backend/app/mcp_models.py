from typing import Any, Literal

from pydantic import BaseModel, Field


class IndexMeetingResult(BaseModel):
    ok: bool
    chunks_indexed: int = Field(ge=0)


class SearchHit(BaseModel):
    id: str
    score: float
    meta: dict[str, Any]


class SearchMeetingResult(BaseModel):
    results: list[SearchHit]


class TaskDraft(BaseModel):
    title: str = ""
    body: str = ""
    labels: list[str] = Field(default_factory=lambda: ["meeting-action"])
    assignee_hint: str | None = None
    due_hint: str | None = None
    source_i: int = 0
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractTasksResult(BaseModel):
    tasks: list[TaskDraft]
    mode: Literal["ollama", "rules"]


class IssuePreview(BaseModel):
    repo: str
    title: str
    body: str
    labels: list[str]


class PreviewIssuesResult(BaseModel):
    would_create: list[IssuePreview]


class CreatedIssue(BaseModel):
    title: str
    status: Literal["created", "skipped-duplicate", "skipped-empty-title"]
    number: int | None = None
    url: str | None = None


class CreateIssuesResult(BaseModel):
    created: list[CreatedIssue]

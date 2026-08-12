import argparse
import os
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .mcp_models import (
    CreateIssuesResult,
    ExtractTasksResult,
    IndexMeetingResult,
    PreviewIssuesResult,
    SearchMeetingResult,
    TaskDraft,
)
from .runtime import extraction_service, issue_service, meeting_service
from .services import ServiceError

MeetingId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
        description="Stable meeting identifier used to index and retrieve one transcript.",
    ),
]
Query = Annotated[str, Field(min_length=1, max_length=500)]
TopK = Annotated[int, Field(ge=1, le=20)]

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
VARIABLE_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
EXTERNAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

mcp = MCPServer(
    name="meeting-to-tasks",
    title="Meeting to Tasks",
    description="Convert meeting transcripts into sourced task drafts and optional GitHub issues.",
    version="0.2.0",
    instructions=(
        "Index transcript text before searching or extracting tasks. Preview GitHub issues before "
        "creation. create_github_issues writes to GitHub and must only be used after explicit user approval."
    ),
)


def _raise_tool_error(exc: ServiceError) -> None:
    where = exc.detail.get("where", "server")
    message = exc.detail.get("error", "Request failed")
    raise ToolError(f"{where}: {message}") from exc


@mcp.tool(
    title="Index meeting transcript",
    description=(
        "Chunk, embed, and index a UTF-8 meeting transcript supplied as text. Returns ok and "
        "chunks_indexed. Reusing a meeting_id replaces its saved transcript and upserts its chunks."
    ),
    annotations=LOCAL_WRITE,
    structured_output=True,
)
def index_meeting(
    meeting_id: MeetingId,
    transcript: Annotated[str, Field(min_length=1, description="Full UTF-8 transcript text.")],
    title: Annotated[str, Field(max_length=200)] = "",
) -> IndexMeetingResult:
    try:
        return IndexMeetingResult.model_validate(
            meeting_service.index_meeting_text(meeting_id, title, transcript)
        )
    except ServiceError as exc:
        _raise_tool_error(exc)


@mcp.tool(
    title="Search meeting context",
    description=(
        "Search indexed chunks for one meeting. Returns results with chunk id, similarity score, "
        "and metadata containing meeting_id, title, and source chunk index i."
    ),
    annotations=READ_ONLY,
    structured_output=True,
)
def search_meeting(
    meeting_id: MeetingId,
    query: Query,
    k: TopK = 5,
) -> SearchMeetingResult:
    try:
        return SearchMeetingResult.model_validate(meeting_service.search(meeting_id, query, k))
    except ServiceError as exc:
        _raise_tool_error(exc)


@mcp.tool(
    title="Extract meeting tasks",
    description=(
        "Retrieve relevant meeting chunks and return normalized task drafts with source_i mapped "
        "to the persisted transcript chunk. Uses Ollama when configured, otherwise rules fallback."
    ),
    annotations=VARIABLE_READ_ONLY,
    structured_output=True,
)
async def extract_meeting_tasks(
    meeting_id: MeetingId,
    query: Query = "action items from this meeting",
    k: TopK = 5,
) -> ExtractTasksResult:
    try:
        result = await extraction_service.extract_tasks(meeting_id, query, k)
        return ExtractTasksResult.model_validate(result)
    except ServiceError as exc:
        _raise_tool_error(exc)


@mcp.tool(
    title="Preview GitHub issues",
    description=(
        "Build the exact GitHub issue payloads without network writes. Returns would_create with "
        "repo, title, body, labels, and source snippets when meeting_id is provided."
    ),
    annotations=READ_ONLY,
    structured_output=True,
)
def preview_github_issues(
    repo: Annotated[str, Field(description='GitHub repository in "owner/repo" form.')],
    tasks: list[TaskDraft],
    meeting_id: MeetingId | None = None,
) -> PreviewIssuesResult:
    try:
        task_payloads = [task.model_dump() for task in tasks]
        result = issue_service.preview_issues(repo, meeting_id, task_payloads)
        return PreviewIssuesResult.model_validate(result)
    except ServiceError as exc:
        _raise_tool_error(exc)


@mcp.tool(
    title="Create GitHub issues",
    description=(
        "Create issues in a GitHub repository after explicit user approval. This external write "
        "may also create missing labels; duplicate fingerprints are skipped. Returns created records "
        "with status, issue number, and URL when available."
    ),
    annotations=EXTERNAL_WRITE,
    structured_output=True,
)
async def create_github_issues(
    repo: Annotated[str, Field(description='GitHub repository in "owner/repo" form.')],
    tasks: list[TaskDraft],
    meeting_id: MeetingId | None = None,
    assignee_map: dict[str, str] | None = None,
) -> CreateIssuesResult:
    try:
        task_payloads = [task.model_dump() for task in tasks]
        result = await issue_service.create_issues(repo, meeting_id, task_payloads, assignee_map)
        return CreateIssuesResult.model_validate(result)
    except ServiceError as exc:
        _raise_tool_error(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Meeting to Tasks MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8001")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path="/mcp",
        stateless_http=True,
    )


if __name__ == "__main__":
    main()

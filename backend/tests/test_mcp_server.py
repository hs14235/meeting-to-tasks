import pytest

from app import mcp_server


class DummyMeetingService:
    def __init__(self):
        self.index_calls = []

    def index_meeting_text(self, meeting_id, title, transcript):
        self.index_calls.append((meeting_id, title, transcript))
        return {"ok": True, "chunks_indexed": 2}


@pytest.mark.anyio
async def test_mcp_exposes_expected_tools_and_safety_annotations():
    tools = {tool.name: tool for tool in await mcp_server.mcp.list_tools()}

    assert set(tools) == {
        "index_meeting",
        "search_meeting",
        "extract_meeting_tasks",
        "preview_github_issues",
        "create_github_issues",
    }
    assert tools["search_meeting"].annotations.read_only_hint is True
    assert tools["create_github_issues"].annotations.destructive_hint is True
    assert tools["create_github_issues"].annotations.open_world_hint is True
    assert tools["extract_meeting_tasks"].output_schema["properties"]["mode"]


@pytest.mark.anyio
async def test_index_meeting_tool_delegates_and_returns_structured_content(monkeypatch):
    dummy_service = DummyMeetingService()
    monkeypatch.setattr(mcp_server, "meeting_service", dummy_service)

    result = await mcp_server.mcp.call_tool(
        "index_meeting",
        {
            "meeting_id": "weekly-sync",
            "title": "Weekly sync",
            "transcript": "Action: Hamza to finish the MCP contract tests.",
        },
    )

    assert result.is_error is False
    assert result.structured_content["ok"] is True
    assert result.structured_content["chunks_indexed"] == 2
    assert dummy_service.index_calls == [
        (
            "weekly-sync",
            "Weekly sync",
            "Action: Hamza to finish the MCP contract tests.",
        )
    ]

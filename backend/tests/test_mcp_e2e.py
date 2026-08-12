import pytest

from scripts.demo_mcp_workflow import run_demo


@pytest.mark.anyio
async def test_complete_mcp_workflow_over_stdio():
    result = await run_demo()

    assert result["server"] == {"name": "meeting-to-tasks", "version": "0.2.0"}
    assert result["extraction"]["mode"] == "rules"
    assert result["extraction"]["task_count"] >= 2
    assert result["github_preview_count"] == result["extraction"]["task_count"]
    assert all(result["checks"].values())

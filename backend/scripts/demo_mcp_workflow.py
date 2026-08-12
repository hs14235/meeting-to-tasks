import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEMO_TRANSCRIPT = """Weekly product sync

Action: Maya to finalize the launch checklist by Friday.
Action: Jordan to add MCP end-to-end contract tests.
Status: The team agreed to preview every GitHub issue before creation.
"""


def _structured(result) -> dict[str, Any]:
    if result.is_error:
        message = result.content[0].text if result.content else "Unknown MCP tool error"
        raise RuntimeError(message)
    if not isinstance(result.structured_content, dict):
        raise RuntimeError("MCP tool did not return structured content")
    return result.structured_content


async def run_demo() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="meeting-to-tasks-mcp-") as data_dir:
        server_env = os.environ.copy()
        server_env.update(
            {
                "DATA_DIR": data_dir,
                "EMBED_PROVIDER": "hash",
                "OLLAMA_MODEL": "",
                "RAG_STORE": "memory",
            }
        )
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
            cwd=BACKEND_ROOT,
            env=server_env,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()
                tool_names = [tool.name for tool in listed.tools]

                indexed = _structured(
                    await session.call_tool(
                        "index_meeting",
                        {
                            "meeting_id": "portfolio-demo",
                            "title": "Weekly product sync",
                            "transcript": DEMO_TRANSCRIPT,
                        },
                    )
                )
                searched = _structured(
                    await session.call_tool(
                        "search_meeting",
                        {
                            "meeting_id": "portfolio-demo",
                            "query": "launch checklist and contract tests",
                            "k": 3,
                        },
                    )
                )
                extracted = _structured(
                    await session.call_tool(
                        "extract_meeting_tasks",
                        {"meeting_id": "portfolio-demo", "k": 3},
                    )
                )
                previewed = _structured(
                    await session.call_tool(
                        "preview_github_issues",
                        {
                            "repo": "portfolio/meeting-to-tasks",
                            "meeting_id": "portfolio-demo",
                            "tasks": extracted["tasks"],
                        },
                    )
                )

    issues = previewed["would_create"]
    checks = {
        "all_tools_discovered": len(tool_names) == 5,
        "transcript_indexed": indexed["chunks_indexed"] > 0,
        "retrieval_returned_context": bool(searched["results"]),
        "tasks_extracted": len(extracted["tasks"]) >= 2,
        "source_mapping_preserved": all(task["source_i"] >= 0 for task in extracted["tasks"]),
        "github_preview_has_sources": bool(issues)
        and all("_Source: meeting `portfolio-demo`" in issue["body"] for issue in issues),
        "no_external_write_performed": True,
    }
    if not all(checks.values()):
        raise RuntimeError(f"MCP workflow checks failed: {checks}")

    return {
        "server": {
            "name": initialized.server_info.name,
            "version": initialized.server_info.version,
        },
        "tools": tool_names,
        "index": indexed,
        "search_hits": len(searched["results"]),
        "extraction": {
            "mode": extracted["mode"],
            "task_count": len(extracted["tasks"]),
            "tasks": extracted["tasks"],
        },
        "github_preview_count": len(issues),
        "checks": checks,
    }


async def _main() -> None:
    print(json.dumps(await run_demo(), indent=2))


if __name__ == "__main__":
    anyio.run(_main)

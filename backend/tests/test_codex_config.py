from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_project_codex_config_points_to_mcp_server_with_write_approval():
    config = tomllib.loads((PROJECT_ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
    server = config["mcp_servers"]["meeting_to_tasks"]
    server_cwd = PROJECT_ROOT / server["cwd"]
    server_command = server_cwd / server["command"]

    assert server_command.exists()
    assert server["args"] == ["-m", "app.mcp_server"]
    assert server["default_tools_approval_mode"] == "writes"
    assert server["tools"]["create_github_issues"]["approval_mode"] == "prompt"

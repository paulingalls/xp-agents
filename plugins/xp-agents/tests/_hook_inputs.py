"""Canonical hook input factories — used by hook unit tests to construct
input dicts that match Claude Code's hook input format.

Re-exported from conftest. Naming uses leading underscores to mark these
as test fixtures, not production helpers.
"""


def _make_write_input(**overrides) -> dict:
    """Build a canonical Write tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Write",
        "tool_input": {"file_path": "src/app.ts", "content": "x"},
        "cwd": "/tmp",
        "agent_id": "main",
    }
    data.update(overrides)
    return data


def _make_bash_input(command: str = "echo hi", stdout: str = "", **overrides) -> dict:
    """Build a canonical Bash tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout},
        "cwd": "/tmp",
        "agent_id": "main",
    }
    data.update(overrides)
    return data


def _make_skill_input(skill: str = "test-skill", **overrides) -> dict:
    """Build a canonical Skill tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Skill",
        "tool_input": {"skill": skill},
        "agent_id": "main",
    }
    data.update(overrides)
    return data


def _make_stop_input(**overrides) -> dict:
    """Build a canonical Stop hook input dict."""
    data = {"session_id": "t", "agent_id": "main"}
    data.update(overrides)
    return data


def _make_teammate_idle_input(**overrides) -> dict:
    """Build a canonical TeammateIdle hook input dict."""
    data = {
        "session_id": "t",
        "teammate_name": "worker-1",
        "team_name": "test-team",
        "permission_mode": "bypassPermissions",
    }
    data.update(overrides)
    return data


def _make_task_completed_input(**overrides) -> dict:
    """Build a canonical TaskCompleted hook input dict."""
    data = {
        "session_id": "t",
        "task_id": "task-1",
        "task_subject": "Implement feature",
        "task_description": "Build the thing",
        "teammate_name": "worker-1",
        "team_name": "test-team",
    }
    data.update(overrides)
    return data

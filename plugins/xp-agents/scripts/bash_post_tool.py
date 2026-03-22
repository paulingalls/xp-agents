#!/usr/bin/env python3
"""PostToolUse command hook for Bash: parse git commits and test results.

Auto-drafts decision events for commits, checks commit size, and records
test pass/fail status from pytest/jest/go test output.
"""

import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import security
from test_parsing import is_test_run, parse_test_results

# ---------------------------------------------------------------------------
# Commit parsing
# ---------------------------------------------------------------------------


def parse_commit_message(tool_response: str) -> str | None:
    """Extract first line of commit message from git output."""
    # Git commit output: [branch hash] message
    match = re.search(r"\[[\w/.-]+\s+\w+\]\s+(.+)", tool_response)
    if match:
        return match.group(1).strip()
    return None


def get_committed_files(cwd: str) -> list[str]:
    """Get list of files changed in the last commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        pass
    return []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _resolve_lint_on_commit(
    smm_dir: Path, cwd: str, agent_id: str, files: list[str]
) -> None:
    """Run linter on committed files and resolve lint concerns for passing ones."""
    if not files:
        return

    import lint_check

    git_root = cwd
    with contextlib.suppress(subprocess.CalledProcessError, FileNotFoundError):
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    config = lint_check.detect_linter_config(cwd, git_root)
    if config is None:
        return

    linter_name, _ = config

    for file_path in files:
        normalized = _common.normalize_path(file_path, cwd)
        lint_output = lint_check.run_linter(linter_name, normalized)
        if lint_output is None:
            # File passes lint (or linter doesn't apply) — resolve concern
            prefix = f"{concerns.LINT_CONCERN_PREFIX}{normalized}:"
            concerns.resolve_concerns(
                smm_dir,
                lambda c, p=prefix: c.startswith(p),
                agent_id,
                "Lint concern resolved on commit",
            )


def load_commit_threshold() -> int:
    """Load commit_size_threshold from settings.json, default 10."""
    try:
        settings_path = _common.resolve_plugin_root() / "settings.json"
        data = json.loads(settings_path.read_text())
        return int(data.get("commit_size_threshold", 10))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
        return 10


# ---------------------------------------------------------------------------
# Event helpers (delegates to _common)
# ---------------------------------------------------------------------------


def _resolve_test_concerns(smm_dir: Path, agent_id: str) -> None:
    """Auto-resolve unresolved test-failure concerns when tests pass."""
    concerns.resolve_concerns(
        smm_dir,
        concerns.TEST_CONCERN_RE.search,
        agent_id,
        "Test concern resolved",
    )


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core bash_post_tool logic. Appends events, no stdout."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    tool_input = input_data.get("tool_input", {})
    tool_response = input_data.get("tool_response", {})
    agent_id = input_data.get("agent_id", "main")
    cwd = input_data.get("cwd", ".")

    command = tool_input.get("command", "")
    # tool_response can be a dict with stdout/stderr or a string
    if isinstance(tool_response, dict):
        response_text = tool_response.get("stdout", "") or ""
    else:
        response_text = str(tool_response)

    # Git commit detection
    if security.is_git_commit(command):
        msg = parse_commit_message(response_text)
        if msg:
            # Record commit as status (not a decision — commit messages
            # are activity, not architectural choices)
            status = _common.make_event(
                _common.STATUS,
                agent_id,
                f"Committed: {msg}",
                working_on=[],
            )
            _common.append_safe(smm_dir, status)

            # Commit size check
            threshold = load_commit_threshold()
            committed_files = get_committed_files(cwd)
            file_count = len(committed_files)
            if file_count >= threshold:
                concern = _common.make_event(
                    _common.CONCERN,
                    agent_id,
                    f"Commit touches {file_count} files — consider smaller commits.",
                    severity="medium",
                )
                _common.append_safe(smm_dir, concern)

        # Resolve lint concerns for committed files that now pass
        _resolve_lint_on_commit(smm_dir, cwd, agent_id, committed_files)

        # Consume security triage marker after successful commit
        security.consume_security_triaged(smm_dir)

        return None

    # Test run detection
    framework = is_test_run(command)
    if framework:
        results = parse_test_results(response_text, framework)
        passed = results["passed"]
        failed = results["failed"]

        status = _common.make_event(
            _common.STATUS,
            agent_id,
            f"Tests: {passed} passed, {failed} failed ({framework})",
            working_on=[],
        )
        _common.append_safe(smm_dir, status)

        if failed > 0:
            concern = _common.make_event(
                _common.CONCERN,
                agent_id,
                f"Test failures detected: {failed} failed ({framework})",
                severity="high",
            )
            _common.append_safe(smm_dir, concern)
        elif failed == 0:
            _resolve_test_concerns(smm_dir, agent_id)

        return None

    # Other commands — ignore
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)

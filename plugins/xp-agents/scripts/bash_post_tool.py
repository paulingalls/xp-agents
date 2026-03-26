#!/usr/bin/env python3
"""PostToolUse command hook for Bash: parse git commits and test results.

Records commit status events, checks commit size, and records test
pass/fail status. Nudges /simplify after commits with 3+ code files.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
import concerns
import markers
import security
from test_parsing import is_test_run, parse_test_results

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

    git_root = _common.resolve_git_root(cwd) or cwd

    config = lint_check.detect_linter_config(cwd, git_root)
    if config is None:
        return

    linter_name, _ = config

    for file_path in files:
        normalized = _common.normalize_path(file_path, cwd)
        lint_output = lint_check.run_linter(linter_name, normalized)
        if lint_output is None:
            # File passes lint (or linter doesn't apply) — resolve concern
            concerns.resolve_concerns(
                smm_dir,
                lambda c, n=normalized: concerns.lint_concern_matches(c, n),
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
# Commit handling
# ---------------------------------------------------------------------------


def _handle_commit(
    smm_dir: Path, agent_id: str, cwd: str, response_text: str
) -> str | None:
    """Process a successful git commit: record events, consume markers, nudge."""
    committed_files: list[str] = []
    msg = commits.parse_commit_message(response_text)
    if msg:
        status = _common.make_event(
            _common.STATUS,
            agent_id,
            f"Committed: {msg}",
            working_on=[],
        )
        _common.append_safe(smm_dir, status)

        # Commit size check
        threshold = load_commit_threshold()
        committed_files = commits.get_committed_files(cwd)
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

    # Reset review cycle marker with new commit hash
    commit_hash = commits.get_head_commit_hash(cwd)
    if commit_hash:
        markers.reset_review_cycle(smm_dir, agent_id, commit_hash)

    # Nudge /simplify if commit has 3+ code files (including tests —
    # test code benefits from simplify too, unlike security triage)
    code_files = [f for f in committed_files if security.is_code_file(f)]
    if len(code_files) >= 3:
        return (
            f"You just committed {len(code_files)} code files. "
            "Run /simplify NOW before starting the next task."
        )

    return None


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
        return _handle_commit(smm_dir, agent_id, cwd, response_text)

    # Test run detection
    framework = is_test_run(command)
    if framework:
        results = parse_test_results(response_text, framework)
        passed = results["passed"]
        failed = results["failed"]

        # If parser couldn't extract numbers (truncated output),
        # still record that tests passed — just without counts
        if passed == 0 and failed == 0:
            content = f"Tests passed ({framework})"
        else:
            content = f"Tests: {passed} passed, {failed} failed ({framework})"

        status = _common.make_event(
            _common.STATUS,
            agent_id,
            content,
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

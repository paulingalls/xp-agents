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

import re

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

    for file_path in files:
        normalized = _common.normalize_path(file_path, cwd)
        config = lint_check.detect_linter_config(cwd, git_root, file_path=normalized)
        if config is None:
            continue
        linter_name, _ = config
        lint_output = lint_check.run_linter(linter_name, normalized, cwd=git_root)
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


def _resolve_test_concerns(smm_dir: Path, agent_id: str) -> bool:
    """Auto-resolve unresolved test-failure concerns when tests pass.

    Returns True if any concerns were resolved.
    """
    return concerns.resolve_concerns(
        smm_dir,
        concerns.TEST_CONCERN_RE.search,
        agent_id,
        "Test concern resolved",
    )


# ---------------------------------------------------------------------------
# Commit handling
# ---------------------------------------------------------------------------


_GIT_PUSH_RE = re.compile(r"\bgit\s+push\b")


def _is_git_push(command: str) -> bool:
    """Detect git push commands."""
    return bool(_GIT_PUSH_RE.search(command))


def _session_end_checklist(smm_dir: Path) -> str | None:
    """Return session-end checklist nudge if issues found."""
    events = _common.read_events_raw(smm_dir)
    if not events:
        return None

    parts: list[str] = []
    unresolved = _common.count_unresolved_concerns(events)
    if unresolved:
        parts.append(
            f"{unresolved} unresolved concern(s) — review before ending session."
        )
    parts.append("Summarize what was accomplished this session for the user.")
    return "Session-end checklist: " + " ".join(parts)


def _handle_commit(
    smm_dir: Path, agent_id: str, cwd: str, response_text: str
) -> str | None:
    """Process a successful git commit: record events, consume markers, nudge."""
    committed_files: list[str] = []
    commit_hash: str | None = None
    msg = commits.parse_commit_message(response_text)
    if msg:
        committed_files = commits.get_committed_files(cwd)
        commit_hash = commits.get_head_commit_hash(cwd)
        has_code = any(security.is_code_file(f) for f in committed_files)

        # Full message body for richer retrospective context
        # Strip Co-Authored-By trailers — metadata, not content
        body = commits.get_commit_message_body(cwd) or msg
        body = re.sub(r"\n+\s*Co-Authored-By:.*$", "", body, flags=re.DOTALL).strip()

        metadata: dict = {"code_commit": has_code}
        if commit_hash:
            metadata["commit_hash"] = commit_hash

        event = _common.make_event(
            _common.COMMIT,
            agent_id,
            body,
            files=committed_files,
            metadata=metadata,
        )
        _common.append_safe(smm_dir, event)

        # Commit size check
        threshold = load_commit_threshold()
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
    if commit_hash is None:
        commit_hash = commits.get_head_commit_hash(cwd)
    if commit_hash:
        markers.reset_review_cycle(smm_dir, agent_id, commit_hash)

    return None


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core bash_post_tool logic. Appends events, returns nudge or None."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
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

    # Git push detection — nudge session-end checklist
    if _is_git_push(command):
        return _session_end_checklist(smm_dir)

    # Test run detection
    framework = is_test_run(command)
    if framework:
        results = parse_test_results(response_text, framework)
        passed = results["passed"]
        failed = results["failed"]

        # If parser couldn't extract numbers (truncated output, wrong dir, etc.),
        # record a neutral status — we don't know if tests passed or failed
        if passed == 0 and failed == 0:
            content = f"Tests ran ({framework}) — counts not extracted"
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
                f"{concerns.TEST_FAILURES_PREFIX}: {failed} failed ({framework})",
                severity="high",
            )
            _common.append_safe(smm_dir, concern)
        elif failed == 0:
            had_failures = _resolve_test_concerns(smm_dir, agent_id)

            # Nudge: commit after green if there are uncommitted code files
            if passed > 0:
                parts: list[str] = []
                if had_failures:
                    parts.append("All prior test failures resolved — tests are green.")
                uncommitted = commits.get_uncommitted_code_files(cwd)
                if uncommitted:
                    parts.append(
                        "Commit now to trigger the review cycle "
                        "(/simplify, /xp-quality-review, /xp-security-triage)."
                    )
                if parts:
                    return " ".join(parts)

        return None

    # Other commands — ignore
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)

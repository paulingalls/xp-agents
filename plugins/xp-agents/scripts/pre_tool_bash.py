#!/usr/bin/env python3
"""PreToolUse hook for Bash: commit security gate + file-modification detection."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import security

# ---------------------------------------------------------------------------
# Bash file-modification heuristic
# ---------------------------------------------------------------------------

_FILE_MODIFY_PATTERNS = [
    re.compile(r">\s*(\S+)"),  # redirect: echo > file
    re.compile(r"tee\s+(\S+)"),  # tee file
    re.compile(r"sed\s+-i\S*\s+\S+\s+(\S+)"),  # sed -i expr file
    re.compile(r"mv\s+\S+\s+(\S+)"),  # mv src dest
    re.compile(r"cp\s+\S+\s+(\S+)"),  # cp src dest
]


def detect_bash_target_files(command: str) -> list[str]:
    """Best-effort extraction of files a Bash command might modify."""
    files = []
    for pattern in _FILE_MODIFY_PATTERNS:
        for match in pattern.finditer(command):
            f = match.group(1)
            if f and not f.startswith("-"):
                files.append(f)
    return files


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core logic. Returns additionalContext string or None. Raises BlockedError."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)

    tool_input = input_data.get("tool_input", {})
    agent_id = input_data.get("agent_id", "main")
    cwd = input_data.get("cwd", ".")
    command = tool_input.get("command", "")

    parts: list[str] = []

    # Commit gate: block git commit until security triage has been run
    # Only require triage for commits that include production code files
    # (skip for test-only, docs-only, or config-only commits)
    if smm_dir is not None and security.is_git_commit(command):
        has_code = security.has_staged_code_files(cwd, command)
        if has_code and not security.security_triaged_exists(smm_dir):
            raise _common.BlockedError(
                "Run /xp-security-triage before committing.",
                "Security triage required before committing.",
            )
        if not has_code:
            # Non-code commit — consume any stale marker so it doesn't
            # carry over and let a future code commit skip triage
            security.consume_security_triaged(smm_dir)

    # File-modification heuristic — advisory only, never blocks
    if smm_dir is not None:
        target_files = detect_bash_target_files(command)
        if target_files:
            coord_data = coordination.read_coordination(smm_dir)
            for target_file in target_files:
                normalized_target = _common.normalize_path(target_file, cwd)
                for aid, entry in coord_data.items():
                    if aid == agent_id:
                        continue
                    for f in entry.get("working_on", []):
                        try:
                            if _common.normalize_path(f, cwd) == normalized_target:
                                parts.append(
                                    f"Advisory: Agent '{aid}' may be working on "
                                    f"'{target_file}'. Coordinate before modifying."
                                )
                        except (ValueError, OSError):
                            continue

    if not parts:
        return None

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()

    try:
        result = run(input_data)
    except _common.BlockedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    if result:
        _common.hook_output("PreToolUse", result)

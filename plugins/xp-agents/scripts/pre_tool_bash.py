#!/usr/bin/env python3
"""PreToolUse hook for Bash: push security gate + file-modification detection."""

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import security

# ---------------------------------------------------------------------------
# Git push detection
# ---------------------------------------------------------------------------


def is_git_push(command: str) -> bool:
    """Detect git push in a shell command using argv parsing.

    Handles /usr/bin/git, git -c key=val push, env git push, etc.
    Falls back to regex on parse failure.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Malformed shell quoting — fall back to simple regex
        return bool(re.search(r"\bgit\s+push\b", command))

    # Walk tokens looking for a git executable followed by push subcommand
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Check if token is 'git' or ends with '/git'
        if tok == "git" or tok.endswith("/git"):
            # Scan forward past flags/options for the subcommand
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-"):
                j += 1
                # Skip flag value for -c/-C style options
                prev = tokens[j - 1]
                if (
                    j < len(tokens)
                    and not prev.startswith("--")
                    and prev in ("-c", "-C")
                ):
                    j += 1
            if j < len(tokens) and tokens[j] == "push":
                return True
        i += 1
    return False


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

    enforcement = _common.load_enforcement_mode()

    parts: list[str] = []

    # Push gate: block git push until security review has been run
    if smm_dir is not None and is_git_push(command):
        head_hash = security.get_head_hash(cwd)
        if head_hash is not None and not security.security_tracker_exists(
            smm_dir, head_hash
        ):
            # Check if a previous review can carry forward
            # (only non-code changes since last reviewed commit)
            reviewed_hash = security.find_last_reviewed_hash(smm_dir)
            if reviewed_hash is not None and not security.diff_has_code_changes(
                reviewed_hash, head_hash, cwd
            ):
                # Carry forward: only non-code changes since last review
                security.write_security_tracker(smm_dir, head_hash)
            else:
                # Block and request review — tracker will be written
                # by security_review_done.py PostToolUse:Skill hook
                # when /security-review completes
                event = _common.make_event(
                    _common.SECURITY_REVIEW_REQUESTED,
                    agent_id,
                    f"Security review required before push (HEAD: {head_hash})",
                )
                _common.append_safe(smm_dir, event)
                msg = (
                    "Security review required before pushing. "
                    "Either run the /security-review skill to "
                    "perform the review, or if you have already "
                    "reviewed the code, run the /security-clear "
                    "skill to clear the gate."
                )
                if enforcement == _common.ENFORCEMENT_ADVISORY:
                    parts.append(f"Advisory warning: {msg}")
                else:
                    raise _common.BlockedError(
                        msg, "Security review required before pushing."
                    )

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

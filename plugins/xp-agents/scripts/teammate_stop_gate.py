#!/usr/bin/env python3
"""Stop command hook: teammate review cycle + commit gate.

Blocks xp-teammate agents from stopping if they have uncommitted changes
without completing the review cycle (xp-simplify → quality-review →
security-review) and committing.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import markers


def _has_uncommitted_changes(cwd: str) -> bool:
    """Check if the working directory has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return False


_WORKTREE_MARKER = "/.claude/worktrees/agent-"


def _is_worktree_teammate(input_data: dict) -> bool:
    """Detect worktree teammates via cwd path or agent_type."""
    agent_type = input_data.get("agent_type", "")
    if agent_type in _common.TEAMMATE_AGENT_TYPES:
        return True
    cwd = input_data.get("cwd", "")
    return _WORKTREE_MARKER in cwd


def _resolve_agent_id(input_data: dict, smm_dir: Path) -> str:
    """Resolve agent_id from input or worktree path prefix."""
    agent_id = input_data.get("agent_id", "")
    if agent_id:
        return agent_id
    cwd = input_data.get("cwd", "")
    idx = cwd.find(_WORKTREE_MARKER)
    if idx < 0:
        return ""
    prefix = cwd[idx + len(_WORKTREE_MARKER) :]
    prefix = prefix.split("/")[0]
    for path in smm_dir.glob(f".review-cycle-{prefix}*.json"):
        return path.name.removeprefix(".review-cycle-").removesuffix(".json")
    return ""


def run(
    input_data: dict,
    smm_dir: Path | None = None,
    has_uncommitted: bool | None = None,
) -> str | None:
    """Return block reason if teammate should not stop, None otherwise."""
    if not _is_worktree_teammate(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if has_uncommitted is None:
        has_uncommitted = _has_uncommitted_changes(input_data.get("cwd", "."))

    if not has_uncommitted:
        return None

    agent_id = _resolve_agent_id(input_data, smm_dir)
    cycle = markers.read_review_cycle(smm_dir, agent_id) if agent_id else {}

    if not cycle.get("simplify_done"):
        return "You have uncommitted changes. Run /xp-simplify before stopping."
    if not cycle.get("quality_review_done"):
        return "Simplify complete. Run /xp-quality-review before stopping."
    if not cycle.get("security_review_done"):
        return "Quality review complete. Run /security-review before stopping."

    return "Review cycle complete. Commit your changes before stopping."


if __name__ == "__main__":
    input_data = _common.read_hook_input()

    # DEBUG: log full stop gate input to events.jsonl
    smm_dir = _common.get_validated_smm_dir()
    if smm_dir is not None:
        import json as _json

        debug_event = _common.make_event(
            _common.STATUS,
            "teammate-stop-gate-debug",
            f"Stop gate input keys: {sorted(input_data.keys())}"
            f" | full: {_json.dumps(input_data, default=str)[:500]}",
            working_on=[],
        )
        _common.append_safe(smm_dir, debug_event)

    result = run(input_data)

    if result:
        print(result, file=sys.stderr)
        sys.exit(2)

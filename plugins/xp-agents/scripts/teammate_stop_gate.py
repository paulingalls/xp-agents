#!/usr/bin/env python3
"""Stop command hook: teammate review cycle + commit gate.

Blocks CLI teammates (detected via worktree cwd path) from stopping if
they have uncommitted changes without completing the review cycle
(xp-simplify → quality-review → security-review) and committing.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import identity
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


def run(
    input_data: dict,
    smm_dir: Path | None = None,
    has_uncommitted: bool | None = None,
) -> str | None:
    """Return block reason if teammate should not stop, None otherwise."""
    if not identity.is_worktree_teammate(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if has_uncommitted is None:
        has_uncommitted = _has_uncommitted_changes(input_data.get("cwd", "."))

    if not has_uncommitted:
        return None

    agent_id = identity.resolve_agent_id(input_data)
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
    result = run(input_data)

    if result:
        print(result, file=sys.stderr)
        sys.exit(2)

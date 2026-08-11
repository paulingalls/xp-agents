#!/usr/bin/env python3
"""Stop command hook: teammate review cycle + commit gate.

Blocks CLI teammates (detected via worktree cwd path) from stopping if
they have uncommitted changes without completing the per-increment review
(/xp-quality-review, which self-finds correctness) and committing.
"""

import subprocess
import sys
from pathlib import Path

import review_records

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

    # Under story cadence, per-increment review is deferred to the merge.
    # Don't demand /xp-quality-review; only demand that changes be committed.
    cadence = markers.read_review_cadence(smm_dir)
    if cadence == "story":
        return "You have uncommitted changes. Commit them before stopping."

    # No `if agent_id` guard: the key falls back to "main" for any cwd, so the
    # empty branch was unreachable and its {} silently read as "unreviewed".
    flags = review_records.read_review_flags(
        smm_dir, identity.review_flags_key(input_data.get("cwd", ""))
    )

    # Per-increment review is /xp-quality-review only — the xp-code-reviewer it
    # spawns self-finds correctness; the workflow /code-review runs at close.
    if not flags.get("quality_review_done"):
        return "You have uncommitted changes. Run /xp-quality-review before stopping."

    return "Review cycle complete. Commit your changes before stopping."


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)

    if result:
        print(result, file=sys.stderr)
        sys.exit(2)

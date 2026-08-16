#!/usr/bin/env python3
"""[verify-deferred] marker parsing and verify-path bookkeeping.

Extracted from commit_handling to keep that module under the 500-line cap
(single responsibility: everything about the [verify-deferred] commit marker
and the story's untouched verify paths lives here).

Holds the marker regex/parser (`parse_verify_deferred`), the base..head scan
(`branch_has_verify_deferred`), the untouched-path pipeline
(`untouched_paths_for_story`), and the CLI both the story-close preload and
commit_handling reuse.

CLI: `verify_deferred.py has-verify-deferred --cwd <dir> --base <ref>` prints
true/false — the story-close preload's single source for the [verify-deferred]
marker check (reuses parse_verify_deferred, no duplicate bash regex).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

_VERIFY_DEFERRED_RE = re.compile(
    r"^\s*\[verify-deferred\]\s*(.*)", re.IGNORECASE | re.DOTALL
)
VERIFY_DEBT_CONTENT_LIMIT = 180
METADATA_KEY_VERIFY_DEFERRED = "verify_deferred"


def parse_verify_deferred(message: str | None) -> str | None:
    """Return the rationale after a [verify-deferred] prefix, or None.

    A bare prefix (no trailing text) yields "(no rationale)" so callers can
    distinguish "deferred without reason" from "not deferred" (None). Kept
    separate from commits.is_escape_hatch_commit: [verify-deferred] bypasses
    only the verify-touch gate, never branch protection.
    """
    if not message:
        return None
    m = _VERIFY_DEFERRED_RE.match(message)
    if not m:
        return None
    return m.group(1).strip() or "(no rationale)"


def branch_has_verify_deferred(cwd: str, base: str, head: str = "HEAD") -> bool:
    """True when any commit subject on base..head carries [verify-deferred].

    Single source for the marker check — reuses parse_verify_deferred so the
    commit-time nudge/debt and the story-close gate share one regex (no
    duplicate bash pattern). `head` defaults to HEAD; the close-gate backstop
    passes the source branch (it runs on the target branch). Returns False on
    git failure (fail-open: an unreadable range defers nothing).
    """
    try:
        result = subprocess.run(
            ["git", "log", f"{base}..{head}", "--format=%s"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    return any(
        parse_verify_deferred(line) is not None for line in result.stdout.splitlines()
    )


def untouched_paths_for_story(
    smm_dir: Path, cwd: str, story_id: str, *, staged: list[str] | None = None
) -> list[str]:
    """Verify paths the story declares that no commit on its branch touched.

    The shared fail-open pipeline behind the pre-commit nudge, the
    post-commit [verify-deferred] debt, and the story-close gate: returns []
    (and never raises) when the story is gone, declares no verify paths, or
    git can't be read.

    `staged` is opt-in coverage from the index (the commit-time nudge's own
    commit doesn't exist yet to be walked). Defaulting to None keeps every
    other caller — the post-commit debt, the close gate, the CLI — reading
    commit-only coverage, which merge time must never relax: a merge carries
    commits, not the index.
    """
    import branching
    import sprint_store
    import verify_paths

    try:
        story = sprint_store.get_story(smm_dir, story_id)
    except (ValueError, OSError):
        return []
    paths = verify_paths.extract_verify_paths(story)
    if not paths:
        return []
    base = branching.get_story_base_branch(smm_dir, cwd)
    try:
        return verify_paths.untouched_verify_paths(
            paths, cwd, base, also_changed=set(staged or ())
        )
    except ValueError:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="verify-deferred queries")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "has-verify-deferred",
        help="Print true/false: any [verify-deferred] commit on base..HEAD",
    )
    p.add_argument("--cwd", default=".", help="Repo working directory")
    p.add_argument("--base", required=True, help="Base ref")
    args = parser.parse_args()

    match args.command:
        case "has-verify-deferred":
            deferred = branch_has_verify_deferred(args.cwd, args.base)
            print("true" if deferred else "false")
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

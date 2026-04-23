#!/usr/bin/env python3
"""Pre-commit resolves-trailer probe for /xp-quality-review.

Scans changed files (staged, unstaged, and untracked) for open concerns
whose files overlap. Called by the xp-quality-review skill BEFORE the
reviewer spawns, so the agent sees overlapping concerns early.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "smm"))

import resolves_probe


def _changed_files(cwd: str) -> list[str]:
    """Return all changed files: staged, unstaged, and untracked new."""
    files: set[str] = set()
    for cmd in (
        ["git", "diff", "HEAD", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if result.returncode == 0:
            files.update(f.strip() for f in result.stdout.splitlines() if f.strip())
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--cwd", required=True)
    args = parser.parse_args()

    smm_dir = Path(args.smm_dir)
    cwd = args.cwd

    changed = _changed_files(cwd)
    if not changed:
        print("(no changed files — skip probe)")
        return 0

    candidates = resolves_probe.find_probe_candidates(
        smm_dir, changed, resolves=[], cwd=cwd
    )
    if not candidates:
        print("(no open concerns match changed files — nothing to auto-link)")
        return 0

    lines = [f"Found {len(candidates)} open concern(s) your changed files touch:"]
    for c in candidates:
        content = (c.get("content") or "")[:100]
        lines.append(f"  - {c['id']}: {content}")
    lines.extend(
        [
            "",
            "If the commit closes one of these, add a trailer to your commit:",
            "  Resolves-Event: <event-id>",
        ]
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

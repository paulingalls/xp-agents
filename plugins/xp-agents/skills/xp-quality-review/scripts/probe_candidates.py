#!/usr/bin/env python3
"""Pre-commit resolves-trailer probe for /xp-quality-review.

Scans the staged file set for open concerns whose files overlap, drops a
REVIEW_FINGERPRINT marker the post-commit hook consumes for dedup, and
emits a resolves_probe_shown status event so retro._compute_resolves_link_rate
can pair it with the subsequent commit.

Called by the xp-quality-review skill BEFORE the reviewer spawns, so the
Resolves-Event: trailer can land on the first commit rather than needing
`git commit --amend`.
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "smm"))

import _common
import identity
import markers
import resolves_probe


def _staged_files(cwd: str) -> list[str]:
    """Return the list of files staged for commit (git diff --cached)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--cwd", required=True)
    args = parser.parse_args()

    smm_dir = Path(args.smm_dir)
    cwd = args.cwd
    agent_id = identity.resolve_agent_id_from_cwd(cwd)

    staged = _staged_files(cwd)
    if not staged:
        print("(no staged files — skip probe)")
        return 0

    candidates = resolves_probe.find_probe_candidates(
        smm_dir, staged, resolves=[], cwd=cwd
    )
    if not candidates:
        print("(no open concerns match staged files — nothing to auto-link)")
        return 0

    fingerprint = resolves_probe.compute_fingerprint(
        staged, [c["id"] for c in candidates], cwd
    )
    markers.marker_write(
        smm_dir,
        markers.REVIEW_FINGERPRINT,
        {
            "fingerprint": fingerprint,
            "candidate_ids": [c["id"] for c in candidates],
            "ts": datetime.now(timezone.utc).isoformat(),
        },
        agent_id,
    )

    # commit_hash=None pre-commit; retro pairs probes with the next commit
    # by probe_candidates intersection, not by commit_hash.
    status_event = resolves_probe.build_probe_status_event(
        candidates, commit_hash=None, agent_id=agent_id
    )
    if status_event:
        _common.append_safe(smm_dir, status_event)

    lines = [f"Found {len(candidates)} open concern(s) your staged files touch:"]
    for c in candidates:
        content = (c.get("content") or "")[:100]
        lines.append(f"  - {c['id']}: {content}")
    lines.extend(
        [
            "",
            "If the commit closes one of these, add a trailer to your commit:",
            "  Resolves-Event: <event-id>",
            "",
            "(Post-commit nudge suppressed via REVIEW_FINGERPRINT marker.)",
        ]
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

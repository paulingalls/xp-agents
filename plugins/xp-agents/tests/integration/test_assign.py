#!/usr/bin/env python3
"""Integration tests for xp-assign: WorktreeCreate hook and shared helpers.

Preload tests in test_assign_preload.py, teammate tests in test_assign_team.py.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from conftest import (
    _IntegrationTestCase,
    _s,
    _sprint_json,
    cleanup_test_worktrees,
)

_PRELOAD_SCRIPT = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"


class TestWorktreeCreateSubprocess(_IntegrationTestCase):
    """WorktreeCreate hook via subprocess with real git repo."""

    def test_creates_worktree_from_non_default_branch(self):
        """On a non-default branch, worktree is created from that branch."""
        # Create a feature branch
        subprocess.run(
            ["git", "checkout", "-b", "feature/v2"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        # Add a commit on the feature branch so it diverges
        (self.tmpdir / "v2.txt").write_text("v2 content")
        subprocess.run(
            ["git", "add", "v2.txt"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "v2 commit"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # Platform sends name only — hook generates path
        result = self._run_script(
            "worktree_create.py",
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": "test-wt",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        wt_path = result.stdout.strip()
        self.assertTrue(Path(wt_path).is_dir(), "Worktree should exist")

        # v2.txt should be present (branched from feature/v2, not main)
        self.assertTrue(
            (Path(wt_path) / "v2.txt").is_file(),
            "Worktree should contain v2.txt from feature branch",
        )

    def test_creates_worktree_on_default_branch(self):
        """On the default branch, worktree is created normally."""
        result = self._run_script(
            "worktree_create.py",
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": "default-wt",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        wt_path = result.stdout.strip()
        self.assertTrue(Path(wt_path).is_dir())

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        super().tearDown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_preload_var(stdout: str, name: str) -> str | None:
    """Extract a VAR=value from preload stdout. Returns value or None."""
    prefix = f"{name}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1]
    return None


# ---------------------------------------------------------------------------
# Sprint fixture helpers for mode selection tests
# ---------------------------------------------------------------------------


def _multi_story_sprint_worktree() -> str:
    """Sprint with independent M/L stories and non-overlapping domains."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "User registration",
                "ready",
                file_domain=["src/auth/register.py", "tests/test_register.py"],
            ),
            _s(
                "story-002",
                "Admin dashboard",
                "ready",
                file_domain=["src/admin/dashboard.py", "tests/test_dashboard.py"],
            ),
        ],
        sprint_id="sprint-001",
        started="2026-04-01",
    )


def _multi_story_sprint_solo_deps() -> str:
    """Sprint with dependency chains (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "User model",
                "ready",
                file_domain=["src/models/user.py"],
            ),
            _s(
                "story-002",
                "User API",
                "ready",
                file_domain=["src/api/user.py"],
                dependencies=["story-001"],
            ),
        ],
        sprint_id="sprint-002",
        started="2026-04-01",
    )


def _multi_story_sprint_all_small() -> str:
    """Sprint with all S stories (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "Fix typo",
                "ready",
                file_domain=["src/ui/header.py"],
            ),
            _s(
                "story-002",
                "Update readme",
                "ready",
                file_domain=["docs/README.md"],
            ),
        ],
        sprint_id="sprint-003",
        started="2026-04-01",
    )


def _multi_story_sprint_no_domains() -> str:
    """Sprint with missing file domains (forces solo mode)."""
    return _sprint_json(
        [
            _s("story-001", "Feature A", "ready"),
            _s("story-002", "Feature B", "ready"),
        ],
        sprint_id="sprint-004",
        started="2026-04-01",
    )


def _multi_story_sprint_overlapping_domains() -> str:
    """Sprint with overlapping file domains (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "Auth flow",
                "ready",
                file_domain=["src/auth/login.py", "src/shared/utils.py"],
            ),
            _s(
                "story-002",
                "Password reset",
                "ready",
                file_domain=["src/auth/reset.py", "src/shared/utils.py"],
            ),
        ],
        sprint_id="sprint-005",
        started="2026-04-01",
    )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for teammate guide injection via SessionStart.

Covers: CLI teammate detection via is_worktree_teammate, teammate guide
content injection at SessionStart, non-teammate paths unaffected.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, write_smm_fixture


class TestTeammateGuideSessionStart(_HookTestCase):
    """CLI teammates get TEAMMATE_GUIDE.md via SessionStart."""

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"

    def setUp(self):
        super().setUp()
        import session_start

        self.session_start = session_start
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("Python 3.10+ only", "convention")],
            risks=[("Auth module fragile", "concern", "problem")],
            wisdom=["TDD always"],
        )

    def _run_teammate(self, **overrides):
        data = {
            "session_id": "t",
            "source": "startup",
            "cwd": self._TEAMMATE_CWD,
            **overrides,
        }
        return self.session_start.run(data, smm_dir=self.smm_dir)

    def test_teammate_gets_teammate_guide_and_values(self):
        """Teammate gets TEAMMATE_GUIDE + XP values, not process guide."""
        result = self._run_teammate()
        assert result is not None
        self.assertIn("Teammate Guide", result)
        self.assertIn("Extreme Programming", result)
        self.assertNotIn("EnterPlanMode", result)

    def test_teammate_guide_has_tdd_and_domain(self):
        """Teammate guide includes TDD, small steps, file domain."""
        result = self._run_teammate()
        assert result is not None
        self.assertIn("TDD", result)
        self.assertIn("small steps", result.lower())
        self.assertIn("file domain", result.lower())
        self.assertIn("raise a concern", result.lower())

    def test_teammate_guide_has_quality_items(self):
        """Teammate guide has quality-focused items."""
        result = self._run_teammate()
        assert result is not None
        self.assertIn("code smells", result.lower())
        self.assertIn("500 lines", result)

    def test_teammate_guide_has_review_cycle(self):
        """Teammate guide has review cycle commands (security at close-skill Step 4)."""
        result = self._run_teammate()
        assert result is not None
        self.assertIn("/code-review", result)
        self.assertIn("/xp-quality-review", result)
        self.assertNotIn("/xp-security-triage", result)
        self.assertIn("/security-review", result)

    def test_teammate_guide_has_event_recording(self):
        """Teammate guide shows how to record events."""
        result = self._run_teammate()
        assert result is not None
        self.assertIn("append.sh", result)

    def test_teammate_no_kickoff(self):
        """Teammate does NOT get kickoff prompt."""
        result = self._run_teammate()
        assert result is not None
        self.assertNotIn("xp-kickoff", result)

    def test_teammate_guide_covers_in_place_main_checkout(self):
        """story-008: the guide documents the in-place (main-checkout) solo
        delegation case, not just the worktree case — a teammate may run in the
        main checkout on the story branch directly."""
        result = self._run_teammate()
        assert result is not None
        self.assertIn("in-place", result.lower())
        self.assertIn("main checkout", result.lower())

    def test_non_teammate_worktree_gets_normal_path(self):
        """Non-teammate worktree gets normal SessionStart (with kickoff)."""
        self._write_events([])
        result = self._run_teammate(
            cwd="/home/user/project/.claude/worktrees/explore-abc/src"
        )
        assert result is not None
        self.assertIn("xp-kickoff", result)
        self.assertNotIn("Teammate Guide", result)


if __name__ == "__main__":
    unittest.main()

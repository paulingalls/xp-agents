#!/usr/bin/env python3
"""Integration tests for story-close cadence routing (story-005).

In 'story' cadence the per-commit review gate is relaxed, so story-close
runs the full review cycle at the merge boundary. preload.sh reads the
cadence and emits REVIEW_PATH (full-cycle | close-reviewer); SKILL.md
Step 4.5 splits into 4.5a (close-reviewer) and 4.5b (full cycle), routed
by REVIEW_PATH. read_review_cadence fail-safes to 'commit'.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from conftest import _extract_preload_var, _IntegrationTestCase

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md"


class TestStoryCloseCadencePreload(_IntegrationTestCase):
    """preload.sh emits REVIEW_PATH from the session cadence marker."""

    def _set_cadence(self, value: str) -> None:
        (self.smm_dir / ".review-cadence").write_text(value)

    def _review_path(self) -> str | None:
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        return _extract_preload_var(result.stdout, "REVIEW_PATH")

    def test_story_cadence_emits_full_cycle(self):
        """AC#1: 'story' cadence → REVIEW_PATH=full-cycle."""
        self._set_cadence("story")
        self.assertEqual(self._review_path(), "full-cycle")

    def test_commit_cadence_emits_close_reviewer(self):
        """AC#2: 'commit' cadence → REVIEW_PATH=close-reviewer."""
        self._set_cadence("commit")
        self.assertEqual(self._review_path(), "close-reviewer")

    def test_unset_cadence_emits_close_reviewer(self):
        """AC#2: no marker → REVIEW_PATH=close-reviewer (fail-safe default)."""
        self.assertEqual(self._review_path(), "close-reviewer")


class TestStoryCloseCadenceProse(unittest.TestCase):
    """SKILL.md Step 4.5 splits into REVIEW_PATH-routed sub-steps."""

    @classmethod
    def setUpClass(cls):
        cls.body = _SKILL_MD.read_text()

    def test_skill_has_4_5a_and_4_5b(self):
        """AC#3: 4.5a/4.5b routed by REVIEW_PATH; 4.5b runs /xp-quality-review."""
        self.assertIn("Step 4.5a", self.body)
        self.assertIn("Step 4.5b", self.body)
        self.assertIn("REVIEW_PATH=close-reviewer", self.body)
        self.assertIn("REVIEW_PATH=full-cycle", self.body)
        # 4.5b runs /xp-quality-review only — the per-story workflow /code-review
        # was removed (role lever); the full /code-review runs at sprint close.
        self.assertIn("/xp-quality-review", self.body)
        self.assertNotIn("/code-review", self.body)

    def test_retains_domain_drift_surface(self):
        """AC#3: the deterministic file_domain drift surface (Step 1b) stays."""
        self.assertIn("validate-domain", self.body)


if __name__ == "__main__":
    unittest.main()

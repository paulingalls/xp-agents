#!/usr/bin/env python3
"""Integration tests for xp-kickoff free-branch behavior.

Covers two surfaces:
- check_session_needs.sh emits an ORPHAN_FREE_BRANCHES section when
  branching.list_free returns non-empty, and omits it otherwise.
- xp-kickoff/SKILL.md Step 2 free fork (calls branching.py create-free
  under a stage gate) and Step 0 orphan-triage prose are pinned by
  guard tests so a future edit cannot silently drop them.

The end-to-end auto-create flow lives in story-004's lifecycle
capstone; this file pins the contracts only.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import write_system_context
from conftest import _IntegrationTestCase

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-kickoff" / "scripts" / "check_session_needs.sh"
_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-kickoff" / "SKILL.md"


class TestKickoffOrphanPreload(_IntegrationTestCase):
    """check_session_needs.sh emits the ORPHAN_FREE_BRANCHES section."""

    def setUp(self):
        super().setUp()
        self.assertTrue(_PRELOAD.is_file(), f"Preload script missing: {_PRELOAD}")
        # Stage 1 — free branches are only created at stage >= 1.
        write_system_context(self.smm_dir, stage=1)

    def _run(self) -> subprocess.CompletedProcess:
        return self._run_preload(_PRELOAD)

    def test_no_section_when_no_free_branches(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ORPHAN_FREE_BRANCHES", result.stdout)

    def test_section_lists_free_branches(self):
        # Create a real free-style branch so list_free returns it.
        # The user-namespace prefix is whatever identity.user_namespace
        # resolves to in the hermetic test repo (typically "test"); list_free
        # filters by that prefix, so we must use it here too.
        from identity import user_namespace

        ns = user_namespace(str(self.tmpdir))
        branch = f"{ns}/free-2026-04-25-tinker"
        subprocess.run(
            ["git", "branch", branch],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ORPHAN_FREE_BRANCHES", result.stdout)
        self.assertIn(branch, result.stdout)


class TestKickoffSkillTextFreeBranch(unittest.TestCase):
    """SKILL.md prose pins the Step 2 free fork + Step 0 orphan-triage contracts."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_free_fork_calls_create_free_under_stage_gate(self):
        self.assertIn("create-free", self.text)
        self.assertIn("STAGE >= 2", self.text)

    def test_orphan_detection_step_lists_branches(self):
        # The orphan-detection step must read the ORPHAN_FREE_BRANCHES
        # section from the preload and surface its branches to the user.
        self.assertIn("ORPHAN_FREE_BRANCHES", self.text)

    def test_orphan_detection_offers_merge_keep_delete(self):
        # Per story-002 design and milestone constraints, each orphan
        # gets a merge/keep/delete prompt. Pin all three options.
        lower = self.text.lower()
        for option in ("merge", "keep", "delete"):
            self.assertIn(option, lower, f"Missing orphan-detection option: {option}")

    def test_orphan_merge_routes_through_free_close(self):
        # "Merge" must invoke /xp-free-close so the orphan goes through
        # the same review+merge path as an interactively closed branch.
        self.assertIn("/xp-free-close", self.text)


if __name__ == "__main__":
    unittest.main()

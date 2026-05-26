#!/usr/bin/env python3
"""Prose pins for xp-sprint-start's M3 surface-coverage + auto-capstone wiring.

Pins the declarative steps the skill must carry: a per-uncovered-surface
coverage concern emitted via surface_coverage.py, an auto-generated capstone
built through `sprint_cli build-capstone` (user-confirmable, behavior-shaped),
and the allowed-tools entry the concern step needs.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _split_frontmatter_body


class TestSurfaceCapstoneWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (_PLUGIN_ROOT / "skills/xp-sprint-start/SKILL.md").read_text()
        cls.frontmatter, cls.body = _split_frontmatter_body(text)

    def _region(self, start: str, end: str) -> str:
        # Colon-terminated anchors so a future "### Step 2b:" can't
        # prefix-collide with "### Step 2:" and silently shrink the slice.
        return self.body[self.body.index(start) : self.body.index(end)]

    def test_surface_coverage_concern_step_invokes_helper(self):
        region = self._region("### Step 1b:", "### Step 2:")
        self.assertIn("surface_coverage.py", region)
        self.assertIn("uncovered", region)
        self.assertIn("--milestone", region)

    def test_concern_step_emits_one_medium_concern_per_surface(self):
        region = self._region("### Step 1b:", "### Step 2:")
        self.assertIn('--type "concern"', region)
        self.assertIn('--severity "medium"', region)
        # The concern content must reference the milestone + the surface,
        # not just fire a generic concern (AC #1).
        self.assertIn("Milestone", region)
        self.assertIn("surface", region)

    def test_capstone_step_uses_build_capstone_cli(self):
        region = self._region("### Step 3b:", "### Step 4:")
        self.assertIn("build-capstone", region)

    def test_capstone_is_user_confirmable_and_behavior_shaped(self):
        region = self._region("### Step 3b:", "### Step 4:")
        self.assertIn("opt-in", region)
        self.assertIn("behavior-shaped", region)
        # The capstone must start in 'ready' status (AC #2).
        self.assertIn("`ready`", region)

    def test_capstone_surfaces_scoped_to_covered(self):
        # Only covered touched surfaces feed --surfaces; uncovered ones have
        # no harness and stay tracked by the Step 1b concern. Pin a phrase
        # unique to the new guidance — "covered" alone matches "uncovered".
        region = self._region("### Step 3b:", "### Step 4:")
        self.assertIn("minus the uncovered", region)

    def test_allowed_tools_permits_surface_coverage_cli(self):
        self.assertIn("surface_coverage.py", self.frontmatter)


class TestVerifiableAcceptanceCommandPin(unittest.TestCase):
    """Pin the verifiable-acceptance-command authoring rule (decision
    4b2454f96b41).

    The verify-touch gate can only confirm a story authored its proof when
    the acceptance command names the specific test file. A bare script alias
    (`npm run test:e2e`) hides the proof file in config — non-verifiable.
    sprint-start must steer authoring toward a path-naming command.
    """

    @classmethod
    def setUpClass(cls):
        text = (_PLUGIN_ROOT / "skills/xp-sprint-start/SKILL.md").read_text()
        cls.frontmatter, cls.body = _split_frontmatter_body(text)
        cls.body_lower = cls.body.lower()

    def test_command_must_name_proof_file_in_file_domain(self):
        # The rule must direct that the command names the test file it runs,
        # and that the named path lives in the story's file_domain.
        self.assertIn("file_domain", self.body_lower)
        self.assertIn("verify-touch", self.body_lower)

    def test_prefers_path_naming_over_script_alias(self):
        # Pin the script-alias contrast so a trim can't drop the steer toward
        # the path-naming binary form.
        self.assertIn("script alias", self.body_lower)


if __name__ == "__main__":
    unittest.main()

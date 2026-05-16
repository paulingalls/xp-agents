#!/usr/bin/env python3
"""xp-story-close MUST NOT emit file_domain drift as concern events.

Per convention 9074fed13abf, file_domain drift is a planning signal
(retro picks it up from cascade_size, not from concern events). Step 1b
previously appended a `--type concern --metadata '{"kind":"file_domain_drift"}'`
event on every drift — re-polluting the unresolved-concern surface each
sprint close. The close-reviewer agent still surfaces drift via its
Concern/Block summary when severity warrants; that path is independent.

This test pins the absence so a future edit doesn't silently reintroduce
the noisy emission.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _split_frontmatter_body


class TestStoryCloseStep1bNoDriftConcern(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(
            (_PLUGIN_ROOT / "skills/xp-story-close/SKILL.md").read_text()
        )
        start = cls.body.index("## Step 1b: Validate file_domain")
        end = cls.body.index("## Step 2:")
        cls.region = cls.body[start:end]

    def test_no_append_sh_concern_in_step1b(self):
        self.assertNotIn("--type concern", self.region)
        self.assertNotIn('--type "concern"', self.region)

    def test_no_file_domain_drift_kind_metadata_in_step1b(self):
        self.assertNotIn("file_domain_drift", self.region)


if __name__ == "__main__":
    unittest.main()

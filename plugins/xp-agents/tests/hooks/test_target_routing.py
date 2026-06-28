#!/usr/bin/env python3
"""Tests for target_routing.strip_our_namespace — shared helper used by
review_cycle_done, subagent_stop, and accept_terminal to scope name-routing
to our plugin's namespace.

The 3 hooks each have integration coverage that exercises this helper
through their own surface; this file pins the helper directly so a future
refactor of strip_our_namespace breaks here first (clearer failure than
seeing 3 unrelated hook tests start failing at once).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import target_routing


class TestStripOurNamespace(unittest.TestCase):
    def test_bare_name_returned_unchanged(self):
        self.assertEqual(target_routing.strip_our_namespace("xp-assign"), "xp-assign")
        self.assertEqual(
            target_routing.strip_our_namespace("code-review"), "code-review"
        )

    def test_our_namespace_strips_to_bare(self):
        self.assertEqual(
            target_routing.strip_our_namespace("xp-agents:xp-assign"), "xp-assign"
        )
        self.assertEqual(
            target_routing.strip_our_namespace("xp-agents:code-review"), "code-review"
        )

    def test_other_plugin_namespace_returns_none(self):
        self.assertIsNone(target_routing.strip_our_namespace("otherplugin:xp-assign"))
        self.assertIsNone(target_routing.strip_our_namespace("third:code-review"))

    def test_empty_name_returns_none(self):
        self.assertIsNone(target_routing.strip_our_namespace(""))

    def test_malformed_namespace_returns_none(self):
        """Empty plugin namespace (':bare') is not our namespace."""
        self.assertIsNone(target_routing.strip_our_namespace(":code-review"))


if __name__ == "__main__":
    unittest.main()

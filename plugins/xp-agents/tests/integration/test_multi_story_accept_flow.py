#!/usr/bin/env python3
"""Capstone E2E for sprint-056: ACCEPT_ACTIVE marker lifecycle.

The per-piece contracts are pinned in their own files (story-001's
TestAcceptMarker in test_pre_tool_write_gates.py; story-004's
TestSprintClosePreload in test_sprint_close.py; story-002's
TestXpAcceptPreloadAcceptActive in test_preload_markers.py). This file
is the single place that walks the full lifecycle in one go — proves
the wiring is correct end-to-end and serves as the canonical regression
fence for c188c64454fd.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import pre_tool_write
from conftest import _IntegrationTestCase, _make_write_input, _s, _sprint_json

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_XP_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"
_XP_SPRINT_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"
)


class TestMultiStoryAcceptFlow(_IntegrationTestCase):
    """E2E sprint-056 acceptance lifecycle."""

    def test_full_lifecycle_arms_suppresses_then_consumes(self):
        # E2E AC + canonical regression guard for c188c64454fd. Walks the
        # full sequence: xp-accept arms the marker, pre_tool_write
        # respects it, xp-sprint-close consumes it, pre_tool_write's
        # gate is restored.
        sprint = _sprint_json(
            [
                _s("story-001", "First", "reviewing"),
                _s("story-002", "Second", "in-progress"),
                _s("story-003", "Third", "in-progress"),
            ],
            sprint_id="sprint-test",
            started="2026-05-04",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)

        # main agent_id (default) — pre_tool_write.run early-returns at
        # is_xp_agent for xp-* subagents, so a teammate-style input
        # would silently skip the gate this lifecycle exercises.
        main_input = _make_write_input(session_id="t", cwd="/tmp")

        # Step 1 (story-002): xp-accept preload arms ACCEPT_ACTIVE
        accept_result = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(
            accept_result.returncode,
            0,
            f"xp-accept preload failed: {accept_result.stderr}",
        )
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))

        # Step 2 (story-001): pre_tool_write does NOT re-arm .accept
        pre_tool_write.run(main_input, smm_dir=self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))

        # Step 3 (story-004): xp-sprint-close consumes ACCEPT_ACTIVE
        close_result = self._run_preload(_XP_SPRINT_CLOSE_PRELOAD)
        self.assertEqual(
            close_result.returncode,
            0,
            f"xp-sprint-close preload failed: {close_result.stderr}",
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))

        # Step 4 (gate restored): pre_tool_write re-arms .accept now
        # that the suppressor is gone — proves the marker mechanism is
        # reversible, not a permanent bypass.
        pre_tool_write.run(main_input, smm_dir=self.smm_dir)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT))


if __name__ == "__main__":
    unittest.main()

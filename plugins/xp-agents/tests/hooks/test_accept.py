#!/usr/bin/env python3
"""Tests for accept_gate.py and accept_done.py hooks."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _make_skill_input, _make_stop_input, make_event

SPRINT_IN_PROGRESS = """\
# Sprint: Build auth

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** in-progress
- **Dependencies:** none
"""

SPRINT_READY_ONLY = """\
# Sprint: Build auth

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** ready
- **Dependencies:** none
"""

SPRINT_ALL_DONE = """\
# Sprint: Build auth

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** done

### story-002: As a user I can register
- **Size:** S
- **Status:** deferred
"""


# ===========================================================================
# accept_gate.py — Stop hook
# ===========================================================================


class TestAcceptGate(_HookTestCase):
    """M8c: accept_gate blocks stop when in-progress stories without accept."""

    def test_xp_agent_skips(self):
        import accept_gate

        result = accept_gate.run(
            _make_stop_input(agent_type="xp-nav"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_stop_hook_active_skips(self):
        import accept_gate

        result = accept_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_no_smm_dir_allows_stop(self):
        import accept_gate

        fake_dir = Path("/nonexistent/smm")
        result = accept_gate.run(_make_stop_input(), smm_dir=fake_dir)
        self.assertIsNone(result)

    def test_no_sprint_file_allows_stop(self):
        import accept_gate

        result = accept_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_in_progress_allows_stop(self):
        import accept_gate

        (self.smm_dir / "sprint.md").write_text(SPRINT_READY_ONLY)
        result = accept_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_in_progress_with_accept_marker_allows_stop(self):
        import accept_gate

        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        result = accept_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_in_progress_without_accept_marker_blocks(self):
        import accept_gate

        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        result = accept_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("xp-accept", result)

    def test_corrupt_sprint_allows_stop(self):
        import accept_gate

        (self.smm_dir / "sprint.md").write_text("")
        result = accept_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_all_done_allows_stop(self):
        import accept_gate

        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DONE)
        result = accept_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)


# ===========================================================================
# accept_done.py — PostToolUse:Skill hook
# ===========================================================================


class TestAcceptDone(_HookTestCase):
    """M8c: accept_done sets marker and detects sprint completion."""

    def test_xp_agent_skips(self):
        import accept_done

        result = accept_done.run(
            _make_skill_input(agent_type="xp-nav"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_ignores_other_skills(self):
        import accept_done

        result = accept_done.run(
            _make_skill_input("simplify"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_sets_accept_marker(self):
        import accept_done

        self._write_events([make_event()])
        accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_qualified_skill_name(self):
        import accept_done

        self._write_events([make_event()])
        accept_done.run(
            _make_skill_input("xp-agents:xp-accept"),
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_sprint_complete_nudges_review(self):
        import accept_done

        self._write_events([make_event()])
        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DONE)
        result = accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("sprint-review", result.lower())

    def test_sprint_not_complete_no_nudge(self):
        import accept_done

        self._write_events([make_event()])
        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        result = accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        # Should return something (confirmation) but NOT mention sprint-review
        if result:
            self.assertNotIn("sprint-review", result.lower())

    def test_no_sprint_file_no_nudge(self):
        import accept_done

        self._write_events([make_event()])
        result = accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("sprint-review", result.lower())

    def test_logs_status_event(self):
        import accept_done

        self._write_events([make_event()])
        accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        events = self._read_events()
        accept_events = [e for e in events if "accept" in e.get("content", "").lower()]
        self.assertGreater(len(accept_events), 0)

    def test_iteration_complete_metadata(self):
        """Accept event has action=iteration_complete for retro counting."""
        import accept_done

        self._write_events([make_event()])
        accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        events = self._read_events()
        iter_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "iteration_complete"
        ]
        self.assertEqual(len(iter_events), 1)


if __name__ == "__main__":
    unittest.main()

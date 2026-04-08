#!/usr/bin/env python3
"""Tests for accept_done.py and accept preload.

Stop-gate tests migrated to test_sprint_stop_gate.py (M1 of the
PostToolUse:Skill replacement plan).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    _HookTestCase,
    _IntegrationTestCase,
    _make_skill_input,
    make_event,
)

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

    def test_consumes_accept_marker(self):
        """Accept done clears the 'needs acceptance' marker."""
        import accept_done

        self._write_events([make_event()])
        (self.smm_dir / ".accept").write_text("done")
        accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_consumes_marker_qualified_name(self):
        """Also works with fully-qualified skill name."""
        import accept_done

        self._write_events([make_event()])
        (self.smm_dir / ".accept").write_text("done")
        accept_done.run(
            _make_skill_input("xp-agents:xp-accept"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_no_marker_no_error(self):
        """Accept done without marker present should not error."""
        import accept_done

        self._write_events([make_event()])
        accept_done.run(_make_skill_input("xp-accept"), smm_dir=self.smm_dir)
        self.assertFalse((self.smm_dir / ".accept").exists())

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


# ===========================================================================
# preload.sh — Accept preload script
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-accept"
    / "scripts"
    / "preload.sh"
)


class TestAcceptPreload(_IntegrationTestCase):
    """M16: preload outputs path, not full sprint content."""

    def test_preload_no_sprint(self):
        """Outputs ERROR when no sprint.md exists."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)

    def test_preload_no_in_progress(self):
        """Outputs NO_IN_PROGRESS when no in-progress stories."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_READY_ONLY)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NO_IN_PROGRESS", result.stdout)

    def test_preload_outputs_path_not_content(self):
        """Outputs SPRINT_FILE path, not full sprint content."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_FILE=", result.stdout)
        # Should NOT contain full sprint content
        self.assertNotIn("**Status:** in-progress", result.stdout)

    def test_preload_shows_in_progress_count(self):
        """Outputs count of in-progress stories."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("in-progress", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for kickoff hooks: kickoff_gate and kickoff_done.

Split from test_session_lifecycle.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _make_skill_input, make_event

# ===========================================================================
# kickoff_gate.py tests
# ===========================================================================


class TestKickoffGate(_HookTestCase):
    """Tests for UserPromptSubmit kickoff gate."""

    def test_blocks_when_marker_exists(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").touch()
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")

    def test_allows_session_review_command(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").touch()
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "/xp-kickoff"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_kickoff_clears_marker(self):
        """Marker cleared when /xp-kickoff runs so sub-skills can AskUserQuestion."""
        import kickoff_gate

        marker = self.smm_dir / ".needs-kickoff"
        marker.write_text("startup")
        kickoff_gate.run(
            {"session_id": "test", "prompt": "/xp-kickoff"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(marker.exists())

    def test_subsequent_prompts_pass_after_kickoff_clears_marker(self):
        """After /xp-kickoff clears the marker, AskUserQuestion prompts pass."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        kickoff_gate.run(
            {"session_id": "test", "prompt": "/xp-kickoff"},
            smm_dir=self.smm_dir,
        )
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "Build a TODO app"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_passes_when_no_marker(self):
        import kickoff_gate

        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").touch()
        result = kickoff_gate.run(
            {
                "session_id": "test",
                "prompt": "work",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_clear_marker_nudges_instead_of_blocking(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("clear")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result, "nudge")

    def test_startup_marker_blocks(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["decision"], "block")

    def test_skips_task_notifications(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        task_prompt = (
            "<task-notification>\n<task-id>abc</task-id>\n</task-notification>"
        )
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": task_prompt},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


# ===========================================================================
# M8a: kickoff_gate sprint marker info tests
# ===========================================================================


class TestKickoffGateSprintInfo(_HookTestCase):
    """M8a: kickoff_gate includes sprint marker info in block message."""

    def test_block_includes_product_spec_info(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        (self.smm_dir / ".needs-product-spec").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("product", result["reason"].lower())

    def test_block_includes_sprint_info(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("sprint", result["reason"].lower())

    def test_block_includes_both(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        (self.smm_dir / ".needs-product-spec").write_text("startup")
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("product", result["reason"].lower())
        self.assertIn("sprint", result["reason"].lower())

    def test_block_no_sprint_markers(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertNotIn("product", result["reason"].lower())

    def test_nudge_still_works_with_sprint_markers(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("clear")
        (self.smm_dir / ".needs-product-spec").write_text("clear")
        (self.smm_dir / ".needs-sprint").write_text("clear")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result, "nudge")


# ===========================================================================
# PostToolUse:Skill — kickoff_done.py
# ===========================================================================

import kickoff_done  # noqa: E402


class TestKickoffDone(_HookTestCase):
    """PostToolUse:Skill hook injects SMM + behavioral guide after kickoff."""

    def test_injects_smm_file_content(self):
        """Should inject SHARED_MENTAL_MODEL.md content after housekeeping."""
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n\n## Intent\n- Ship v1\n"
        )
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)

    def test_injects_process_guide(self):
        """Should inject PROCESS_GUIDE.md after xp-housekeeping."""
        self._write_events([make_event("goal", content="Ship v1")])
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("EnterPlanMode", result)

    def test_no_xp_values_in_kickoff_done(self):
        """Values injected at session start, not kickoff done."""
        self._write_events([make_event("goal", content="Ship v1")])
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("XP Values", result)

    def test_ignores_other_skills(self):
        """Should return None for non-housekeeping skills."""
        self._write_events([make_event("goal", content="Ship v1")])
        result = kickoff_done.run(_make_skill_input("simplify"), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """Should skip for xp-agent types."""
        result = kickoff_done.run(
            _make_skill_input(agent_type="xp-test"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    def test_injects_smm_and_process(self):
        """Output has SMM content and process guide."""
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n\n## Intent\n- Ship v1\n"
        )
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertIn("EnterPlanMode", result)

    def test_graceful_without_smm_file(self):
        """No SMM file — still returns process guide."""
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").unlink(missing_ok=True)
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("EnterPlanMode", result)

    def test_deletes_needs_session_review_marker(self):
        """Should delete .needs-kickoff marker after injection."""
        marker = self.smm_dir / ".needs-kickoff"
        marker.touch()
        self._write_events([make_event("goal", content="Ship v1")])
        kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse(marker.exists())


# ===========================================================================
# M8a: kickoff_done sprint nudge tests
# ===========================================================================

_SPRINT_READY_ONLY = """\
# Sprint: Build auth
## Stories
### story-001: As a user I can log in
- **Size:** M
- **Status:** ready
"""

_SPRINT_IN_PROGRESS = """\
# Sprint: Build auth
## Stories
### story-001: As a user I can log in
- **Size:** M
- **Status:** in-progress
"""


class TestKickoffDoneSprintNudge(_HookTestCase):
    """M8a: kickoff_done nudges when no in-progress stories."""

    def test_nudges_when_no_in_progress_stories(self):
        self._write_events([make_event("goal", content="Ship v1")])
        (self.smm_dir / "sprint.md").write_text(_SPRINT_READY_ONLY)
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("No stories marked", result)

    def test_no_nudge_when_in_progress_exists(self):
        self._write_events([make_event("goal", content="Ship v1")])
        (self.smm_dir / "sprint.md").write_text(_SPRINT_IN_PROGRESS)
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("No stories marked", result)

    def test_no_nudge_when_no_sprint_file(self):
        self._write_events([make_event("goal", content="Ship v1")])
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("No stories marked", result)

    def test_clears_sprint_markers(self):
        self._write_events([make_event("goal", content="Ship v1")])
        (self.smm_dir / ".needs-product-spec").write_text("startup")
        (self.smm_dir / ".needs-sprint").write_text("startup")
        kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".needs-product-spec").exists())
        self.assertFalse((self.smm_dir / ".needs-sprint").exists())

    def test_nudge_appended_to_guide(self):
        self._write_events([make_event("goal", content="Ship v1")])
        (self.smm_dir / "sprint.md").write_text(_SPRINT_READY_ONLY)
        result = kickoff_done.run(
            _make_skill_input("xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIn("EnterPlanMode", result)
        self.assertIn("No stories marked", result)


if __name__ == "__main__":
    unittest.main()

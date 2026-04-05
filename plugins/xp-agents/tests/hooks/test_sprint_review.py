#!/usr/bin/env python3
"""Tests for prepare_review_data.py, sprint_review_done.py, and preload."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-sprint-review" / "scripts"
    ),
)

from conftest import _HookTestCase, _IntegrationTestCase, _make_skill_input

# ---------------------------------------------------------------------------
# Sprint fixtures
# ---------------------------------------------------------------------------

SPRINT_MIXED = """\
# Sprint: Build auth system

- **Sprint ID:** sprint-001
- **Started:** 2026-03-15

## Stories

### story-001: User login
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: User registration
- **Size:** S
- **Status:** done
- **Dependencies:** none

### story-003: Password reset
- **Size:** M
- **Status:** deferred
- **Dependencies:** story-001

### story-004: OAuth integration
- **Size:** L
- **Status:** ready
- **Dependencies:** story-001
"""

SPRINT_ALL_DONE = """\
# Sprint: Build auth system

- **Sprint ID:** sprint-001
- **Started:** 2026-03-15

## Stories

### story-001: User login
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: User registration
- **Size:** S
- **Status:** done
- **Dependencies:** none

### story-003: Password reset
- **Size:** M
- **Status:** done
- **Dependencies:** story-001
"""

SPRINT_ALL_DEFERRED = """\
# Sprint: Build auth system

- **Sprint ID:** sprint-001
- **Started:** 2026-03-15

## Stories

### story-001: User login
- **Size:** M
- **Status:** deferred
- **Dependencies:** none

### story-002: User registration
- **Size:** S
- **Status:** deferred
- **Dependencies:** none
"""

SPRINT_NO_ID = """\
# Sprint: Build auth system

## Stories

### story-001: User login
- **Size:** M
- **Status:** done
"""

PRODUCT_SPEC = """\
# Product Spec: Auth System

## Features

### User Registration [planned]
- Users can register with email and password

### JWT Authentication [planned]
- Login returns JWT tokens

### Password Reset [planned]
- Reset password via email link
"""


# ===========================================================================
# prepare_review_data.py
# ===========================================================================


class TestPrepareReviewData(_HookTestCase):
    """M11: prepare_review_data reads sprint + product_spec, computes velocity."""

    def test_basic_velocity(self):
        """2 done, 1 deferred, 1 ready -> planned=4, delivered=2, carried=1."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 4)
        self.assertEqual(vel["stories_delivered"], 2)
        self.assertEqual(vel["stories_carried"], 1)

    def test_review_input_structure(self):
        """Output dict has all required keys."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        for key in ("sprint_id", "goal", "velocity", "sprint_md", "product_spec_md"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_no_sprint_returns_none(self):
        """No sprint.md -> None."""
        import prepare_review_data

        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNone(result)

    def test_missing_product_spec_empty_string(self):
        """No product_spec.md -> product_spec_md=''."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result["product_spec_md"], "")

    def test_product_spec_included_raw(self):
        """product_spec_md contains exact raw text."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        (self.smm_dir / "product_spec.md").write_text(PRODUCT_SPEC)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result["product_spec_md"], PRODUCT_SPEC)

    def test_all_done_velocity(self):
        """3/3 done -> planned=3, delivered=3, carried=0."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DONE)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 3)
        self.assertEqual(vel["stories_delivered"], 3)
        self.assertEqual(vel["stories_carried"], 0)

    def test_all_deferred_velocity(self):
        """0/2 delivered, 2/2 carried."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DEFERRED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 2)
        self.assertEqual(vel["stories_delivered"], 0)
        self.assertEqual(vel["stories_carried"], 2)

    def test_atomic_write(self):
        """.sprint-review-input.json exists after run."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        prepare_review_data.run(self.smm_dir)
        self.assertTrue((self.smm_dir / ".sprint-review-input.json").exists())

    def test_malformed_sprint_returns_none(self):
        """Sprint without sprint_id -> None."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_NO_ID)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNone(result)

    def test_sprint_id_in_output(self):
        """sprint_id matches what's in sprint.md."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertEqual(result["sprint_id"], "sprint-001")

    def test_goal_in_output(self):
        """goal matches sprint heading."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertEqual(result["goal"], "Build auth system")


# ===========================================================================
# sprint_review_done.py
# ===========================================================================


class TestSprintReviewDone(_HookTestCase):
    """M11: sprint_review_done records sprint end event and nudges retro."""

    def _seed_sprint(self, content: str = SPRINT_MIXED) -> None:
        (self.smm_dir / "sprint.md").write_text(content)

    def test_xp_agent_skips(self):
        import sprint_review_done

        result = sprint_review_done.run(
            _make_skill_input(agent_type="xp-nav"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_ignores_other_skills(self):
        import sprint_review_done

        result = sprint_review_done.run(
            _make_skill_input("simplify"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_matches_qualified_name(self):
        import sprint_review_done

        self._seed_sprint()
        result = sprint_review_done.run(
            _make_skill_input("xp-agents:xp-sprint-review"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)

    def test_matches_unqualified_name(self):
        import sprint_review_done

        self._seed_sprint()
        result = sprint_review_done.run(
            _make_skill_input("xp-sprint-review"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)

    def test_returns_retro_nudge(self):
        import sprint_review_done

        self._seed_sprint()
        result = sprint_review_done.run(
            _make_skill_input("xp-sprint-review"), smm_dir=self.smm_dir
        )
        self.assertIn("sprint-retro", result.lower())

    def test_logs_sprint_end_event(self):
        """Sprint end event with type=sprint, action=end, velocity."""
        import sprint_review_done

        self._seed_sprint()
        sprint_review_done.run(
            _make_skill_input("xp-sprint-review"), smm_dir=self.smm_dir
        )
        events = self._read_events()
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        self.assertEqual(len(sprint_events), 1)
        meta = sprint_events[0].get("metadata", {})
        self.assertEqual(meta["action"], "end")
        self.assertEqual(meta["sprint_id"], "sprint-001")
        self.assertIn("stories_planned", meta)
        self.assertIn("stories_delivered", meta)
        self.assertIn("stories_carried", meta)

    def test_sprint_end_velocity_values(self):
        """Velocity in sprint end event matches sprint.md data."""
        import sprint_review_done

        self._seed_sprint(SPRINT_MIXED)
        sprint_review_done.run(
            _make_skill_input("xp-sprint-review"), smm_dir=self.smm_dir
        )
        events = self._read_events()
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        meta = sprint_events[0]["metadata"]
        self.assertEqual(meta["stories_planned"], 4)
        self.assertEqual(meta["stories_delivered"], 2)
        self.assertEqual(meta["stories_carried"], 1)

    def test_cleans_up_input_file(self):
        import sprint_review_done

        self._seed_sprint()
        (self.smm_dir / ".sprint-review-input.json").write_text("{}")
        sprint_review_done.run(
            _make_skill_input("xp-sprint-review"), smm_dir=self.smm_dir
        )
        self.assertFalse((self.smm_dir / ".sprint-review-input.json").exists())

    def test_no_sprint_graceful(self):
        """No sprint.md -> still returns nudge, no crash."""
        import sprint_review_done

        result = sprint_review_done.run(
            _make_skill_input("xp-sprint-review"), smm_dir=self.smm_dir
        )
        # Should return nudge even without sprint data
        self.assertIsNotNone(result)

    def test_no_smm_dir_returns_none(self):
        import sprint_review_done

        result = sprint_review_done.run(
            _make_skill_input("xp-sprint-review"),
            smm_dir=Path("/nonexistent/path"),
        )
        self.assertIsNone(result)


# ===========================================================================
# preload.sh — Integration tests
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-review"
    / "scripts"
    / "preload.sh"
)


class TestSprintReviewPreload(_IntegrationTestCase):
    """M11: preload.sh runs prepare_review_data and outputs paths."""

    def _run_preload(self) -> subprocess.CompletedProcess:
        """Run preload.sh as a subprocess."""
        if not _PRELOAD_SCRIPT.is_file():
            self.skipTest("preload.sh not yet created")
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data_dir)
        return subprocess.run(
            ["bash", str(_PRELOAD_SCRIPT)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_review_input(self):
        """Preload output includes REVIEW_INPUT= line."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_sprint_graceful(self):
        """No sprint.md -> exits 0, no REVIEW_INPUT."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_guide(self):
        """Preload no longer dumps guide (SubagentStart handles it)."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Behavioral Guide", result.stdout)

    def test_preload_creates_review_input_file(self):
        """Preload creates .sprint-review-input.json in SMM dir."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / ".sprint-review-input.json").exists())


if __name__ == "__main__":
    unittest.main()

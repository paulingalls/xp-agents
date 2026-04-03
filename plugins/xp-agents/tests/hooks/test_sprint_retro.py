#!/usr/bin/env python3
"""Tests for prepare_sprint_retro_data.py and preload."""

import json
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
    str(Path(__file__).parent.parent.parent / "skills" / "xp-sprint-retro" / "scripts"),
)

from conftest import _HookTestCase, _IntegrationTestCase

# ---------------------------------------------------------------------------
# Sprint fixture
# ---------------------------------------------------------------------------

SPRINT_CONTENT = """\
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
- **Size:** L
- **Status:** deferred
- **Dependencies:** story-001
"""

SPRINT_NO_ID = """\
# Sprint: Test

## Stories

### story-001: Something
- **Status:** done
"""


def _make_retro_file(
    smm_dir: Path, timestamp: str, keep: int = 1, fix: int = 0, try_count: int = 0
) -> None:
    """Create a mock retrospective JSON file."""
    retro_dir = smm_dir / "retrospectives"
    retro_dir.mkdir(exist_ok=True)
    filename = timestamp.replace(":", "-").replace("+", "_")[:19] + ".json"
    data = {
        "timestamp": timestamp,
        "keep": [{"content": f"keep-{i}"} for i in range(keep)],
        "fix": [{"content": f"fix-{i}"} for i in range(fix)],
        "try": [{"content": f"try-{i}"} for i in range(try_count)],
    }
    (retro_dir / filename).write_text(json.dumps(data))


# ===========================================================================
# prepare_sprint_retro_data.py
# ===========================================================================


class TestPrepareSprintRetroData(_HookTestCase):
    """M12: prep script collects retros, velocity, and sizing."""

    def test_basic_output_structure(self):
        """All required keys present."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        for key in (
            "sprint_id",
            "goal",
            "started",
            "velocity",
            "stories",
            "session_retros",
            "sprint_md",
        ):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_velocity_in_output(self):
        """Velocity matches sprint data."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 3)
        self.assertEqual(vel["stories_delivered"], 2)
        self.assertEqual(vel["stories_carried"], 1)

    def test_stories_in_output(self):
        """Stories list populated with sizes."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(len(result["stories"]), 3)
        sizes = {s["id"]: s["size"] for s in result["stories"]}
        self.assertEqual(sizes["story-001"], "M")
        self.assertEqual(sizes["story-003"], "L")

    def test_no_sprint_returns_none(self):
        import prepare_sprint_retro_data

        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertIsNone(result)

    def test_session_retros_collected(self):
        """Retros within sprint window collected."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        # Sprint started 2026-03-15 — these retros are after
        _make_retro_file(self.smm_dir, "2026-03-16T10:00:00+00:00", keep=2)
        _make_retro_file(self.smm_dir, "2026-03-17T10:00:00+00:00", fix=1)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(len(result["session_retros"]), 2)

    def test_retros_before_sprint_excluded(self):
        """Retros before start date filtered out."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        # Sprint started 2026-03-15 — this retro is before
        _make_retro_file(self.smm_dir, "2026-03-14T10:00:00+00:00", keep=1)
        # This one is after
        _make_retro_file(self.smm_dir, "2026-03-16T10:00:00+00:00", keep=1)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(len(result["session_retros"]), 1)
        self.assertTrue(
            result["session_retros"][0]["timestamp"].startswith("2026-03-16")
        )

    def test_empty_retro_dir(self):
        """Empty retrospectives dir -> empty session_retros list."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        (self.smm_dir / "retrospectives").mkdir()
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(result["session_retros"], [])

    def test_no_retro_dir(self):
        """Missing retrospectives dir -> empty session_retros list."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(result["session_retros"], [])

    def test_atomic_write(self):
        """.sprint-retro-input.json exists after run."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        prepare_sprint_retro_data.run(self.smm_dir)
        self.assertTrue((self.smm_dir / ".sprint-retro-input.json").exists())

    def test_malformed_sprint_returns_none(self):
        """Sprint without sprint_id -> None."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_NO_ID)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertIsNone(result)

    def test_sprint_md_in_output(self):
        """Raw sprint markdown included."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(result["sprint_md"], SPRINT_CONTENT)

    def test_retros_sorted_by_timestamp(self):
        """Session retros returned in chronological order."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        _make_retro_file(self.smm_dir, "2026-03-18T10:00:00+00:00")
        _make_retro_file(self.smm_dir, "2026-03-16T10:00:00+00:00")
        _make_retro_file(self.smm_dir, "2026-03-17T10:00:00+00:00")
        result = prepare_sprint_retro_data.run(self.smm_dir)
        timestamps = [r["timestamp"] for r in result["session_retros"]]
        self.assertEqual(timestamps, sorted(timestamps))


# ===========================================================================
# preload.sh — Integration tests
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-retro"
    / "scripts"
    / "preload.sh"
)


class TestSprintRetroPreload(_IntegrationTestCase):
    """M12: preload.sh runs prepare_sprint_retro_data and outputs paths."""

    def _run_preload(self) -> subprocess.CompletedProcess:
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
        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_retro_input(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RETRO_INPUT=", result.stdout)

    def test_preload_no_sprint_graceful(self):
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RETRO_INPUT=", result.stdout)

    def test_preload_includes_behavioral_guide(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_CONTENT)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Behavioral Guide", result.stdout)


if __name__ == "__main__":
    unittest.main()

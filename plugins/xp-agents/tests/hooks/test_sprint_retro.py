#!/usr/bin/env python3
"""Tests for prepare_sprint_retro_data.py and preload."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _HookTestCase,
    _IntegrationTestCase,
    _s,
    _sprint_json,
    write_smm_fixture,
)

# ---------------------------------------------------------------------------
# Sprint fixture
# ---------------------------------------------------------------------------

SPRINT_CONTENT = _sprint_json(
    [
        _s("story-001", "User login", "M", "done"),
        _s("story-002", "User registration", "S", "done"),
        _s(
            "story-003",
            "Password reset",
            "L",
            "deferred",
            dependencies=["story-001"],
        ),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)

SPRINT_NO_ID = _sprint_json(
    [_s("story-001", "Something", "M", "done")],
    goal="Test",
)


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
        """All required keys present, with path instead of content."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        for key in (
            "sprint_id",
            "goal",
            "started",
            "velocity",
            "stories",
            "session_retros",
            "sprint_md_path",
        ):
            self.assertIn(key, result, f"Missing key: {key}")
        # Should NOT have embedded content
        self.assertNotIn("sprint_md", result)

    def test_velocity_in_output(self):
        """Velocity matches sprint data."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 3)
        self.assertEqual(vel["stories_delivered"], 2)
        self.assertEqual(vel["stories_carried"], 1)

    def test_stories_in_output(self):
        """Stories list populated with sizes."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
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

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        # Sprint started 2026-03-15 — these retros are after
        _make_retro_file(self.smm_dir, "2026-03-16T10:00:00+00:00", keep=2)
        _make_retro_file(self.smm_dir, "2026-03-17T10:00:00+00:00", fix=1)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(len(result["session_retros"]), 2)

    def test_retros_before_sprint_excluded(self):
        """Retros before start date filtered out."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
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

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        (self.smm_dir / "retrospectives").mkdir()
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(result["session_retros"], [])

    def test_no_retro_dir(self):
        """Missing retrospectives dir -> empty session_retros list."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertEqual(result["session_retros"], [])

    def test_atomic_write(self):
        """.sprint-retro-input.json exists after run."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        prepare_sprint_retro_data.run(self.smm_dir)
        self.assertTrue((self.smm_dir / ".sprint-retro-input.json").exists())

    def test_malformed_sprint_returns_none(self):
        """Sprint without sprint_id -> None."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_NO_ID)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        self.assertIsNone(result)

    def test_sprint_md_path_in_output(self):
        """sprint_md_path points to existing file."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        result = prepare_sprint_retro_data.run(self.smm_dir)
        path = result["sprint_md_path"]
        self.assertTrue(path)
        self.assertTrue(Path(path).is_file())

    def test_retros_sorted_by_timestamp(self):
        """Session retros returned in chronological order."""
        import prepare_sprint_retro_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
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
    / "xp-run-sprint-retro"
    / "scripts"
    / "preload.sh"
)


class TestSprintRetroPreload(_IntegrationTestCase):
    """M12: preload.sh runs prepare_sprint_retro_data and outputs paths."""

    def test_preload_outputs_smm_dir(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_retro_input(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RETRO_INPUT=", result.stdout)

    def test_preload_no_sprint_graceful(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RETRO_INPUT=", result.stdout)

    def test_preload_outputs_smm_path_no_content(self):
        """SMM_FILE= path, no values or pillar content in stdout."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        write_smm_fixture(
            self.smm_dir,
            constraints=[("TDD always", "convention")],
            wisdom=["Commit after green"],
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        # SMM_FILE path present
        self.assertIn("SMM_FILE=", result.stdout)
        # No XP values (injected via SubagentStart now)
        self.assertNotIn("XP Values", result.stdout)
        # No SMM content
        self.assertNotIn("TDD always", result.stdout)
        self.assertNotIn("Commit after green", result.stdout)

    def test_preload_is_idempotent_when_input_exists(self):
        """M2: if .sprint-retro-input.json already exists (written by
        SessionStart hook), the skill preload should not overwrite it.

        This preserves the schema written by the session-start path and
        avoids recomputing prep data twice.
        """
        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)
        sentinel_file = self.smm_dir / ".sprint-retro-input.json"
        sentinel_content = '{"sentinel": "pre-written-by-session-start"}'
        sentinel_file.write_text(sentinel_content)

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RETRO_INPUT=", result.stdout)
        # File must be untouched — preload is a no-op when it exists.
        self.assertEqual(sentinel_file.read_text(), sentinel_content)

    def test_preload_and_direct_call_produce_equivalent_schema(self):
        """M2: SessionStart-hook path (direct function call) and skill-preload
        path (shell invocation) must produce .sprint-retro-input.json files
        with identical top-level keys.

        Prevents schema drift between the two code paths.
        """
        (self.smm_dir / "sprint.json").write_text(SPRINT_CONTENT)

        # Path A: direct function call (SessionStart hook style)
        import prepare_sprint_retro_data

        prepare_sprint_retro_data.run(self.smm_dir)
        direct_file = self.smm_dir / ".sprint-retro-input.json"
        direct_keys = set(json.loads(direct_file.read_text()).keys())
        direct_file.unlink()

        # Path B: preload shell script (manual invocation style)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        preload_file = self.smm_dir / ".sprint-retro-input.json"
        self.assertTrue(preload_file.exists())
        preload_keys = set(json.loads(preload_file.read_text()).keys())

        self.assertEqual(
            direct_keys,
            preload_keys,
            "direct call and preload must produce equivalent JSON schemas",
        )


if __name__ == "__main__":
    unittest.main()

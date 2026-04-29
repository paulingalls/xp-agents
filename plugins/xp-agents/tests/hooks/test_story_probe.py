#!/usr/bin/env python3
"""Tests for story_probe: pre-commit story-prefix nudge."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree
from conftest import _HookTestCase


class TestStoryProbeConstants(unittest.TestCase):
    """Probe-status contract constants must exist with stable string values."""

    def test_constants_exist(self):
        from event_schema import (
            METADATA_KEY_STORY_CANDIDATE,
            STATUS_CONTENT_STORY_PROBE,
        )

        self.assertEqual(STATUS_CONTENT_STORY_PROBE, "story_probe_shown")
        self.assertEqual(METADATA_KEY_STORY_CANDIDATE, "story_candidate")


def _sprint(stories):
    """Build a minimal sprint dict for find_story_candidate tests."""
    return {"sprint_id": "sprint-099", "stories": stories}


def _story(sid, status="in-progress", file_domain=None):
    return {
        "id": sid,
        "title": f"Story {sid}",
        "status": status,
        "file_domain": file_domain or [],
    }


class TestFindStoryCandidate(unittest.TestCase):
    """find_story_candidate: pre-commit nudge for story-prefix attribution."""

    def setUp(self):
        # Prevent worktree assignment from leaking: cwd is project root,
        # not a worktree. extract_worktree_name returns None for these tests.
        self.cwd = "/tmp/not-a-worktree"

    def _call(self, sprint, files, message, smm_dir=Path("/tmp/no-smm")):
        import story_probe

        return story_probe.find_story_candidate(
            smm_dir, self.cwd, files, message, sprint=sprint
        )

    def test_no_sprint_returns_none(self):
        self.assertIsNone(self._call(None, ["scripts/foo.py"], ""))

    def test_zero_in_progress_returns_none(self):
        sprint = _sprint([_story("story-001", status="ready")])
        self.assertIsNone(self._call(sprint, ["scripts/foo.py"], ""))

    def test_one_in_progress_returns_none(self):
        # Tier 2a in _resolve_story_id handles single-in-progress at commit
        # time; the probe stays silent because attribution is unambiguous.
        sprint = _sprint([_story("story-001", file_domain=["scripts/foo.py"])])
        self.assertIsNone(self._call(sprint, ["scripts/foo.py"], ""))

    def test_bracket_prefix_silences_probe(self):
        sprint = _sprint(
            [
                _story("story-001", file_domain=["scripts/foo.py"]),
                _story("story-002", file_domain=["scripts/bar.py"]),
            ]
        )
        for prefix in (
            "[chore]",
            "[release]",
            "[free]",
            "[doc]",
            "[fix]",
            "[story-001]",
            "[anything]",
        ):
            with self.subTest(prefix=prefix):
                self.assertIsNone(
                    self._call(sprint, ["scripts/foo.py"], f"{prefix} subject"),
                    f"prefix {prefix} should silence",
                )

    def test_no_prefix_dominant_overlap_returns_candidate(self):
        sprint = _sprint(
            [
                _story("story-001", file_domain=["scripts/foo.py", "scripts/bar.py"]),
                _story("story-002", file_domain=["scripts/baz.py"]),
            ]
        )
        result = self._call(
            sprint,
            ["scripts/foo.py", "scripts/bar.py", "scripts/quux.py"],
            "subject without prefix",
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["story_id"], "story-001")
        self.assertEqual(result["overlap_count"], 2)
        self.assertEqual(result["total_files"], 3)

    def test_no_prefix_tied_overlap_returns_none(self):
        sprint = _sprint(
            [
                _story("story-001", file_domain=["scripts/foo.py"]),
                _story("story-002", file_domain=["scripts/bar.py"]),
            ]
        )
        self.assertIsNone(self._call(sprint, ["scripts/foo.py", "scripts/bar.py"], ""))

    def test_no_prefix_zero_overlap_returns_none(self):
        sprint = _sprint(
            [
                _story("story-001", file_domain=["scripts/foo.py"]),
                _story("story-002", file_domain=["scripts/bar.py"]),
            ]
        )
        self.assertIsNone(self._call(sprint, ["docs/README.md"], ""))

    def test_worktree_teammate_returns_none(self):
        """When cwd is a teammate worktree with story_assignment, Tier 1
        already attributes the commit — probe stays silent."""
        sprint = _sprint(
            [
                _story("story-001", file_domain=["scripts/foo.py"]),
                _story("story-002", file_domain=["scripts/bar.py"]),
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            wt_cwd = "/tmp/.claude/worktrees/teammate-step-1"
            assignment = worktree.story_assignment_path(smm_dir, "teammate-step-1")
            assignment.parent.mkdir(parents=True, exist_ok=True)
            assignment.write_text("story-001")
            import story_probe

            result = story_probe.find_story_candidate(
                smm_dir, wt_cwd, ["scripts/foo.py"], "", sprint=sprint
            )
            self.assertIsNone(result)


class TestBuildNudgeLine(unittest.TestCase):
    def test_format(self):
        import story_probe

        line = story_probe.build_nudge_line(
            {"story_id": "story-005", "overlap_count": 3, "total_files": 4}
        )
        self.assertEqual(
            line,
            "Story attribution: staged files match story-005's domain "
            "(3/4 files). Add prefix [story-005] (or any other "
            "[bracketed] prefix to skip).",
        )


class TestEmitProbeStatus(_HookTestCase):
    def test_writes_status_event_with_metadata(self):
        import story_probe
        from event_schema import (
            METADATA_KEY_STORY_CANDIDATE,
            STATUS_CONTENT_STORY_PROBE,
        )

        story_probe.emit_probe_status(
            self.smm_dir,
            {"story_id": "story-007", "overlap_count": 2, "total_files": 3},
            "main",
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["type"], "status")
        self.assertTrue(e["content"].startswith(STATUS_CONTENT_STORY_PROBE))
        self.assertIn("story-007", e["content"])
        self.assertEqual(e["metadata"][METADATA_KEY_STORY_CANDIDATE], "story-007")

    def test_none_candidate_is_noop(self):
        import story_probe

        story_probe.emit_probe_status(self.smm_dir, None, "main")
        self.assertEqual(self._read_events(), [])


if __name__ == "__main__":
    unittest.main()

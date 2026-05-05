#!/usr/bin/env python3
"""Tests for auto-resolve of test-failure and lint concerns."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import concerns
import lint_check
import worktree
from conftest import _HookTestCase, _make_bash_input, _make_write_input, make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_LINT_RESOLVED,
)


class TestAutoResolveTestConcerns(_HookTestCase):
    """Tests for auto-resolve of test-failure concerns."""

    def _run_bash(self, command, stdout="", **kw):
        import bash_post_tool

        data = _make_bash_input(command=command, stdout=stdout, **kw)
        bash_post_tool.run(data, smm_dir=self.smm_dir)

    def test_passing_resolves_prior_failure_concern(self):
        """Seed failure concern, pass tests, verify resolution."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        self._write_events([concern])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)
        self.assertIn(
            concern["id"],
            resolutions[0]["metadata"]["resolves"],
        )

    def test_passing_resolves_multiple_concerns(self):
        """Two different failure concerns should both be resolved."""
        c1 = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        c2 = make_event(
            EVENT_TYPE_CONCERN,
            content="Test run failed: 1 error",
            severity="high",
        )
        self._write_events([c1, c2])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        all_resolved_ids = []
        for e in events:
            all_resolved_ids.extend(e.get("metadata", {}).get("resolves", []))
        self.assertIn(c1["id"], all_resolved_ids)
        self.assertIn(c2["id"], all_resolved_ids)

    def test_no_resolve_when_no_prior_concerns(self):
        """Clean state, no resolution events."""
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_skip_already_resolved_concerns(self):
        """No duplicate resolutions."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 1 failed (pytest)",
            severity="high",
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Test concern resolved",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nOK",
        )
        events = self._read_events()
        new_resolutions = [
            e
            for e in events[2:]  # skip seeded events
            if e.get("metadata", {}).get("resolves")
        ]
        self.assertEqual(len(new_resolutions), 0)

    def test_failing_tests_no_auto_resolve(self):
        """Still-failing tests should not resolve anything."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        self._write_events([concern])
        self._run_bash(
            "python3 -m unittest test.py",
            stdout="Ran 5 tests in 0.1s\n\nFAILED (failures=1)",
        )
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_stop_gate_ignores_resolution_events(self):
        """Resolution events should not confuse the TDD stop gate."""
        import tdd_stop_gate

        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 1 failed (pytest)",
            severity="high",
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Test concern resolved: 1 concern auto-resolved",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        pass_status = make_event(
            EVENT_TYPE_STATUS,
            content="Tests: 5 passed, 0 failed (pytest)",
            working_on=[],
        )
        self._write_events([concern, resolver, pass_status])
        result = tdd_stop_gate.run({"session_id": "t"}, smm_dir=self.smm_dir)
        self.assertIsNone(result)


class _LintTmpDirMixin:
    """Shared setUp/tearDown for tests needing a tmpdir with ruff.toml."""

    def setUp(self):
        super().setUp()  # type: ignore[misc]
        self._lint_tmpdir = Path(tempfile.mkdtemp())
        (self._lint_tmpdir / "ruff.toml").touch()

    def tearDown(self):
        shutil.rmtree(self._lint_tmpdir, ignore_errors=True)
        super().tearDown()  # type: ignore[misc]


class TestAutoResolveLintConcerns(_LintTmpDirMixin, _HookTestCase):
    """Tests for auto-resolve of lint concerns when lint passes."""

    def _normalized(self, rel_path: str) -> str:
        """Return the normalized absolute path lint_check will use."""
        return worktree.normalize_path(rel_path, str(self._lint_tmpdir))

    def _run_lint_clean(self, file_path="src/app.py"):
        """Run lint_check with a clean lint result for file_path."""
        with (
            patch(
                "lint_check.shutil.which",
                return_value="/usr/bin/ruff",
            ),
            patch("lint_check.run_linter", return_value=None),
        ):
            lint_check.run(
                _make_write_input(
                    tool_input={
                        "file_path": file_path,
                        "content": "x",
                    },
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )

    def test_lint_pass_resolves_concern_for_same_file(self):
        """Seed lint concern for src/app.py, pass lint -> resolved."""
        norm = self._normalized("src/app.py")
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
        )
        self._write_events([concern])
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)
        self.assertIn(
            concern["id"],
            resolutions[0]["metadata"]["resolves"],
        )

    def test_lint_pass_resolution_carries_action_tag(self):
        """Lint resolution events from PostToolUse:Write/Edit must carry
        metadata.action='lint_resolved' so retro_metrics counts them as
        lint_events (not 'other'). Mirrors the lint_resolution.py path
        already does for PostToolUse:Bash on commit; the Write/Edit path
        was missed when the action vocabulary was introduced."""
        norm = self._normalized("src/app.py")
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
        )
        self._write_events([concern])
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)
        self.assertEqual(
            resolutions[0]["metadata"].get("action"),
            STATUS_ACTION_LINT_RESOLVED,
            "Write/Edit-time lint resolution must tag action=lint_resolved "
            "to symmetrically tick retro_metrics' lint_events counter "
            "(commit-time path already does this via lint_resolution.py).",
        )

    def test_lint_pass_no_resolve_for_different_file(self):
        """Lint concern for src/other.py not resolved by src/app.py."""
        norm_other = self._normalized("src/other.py")
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm_other}:\nE302",
            severity="medium",
        )
        self._write_events([concern])
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_no_lint_concerns_no_resolution(self):
        """No lint concerns in events -> no resolution events."""
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_already_resolved_not_re_resolved(self):
        """Already-resolved lint concern not re-resolved."""
        norm = self._normalized("src/app.py")
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302",
            severity="medium",
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Lint concern resolved",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        self._run_lint_clean("src/app.py")
        events = self._read_events()
        new_resolutions = [
            e
            for e in events[2:]  # skip seeded events
            if e.get("metadata", {}).get("resolves")
        ]
        self.assertEqual(len(new_resolutions), 0)


class TestResolutionsThreading(_LintTmpDirMixin, _HookTestCase):
    """Verify resolve_lint_on_commit threads resolutions without re-computation."""

    def test_precomputed_resolutions_skip_recomputation(self):
        """When resolutions kwarg is provided, compute_resolutions is not called."""
        import lint_resolution
        import resolution

        norm = worktree.normalize_path("src/app.py", str(self._lint_tmpdir))
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
        )
        self._write_events([concern])

        events = self._read_events()
        precomputed = resolution.compute_resolutions(events)

        with (
            patch(
                "lint_check.detect_linter_config",
                return_value=("ruff", None),
            ),
            patch("lint_check.run_linter", return_value=None),
            patch(
                "resolution.compute_resolutions",
                wraps=resolution.compute_resolutions,
            ) as mock_compute,
        ):
            lint_resolution.resolve_lint_on_commit(
                self.smm_dir,
                str(self._lint_tmpdir),
                "main",
                ["src/app.py"],
                events=events,
                resolutions=precomputed,
            )
            mock_compute.assert_not_called()


class TestLintConcernMatches(unittest.TestCase):
    """Test lint concern matching across absolute/relative path formats."""

    def test_matches_relative_path(self):
        content = "Lint errors in src/app.py:\nE302"
        self.assertTrue(concerns.lint_concern_matches(content, "src/app.py"))

    def test_matches_absolute_path_with_relative(self):
        content = "Lint errors in /Users/paul/project/src/app.py:\nE302"
        self.assertTrue(concerns.lint_concern_matches(content, "src/app.py"))

    def test_no_match_different_file(self):
        content = "Lint errors in src/other.py:\nE302"
        self.assertFalse(concerns.lint_concern_matches(content, "src/app.py"))

    def test_no_false_positive_suffix(self):
        """old_app.py should not match app.py."""
        content = "Lint errors in src/old_app.py:\nE302"
        self.assertFalse(concerns.lint_concern_matches(content, "src/app.py"))

    def test_non_lint_concern(self):
        content = "Some other concern about src/app.py"
        self.assertFalse(concerns.lint_concern_matches(content, "src/app.py"))


class TestSweepOrphanLintConcerns(_LintTmpDirMixin, _HookTestCase):
    """Sweep unresolved lint concerns whose file isn't in this commit.

    Catches side-effect fixes (`ruff check --fix` from Bash, pre-commit
    reformatting, cross-file fixes) that don't show up as direct edits
    to the offending file. Closes debt 3863cb520147 mechanically.
    """

    def _seed_concern(self, rel_path: str) -> dict:
        # Create the file before normalizing so path realpath is stable
        # (macOS /var/folders → /private/var/folders symlink would otherwise
        # give different normalization before vs. after file creation).
        target = Path(self._lint_tmpdir) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        norm = worktree.normalize_path(rel_path, str(self._lint_tmpdir))
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
            files=[norm],
        )
        self._write_events([concern])
        return concern

    def _run_sweep(self, committed_files, lint_clean=True):
        import lint_resolution

        events = self._read_events()
        with (
            patch(
                "lint_check.detect_linter_config",
                return_value=("ruff", str(self._lint_tmpdir / "ruff.toml")),
            ),
            patch(
                "lint_check.run_linter",
                return_value=None if lint_clean else "E302",
            ),
        ):
            lint_resolution.sweep_orphan_lint_concerns(
                self.smm_dir,
                str(self._lint_tmpdir),
                "main",
                committed_files,
                events=events,
                resolutions=None,
            )

    def test_resolves_concern_for_clean_file_outside_commit(self):
        """Concern on src/other.py (not in commit), file now lints clean -> resolved."""
        concern = self._seed_concern("src/other.py")
        self._run_sweep(committed_files=["src/app.py"], lint_clean=True)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)
        self.assertIn(concern["id"], resolutions[0]["metadata"]["resolves"])
        self.assertEqual(resolutions[0]["metadata"].get("action"), "lint_resolved")

    def test_skips_files_already_in_commit(self):
        """Concern on src/app.py which IS in committed_files -> sweep skips
        (already handled by _resolve_lint_on_commit, no double-resolve)."""
        self._seed_concern("src/app.py")
        self._run_sweep(committed_files=["src/app.py"], lint_clean=True)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_leaves_dirty_file_concern_open(self):
        """Concern on src/other.py, file still dirty -> NOT resolved."""
        self._seed_concern("src/other.py")
        self._run_sweep(committed_files=[], lint_clean=False)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_skips_deleted_file(self):
        """Concern on a file that no longer exists -> skip, don't crash."""
        norm = worktree.normalize_path("src/gone.py", str(self._lint_tmpdir))
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302",
            severity="medium",
            files=[norm],
        )
        self._write_events([concern])
        # File was never created — Path.exists() is False
        self._run_sweep(committed_files=[], lint_clean=True)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_no_op_with_no_unresolved_concerns(self):
        """No unresolved lint concerns -> no work, no events written."""
        self._run_sweep(committed_files=["src/app.py"], lint_clean=True)
        events = self._read_events()
        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()

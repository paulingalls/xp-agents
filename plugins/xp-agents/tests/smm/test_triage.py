#!/usr/bin/env python3
"""Tests for smm/triage.py — shared triage helpers.

Covers: find_unresolved, find_overlapping_commits, extract_file_domain_paths.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import triage
from conftest import make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN, EVENT_TYPE_DEBT


class TestFindUnresolved(unittest.TestCase):
    """find_unresolved returns unresolved events of a given type, newest first."""

    def test_returns_unresolved_concerns_newest_first(self):
        c1 = make_event(EVENT_TYPE_CONCERN, content="First")
        c1["ts"] = "2026-01-01T00:00:00Z"
        c2 = make_event(EVENT_TYPE_CONCERN, content="Second")
        c2["ts"] = "2026-01-02T00:00:00Z"
        result = triage.find_unresolved([c1, c2], "concern", set())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["content"], "Second")

    def test_excludes_resolved(self):
        c1 = make_event(EVENT_TYPE_CONCERN, content="Resolved one")
        c2 = make_event(EVENT_TYPE_CONCERN, content="Still open")
        result = triage.find_unresolved([c1, c2], "concern", {c1["id"]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Still open")

    def test_filters_by_type(self):
        c = make_event(EVENT_TYPE_CONCERN, content="A concern")
        d = make_event(EVENT_TYPE_DEBT, content="Some debt")
        result = triage.find_unresolved([c, d], "concern", set())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], EVENT_TYPE_CONCERN)

    def test_empty_events(self):
        result = triage.find_unresolved([], "concern", set())
        self.assertEqual(result, [])


class TestFindOverlappingCommits(unittest.TestCase):
    """find_overlapping_commits finds commits whose files overlap a concern."""

    def test_finds_overlapping_commit(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        commit = make_event(EVENT_TYPE_COMMIT, content="fix app", files=["src/app.ts"])
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 1)

    def test_ignores_commits_before_concern(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        concern["ts"] = "2099-01-01T00:00:00Z"
        commit = make_event(EVENT_TYPE_COMMIT, content="old fix", files=["src/app.ts"])
        commit["ts"] = "2000-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_no_overlap_different_files(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        commit = make_event(
            EVENT_TYPE_COMMIT, content="fix other", files=["src/other.ts"]
        )
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_same_timestamp_excluded(self):
        """Commit at exact same timestamp as concern is excluded."""
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        concern["ts"] = "2026-06-01T00:00:00Z"
        commit = make_event(EVENT_TYPE_COMMIT, content="fix", files=["src/app.ts"])
        commit["ts"] = "2026-06-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_concern_without_files_returns_empty(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="No files")
        commit = make_event(EVENT_TYPE_COMMIT, content="fix", files=["src/app.ts"])
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)


class TestExtractFileDomainPaths(unittest.TestCase):
    """extract_file_domain_paths splits "path — desc" entries and expands globs.

    Glob expansion uses fnmatch-style matching against an optional
    `candidate_files` iterable (the cascade-analysis case where commit files
    may no longer exist on disk). When no candidates are passed, falls back
    to pathlib.Path(".").glob for current on-disk files.
    """

    def test_literal_path_with_em_dash(self):
        result = triage.extract_file_domain_paths(["scripts/auth.py — add login"])
        self.assertEqual(result, {"scripts/auth.py"})

    def test_literal_path_no_dash(self):
        result = triage.extract_file_domain_paths(["scripts/foo.py"])
        self.assertEqual(result, {"scripts/foo.py"})

    def test_empty_list(self):
        self.assertEqual(triage.extract_file_domain_paths([]), set())

    def test_blank_entry_skipped(self):
        self.assertEqual(triage.extract_file_domain_paths(["   "]), set())

    def test_literal_unaffected_by_candidate_files_kwarg(self):
        """AC2: literal entries pass through unchanged when candidates are given."""
        result = triage.extract_file_domain_paths(
            ["scripts/foo.py — modify foo"],
            candidate_files=["scripts/foo.py", "scripts/bar.py"],
        )
        self.assertEqual(result, {"scripts/foo.py"})

    def test_glob_expanded_against_candidates(self):
        """AC1: 'tests/hooks/**/*.py' expands to matching candidate paths."""
        candidates = [
            "tests/hooks/test_a.py",
            "tests/hooks/test_b.py",
            "tests/hooks/sub/test_c.py",
            "scripts/foo.py",
        ]
        result = triage.extract_file_domain_paths(
            ["tests/hooks/**/*.py — migrated tests"],
            candidate_files=candidates,
        )
        self.assertEqual(
            result,
            {
                "tests/hooks/test_a.py",
                "tests/hooks/test_b.py",
                "tests/hooks/sub/test_c.py",
            },
        )

    def test_glob_drops_non_matching_candidates(self):
        candidates = ["scripts/foo.py", "tests/hooks/test_a.py"]
        result = triage.extract_file_domain_paths(
            ["tests/hooks/*.py"],
            candidate_files=candidates,
        )
        self.assertEqual(result, {"tests/hooks/test_a.py"})

    def test_glob_single_star_does_not_cross_slash(self):
        """A bare '*' segment is one path segment — doesn't match nested dirs."""
        candidates = ["tests/foo.py", "tests/sub/bar.py"]
        result = triage.extract_file_domain_paths(
            ["tests/*.py"], candidate_files=candidates
        )
        self.assertEqual(result, {"tests/foo.py"})

    def test_question_mark_glob(self):
        candidates = ["tests/test_a.py", "tests/test_ab.py", "tests/test_b.py"]
        result = triage.extract_file_domain_paths(
            ["tests/test_?.py"], candidate_files=candidates
        )
        self.assertEqual(result, {"tests/test_a.py", "tests/test_b.py"})

    def test_bracket_class_glob(self):
        candidates = ["test_a.py", "test_b.py", "test_c.py", "test_d.py"]
        result = triage.extract_file_domain_paths(
            ["test_[ab].py"], candidate_files=candidates
        )
        self.assertEqual(result, {"test_a.py", "test_b.py"})

    def test_glob_with_no_candidates_falls_back_to_disk(self):
        """When candidate_files is omitted, expand via Path.glob from cwd."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "tests" / "hooks").mkdir(parents=True)
            (tdp / "tests" / "hooks" / "test_a.py").touch()
            (tdp / "tests" / "hooks" / "test_b.py").touch()
            (tdp / "scripts").mkdir()
            (tdp / "scripts" / "foo.py").touch()

            cwd = os.getcwd()
            os.chdir(td)
            try:
                result = triage.extract_file_domain_paths(["tests/hooks/*.py"])
            finally:
                os.chdir(cwd)
            self.assertEqual(result, {"tests/hooks/test_a.py", "tests/hooks/test_b.py"})

    def test_glob_recursive_no_candidates_falls_back_to_disk(self):
        """** falls back to Path.glob recursive matching."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "tests" / "hooks" / "sub").mkdir(parents=True)
            (tdp / "tests" / "hooks" / "test_a.py").touch()
            (tdp / "tests" / "hooks" / "sub" / "test_b.py").touch()

            cwd = os.getcwd()
            os.chdir(td)
            try:
                result = triage.extract_file_domain_paths(["tests/hooks/**/*.py"])
            finally:
                os.chdir(cwd)
            self.assertIn("tests/hooks/test_a.py", result)
            self.assertIn("tests/hooks/sub/test_b.py", result)

    def test_glob_no_matching_candidates_yields_nothing(self):
        """When a glob matches no candidates, the entry contributes no paths."""
        result = triage.extract_file_domain_paths(
            ["tests/hooks/**/*.py"],
            candidate_files=["scripts/foo.py"],
        )
        self.assertEqual(result, set())

    def test_mixed_literal_and_glob_entries(self):
        candidates = ["tests/hooks/test_a.py", "scripts/foo.py"]
        result = triage.extract_file_domain_paths(
            [
                "tests/hooks/**/*.py — migrated tests",
                "scripts/explicit.py — direct",
            ],
            candidate_files=candidates,
        )
        self.assertEqual(result, {"tests/hooks/test_a.py", "scripts/explicit.py"})

    # --- cwd kwarg (story-005 / concern edf2fc993f52) ---------------------
    #
    # Prior shape used `Path(".").glob(path)` implicitly — every caller had
    # to chdir before invoking, an easy foot-gun. The `cwd=` kwarg lets a
    # caller name the root explicitly. Default `cwd=None` keeps the legacy
    # implicit-cwd behavior so existing call-sites stay green.

    def test_glob_with_cwd_kwarg_uses_provided_dir(self):
        """AC2/AC3: cwd= names the glob root — does NOT consult os.getcwd()."""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "tests" / "hooks").mkdir(parents=True)
            (tdp / "tests" / "hooks" / "test_a.py").touch()
            (tdp / "tests" / "hooks" / "test_b.py").touch()

            # Stay in a DIFFERENT cwd to prove the kwarg, not the process
            # cwd, drives expansion. If the implementation regresses to
            # `Path(".").glob` the result will be empty under any tmpdir
            # that doesn't itself contain `tests/hooks/*.py`.
            with tempfile.TemporaryDirectory() as other_cwd:
                origin = os.getcwd()
                os.chdir(other_cwd)
                try:
                    result = triage.extract_file_domain_paths(
                        ["tests/hooks/*.py"], cwd=td
                    )
                finally:
                    os.chdir(origin)

            self.assertEqual(
                result,
                {"tests/hooks/test_a.py", "tests/hooks/test_b.py"},
                "cwd= should drive glob expansion, not the process cwd",
            )

    def test_cwd_kwarg_default_none_preserves_legacy_behavior(self):
        """AC3: omitting cwd preserves the legacy implicit-cwd behavior.

        Backward-compat pin: every existing caller (sprint_status,
        sprint_cli, _flagged_missing_paths) calls without cwd. They must
        keep working.
        """
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "tests" / "hooks").mkdir(parents=True)
            (tdp / "tests" / "hooks" / "test_a.py").touch()

            cwd = os.getcwd()
            os.chdir(td)
            try:
                result = triage.extract_file_domain_paths(["tests/hooks/*.py"])
            finally:
                os.chdir(cwd)
            self.assertEqual(result, {"tests/hooks/test_a.py"})

    def test_cwd_ignored_when_candidate_files_provided(self):
        """AC2: candidate_files takes precedence — cwd= is irrelevant.

        Cascade-analysis call-sites (story_metrics._attribute_commits) pass
        candidate_files with historical commit paths that may not exist on
        disk. cwd= must NOT silently switch them to disk-glob.
        """
        candidates = ["tests/hooks/test_a.py"]
        with tempfile.TemporaryDirectory() as td:
            # The tmpdir has no matching files — if cwd= leaked through,
            # the result would be empty. The candidate_files path must win.
            result = triage.extract_file_domain_paths(
                ["tests/hooks/*.py"],
                candidate_files=candidates,
                cwd=td,
            )
        self.assertEqual(result, {"tests/hooks/test_a.py"})


if __name__ == "__main__":
    unittest.main()

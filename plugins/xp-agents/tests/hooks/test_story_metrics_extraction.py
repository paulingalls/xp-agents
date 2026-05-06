#!/usr/bin/env python3
"""Tests for story_metrics.py — extract_file_domain_paths."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import conftest  # noqa: F401 — git env cleanup


class TestExtractFileDomainPaths(unittest.TestCase):
    def test_extracts_path_before_dash(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths(
            ["scripts/auth.py \u2014 add login", "tests/test_auth.py \u2014 auth tests"]
        )
        self.assertEqual(paths, {"scripts/auth.py", "tests/test_auth.py"})

    def test_plain_path_without_description(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths(["scripts/auth.py"])
        self.assertEqual(paths, {"scripts/auth.py"})

    def test_empty_list(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths([])
        self.assertEqual(paths, set())

    def test_mixed_formats(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths(
            ["scripts/auth.py \u2014 add login", "scripts/plain.py"]
        )
        self.assertEqual(paths, {"scripts/auth.py", "scripts/plain.py"})


class TestExtractFileDomainPathsGlob(unittest.TestCase):
    """Glob entries in file_domain expand against candidate files."""

    def test_glob_entry_expands_against_candidates(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths(
            ["tests/hooks/**/*.py — migrated tests"],
            candidate_files=[
                "tests/hooks/test_a.py",
                "tests/hooks/test_b.py",
                "scripts/foo.py",
            ],
        )
        self.assertEqual(paths, {"tests/hooks/test_a.py", "tests/hooks/test_b.py"})


class TestAttributeCommitsGlobFileDomain(unittest.TestCase):
    """AC3 + AC4: cascade analysis treats glob file_domain entries as in-domain.

    Replays the sprint-065 drift shape: file_domain uses 'tests/hooks/**/*.py'
    glob prose, commits modify literal test paths under that glob — cascade
    must NOT increment for the in-domain files.
    """

    def test_glob_file_domain_matches_committed_test_files(self):
        import story_metrics
        from conftest import _s, commit_event

        stories = [
            _s(
                "story-001",
                "Migrate tests",
                "done",
                file_domain=["tests/hooks/**/*.py — migrated tests"],
            ),
        ]
        commits = [
            commit_event(
                ["tests/hooks/test_session_start.py"],
                story_id="story-001",
            ),
        ]
        result = story_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 1)
        self.assertEqual(
            result["story-001"]["cascade_size"],
            0,
            "test_session_start.py is in-domain via tests/hooks/**/*.py glob",
        )

    def test_glob_shapes_no_cascade_against_matching_commits(self):
        """AC4 e2e: every glob-prose drift shape no longer fires.

        Covers the four shapes that logged drift in the sprint-065 retrospective:
        recursive `**` mid-path, recursive `**` at root, and a flat `*.ext`
        entry. Each row pairs a glob entry with a literal commit path that
        should match — cascade_size must be 0 for every row.
        """
        import story_metrics
        from conftest import _s, commit_event

        cases = [
            ("a/b/**/*.py", "a/b/c.py"),
            ("a/b/**/*.py", "a/b/sub/c.py"),
            ("pkg/**/*.py", "pkg/mod/sub/c.py"),
            ("docs/*.md", "docs/readme.md"),
        ]
        for i, (glob_entry, committed_file) in enumerate(cases, start=1):
            sid = f"story-{i:03d}"
            stories = [
                _s(
                    sid,
                    "case",
                    "done",
                    file_domain=[f"{glob_entry} — migrated"],
                ),
            ]
            commits = [commit_event([committed_file], story_id=sid)]
            result = story_metrics._attribute_commits(commits, stories)
            with self.subTest(case=glob_entry):
                self.assertEqual(
                    result[sid]["cascade_size"],
                    0,
                    f"{committed_file} should match {glob_entry}",
                )


if __name__ == "__main__":
    unittest.main()

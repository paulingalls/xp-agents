#!/usr/bin/env python3
"""Tests for sizing_metrics.py — commit-to-story attribution."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _s, commit_event


class TestAttributeCommits(unittest.TestCase):
    def test_single_commit_single_story(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            commit_event(
                ["scripts/auth.py", "scripts/util.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["cascade_size"], 1)

    def test_story_id_determines_attribution(self):
        """story_id determines attribution, not file overlap."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
            _s(
                "story-002",
                "Tests",
                "S",
                "done",
                file_domain=["scripts/auth.py \u2014 update"],
            ),
        ]
        commits = [
            commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-002"]["commits"], 0)

    def test_no_story_id_not_attributed(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [commit_event(["scripts/auth.py"])]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 0)
        self.assertEqual(result["story-001"]["files_changed"], 0)

    def test_cascade_size(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            commit_event(
                [
                    "scripts/auth.py",
                    "scripts/x.py",
                    "scripts/y.py",
                    "scripts/z.py",
                ],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["cascade_size"], 3)

    def test_no_file_domain(self):
        import sizing_metrics

        stories = [
            _s("story-001", "Auth", "M", "done", file_domain=[]),
        ]
        commits = [
            commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["cascade_size"], 1)

    def test_test_file_matches_source_domain(self):
        """tests/hooks/test_foo.py should match domain scripts/foo.py."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=[
                    "scripts/retro_flags.py \u2014 add suppression",
                ],
            ),
        ]
        commits = [
            commit_event(
                [
                    "scripts/retro_flags.py",
                    "tests/hooks/test_retro_flags.py",
                ],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["cascade_size"], 0)

    def test_prefixed_path_matches_domain(self):
        """plugins/xp-agents/scripts/foo.py matches scripts/foo.py."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            commit_event(
                ["plugins/xp-agents/scripts/auth.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["cascade_size"], 0)

    def test_multiple_commits_deduped(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
            commit_event(
                ["scripts/auth.py", "scripts/util.py"],
                story_id="story-001",
            ),
            commit_event(["scripts/unrelated.py"]),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 2)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["cascade_size"], 1)


class TestAttributeCommitsStoryId(unittest.TestCase):
    """_attribute_commits edge cases for story_id-based attribution."""

    def test_unknown_story_id_not_attributed(self):
        """Commit with unknown story_id is not attributed."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 login"],
            ),
        ]
        commits = [
            commit_event(
                ["scripts/auth.py"],
                story_id="story-999",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 0)

    def test_cross_cutting_commit_not_attributed_without_story_id(
        self,
    ):
        """Infrastructure commit without story_id doesn't pollute."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["CLAUDE.md \u2014 docs"],
            ),
        ]
        commits = [
            commit_event(
                ["CLAUDE.md"],
                story_id="story-001",
            ),
            commit_event(
                [
                    "CLAUDE.md",
                    "README.md",
                    "scripts/spawn.py",
                    "tests/test_spawn.py",
                ],
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 1)


if __name__ == "__main__":
    unittest.main()

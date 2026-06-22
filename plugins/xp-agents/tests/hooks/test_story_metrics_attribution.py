#!/usr/bin/env python3
"""Tests for story_metrics.py — commit-to-story attribution."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _s, commit_event


def _write_sprint(
    smm_dir: Path,
    stories: list[dict],
    sprint_id: str = "sprint-001",
) -> None:
    sprint = {
        "sprint_id": sprint_id,
        "goal": "test",
        "started": "2026-04-22",
        "milestone": "test",
        "stories": stories,
    }
    (smm_dir / "sprint.json").write_text(json.dumps(sprint))


class TestAttributeCommits(unittest.TestCase):
    def test_single_commit_single_story(self):
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
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
        result = story_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["cascade_size"], 1)

    def test_story_id_determines_attribution(self):
        """story_id determines attribution, not file overlap."""
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
            _s(
                "story-002",
                "Tests",
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
        result = story_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-002"]["commits"], 0)

    def test_no_story_id_not_attributed(self):
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [commit_event(["scripts/auth.py"])]
        result = story_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 0)
        self.assertEqual(result["story-001"]["files_changed"], 0)

    def test_cascade_size(self):
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
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
        result = story_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["cascade_size"], 3)

    def test_no_file_domain(self):
        import story_metrics

        stories = [
            _s("story-001", "Auth", "done", file_domain=[]),
        ]
        commits = [
            commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
        ]
        result = story_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["cascade_size"], 1)

    def test_test_file_matches_source_domain(self):
        """tests/hooks/test_foo.py should match domain scripts/foo.py."""
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
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
        result = story_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["cascade_size"], 0)

    def test_prefixed_path_matches_domain(self):
        """plugins/xp-agents/scripts/foo.py matches scripts/foo.py."""
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
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
        result = story_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["cascade_size"], 0)

    def test_multiple_commits_deduped(self):
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
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
        result = story_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 2)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["cascade_size"], 1)


class TestAttributeCommitsStoryId(unittest.TestCase):
    """_attribute_commits edge cases for story_id-based attribution."""

    def test_unknown_story_id_not_attributed(self):
        """Commit with unknown story_id is not attributed."""
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
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
        result = story_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 0)

    def test_cross_cutting_commit_not_attributed_without_story_id(
        self,
    ):
        """Infrastructure commit without story_id doesn't pollute."""
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
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
        result = story_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 1)

    def test_merge_commit_not_attributed(self):
        """metadata.is_merge=True (close-cycle merge from close_common) is
        excluded from per-story commit counts and files_changed when the story
        already has real code commits — the merge HEAD aggregates them and
        would inflate the story's metrics by +1 every close. Unlike
        retro_metrics' UNCONDITIONAL is_merge exclusion, the merge is still
        recorded here as a shipping signal (merged=True) and used as a fallback
        when no real code commit exists (see TestMergeFallbackAttribution)."""
        import story_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "done",
                file_domain=["scripts/auth.py — login"],
            ),
        ]
        commits = [
            commit_event(["scripts/auth.py"], story_id="story-001"),
            commit_event(["scripts/auth.py"], story_id="story-001", is_merge=True),
        ]
        result = story_metrics._attribute_commits(commits, stories)
        # Only the real story commit counts — the merge is filtered out.
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 1)
        # The merge IS recorded as shipping evidence (the branch merged).
        self.assertTrue(result["story-001"]["merged"])


class TestMergeFallbackAttribution(unittest.TestCase):
    """Parallel-teammate stories whose per-story code commits were never
    recorded must not read as 0-commit / attribution-blind: the attributed
    close-cycle merge is the reliable per-story shipping signal."""

    def test_merge_only_counts_as_shipping_evidence(self):
        """No recorded code commits, only the attributed merge → commits=1,
        merge files folded in, merged flag set. (The teammate-recording gap.)"""
        import story_metrics

        stories = [
            _s("story-001", "Auth", "done", file_domain=["scripts/auth.py — login"]),
        ]
        commits = [
            commit_event(
                ["scripts/auth.py", "scripts/util.py"],
                story_id="story-001",
                is_merge=True,
            ),
        ]
        result = story_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["cascade_size"], 1)
        self.assertTrue(result["story-001"]["merged"])

    def test_no_merge_no_commits_is_blind_zero(self):
        """No commits at all → commits=0, merged=False (genuinely no work)."""
        import story_metrics

        stories = [
            _s("story-001", "Auth", "done", file_domain=["scripts/auth.py — login"]),
        ]
        result = story_metrics._attribute_commits([], stories)
        self.assertEqual(result["story-001"]["commits"], 0)
        self.assertEqual(result["story-001"]["files_changed"], 0)
        self.assertFalse(result["story-001"]["merged"])

    def test_real_commits_present_merge_not_counted_but_flagged(self):
        """Real code commits → +1 guard holds (merge not counted), merged set."""
        import story_metrics

        stories = [
            _s("story-001", "Auth", "done", file_domain=["scripts/auth.py — login"]),
        ]
        commits = [
            commit_event(["scripts/auth.py"], story_id="story-001"),
            commit_event(["scripts/auth.py"], story_id="story-001"),
            commit_event(["scripts/auth.py"], story_id="story-001", is_merge=True),
        ]
        result = story_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 2)
        self.assertTrue(result["story-001"]["merged"])

    def test_merge_only_surfaces_in_compute_story_analysis(self):
        """The merged flag flows through to per_story output for retros."""
        import story_metrics

        stories = [
            _s("story-001", "Auth", "done", file_domain=["scripts/auth.py — login"]),
        ]
        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            _write_sprint(smm_dir, stories, sprint_id="sprint-001")
            events = [
                commit_event(
                    ["scripts/auth.py"],
                    ts="2026-04-22T10:00:00+00:00",
                    story_id="story-001",
                    sprint_id="sprint-001",
                    is_merge=True,
                ),
            ]
            result = story_metrics.compute_story_analysis(smm_dir, events)
            assert result is not None
            story = result["per_story"][0]
            self.assertEqual(story["commits"], 1)
            self.assertTrue(story["merged"])


class TestCodeFreeFlag(unittest.TestCase):
    """code_free flag distinguishes investigation-only from code-expected stories."""

    def test_empty_file_domain_is_code_free(self):
        import story_metrics

        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            _write_sprint(
                smm_dir,
                [_s("story-001", "Investigate auth gap", "done", file_domain=[])],
            )
            result = story_metrics.compute_story_analysis(smm_dir, [])
            assert result is not None
            self.assertTrue(result["per_story"][0]["code_free"])

    def test_populated_file_domain_is_not_code_free(self):
        import story_metrics

        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            _write_sprint(
                smm_dir,
                [
                    _s(
                        "story-001",
                        "Add auth",
                        "done",
                        file_domain=["scripts/auth.py — login"],
                    )
                ],
            )
            result = story_metrics.compute_story_analysis(smm_dir, [])
            assert result is not None
            self.assertFalse(result["per_story"][0]["code_free"])


class TestSprintScopedAttribution(unittest.TestCase):
    """compute_story_analysis must scope commits by sprint_id."""

    def test_excludes_commits_from_other_sprint(self):
        """Commits with a different sprint_id are excluded even if story_id matches."""
        import story_metrics

        stories = [
            _s("story-001", "Auth", "done", file_domain=["scripts/auth.py — login"]),
        ]
        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            _write_sprint(smm_dir, stories, sprint_id="sprint-002")

            events = [
                commit_event(
                    ["scripts/auth.py"],
                    ts="2026-04-22T10:00:00+00:00",
                    story_id="story-001",
                    sprint_id="sprint-001",
                ),
                commit_event(
                    ["scripts/auth.py"],
                    ts="2026-04-22T11:00:00+00:00",
                    story_id="story-001",
                    sprint_id="sprint-001",
                ),
                commit_event(
                    ["scripts/auth.py"],
                    ts="2026-04-22T12:00:00+00:00",
                    story_id="story-001",
                    sprint_id="sprint-002",
                ),
            ]

            result = story_metrics.compute_story_analysis(smm_dir, events)
            assert result is not None
            story = result["per_story"][0]
            self.assertEqual(story["commits"], 1)

    def test_includes_commits_without_sprint_id(self):
        """Old commits without sprint_id are included (backward compat)."""
        import story_metrics

        stories = [
            _s("story-001", "Auth", "done", file_domain=["scripts/auth.py — login"]),
        ]
        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            _write_sprint(smm_dir, stories, sprint_id="sprint-002")

            events = [
                commit_event(
                    ["scripts/auth.py"],
                    ts="2026-04-22T10:00:00+00:00",
                    story_id="story-001",
                ),
            ]

            result = story_metrics.compute_story_analysis(smm_dir, events)
            assert result is not None
            story = result["per_story"][0]
            self.assertEqual(story["commits"], 1)


if __name__ == "__main__":
    unittest.main()

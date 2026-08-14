#!/usr/bin/env python3
"""How a MERGE attributes to a story — the half of attribution that turns on
which emitter recorded it.

Split from `test_story_metrics_attribution.py` when it crossed the 500-line cap.
The seam is the honest one rather than the convenient one: everything here turns
on `metadata.is_merge` and on WHO wrote the event, while that file answers the
prior question of which story a commit belongs to at all.

Why the emitter matters: `is_merge` stopped meaning "the story shipped" once the
commit hook began tagging every two-parent HEAD from its parent count. A
close-cycle merge (agent `close_common`) is the shipping signal; a hand-run
back-merge carrying the same tag and the same story id is not.
"""

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
    """A sprint.json for the one case here that drives the whole analysis rather
    than `_attribute_commits` directly. Duplicated from the sibling suite rather
    than shared: three lines of literal, and hoisting it into a fixture module
    would put the seam in the wrong place for two callers."""
    sprint = {
        "sprint_id": sprint_id,
        "goal": "test",
        "started": "2026-04-22",
        "milestone": "test",
        "stories": stories,
    }
    (smm_dir / "sprint.json").write_text(json.dumps(sprint))


class TestAMergesEmitterDecidesWhatItMeans(unittest.TestCase):
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
            commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
                is_merge=True,
                agent_id="close_common",
            ),
        ]
        result = story_metrics._attribute_commits(commits, stories)
        # Only the real story commit counts — the merge is filtered out.
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 1)
        # The merge IS recorded as shipping evidence (the branch merged).
        self.assertTrue(result["story-001"]["merged"])

    def test_a_hand_run_back_merge_is_not_shipping_evidence(self):
        """`is_merge` alone stopped meaning "the story shipped" once the commit
        hook began tagging every two-parent HEAD from the parent count. A teammate
        running `git merge main` mid-story to keep the branch current produces an
        is_merge event carrying that story's id, from agent `main` rather than
        `close_common` — and reading it as a close marked the story merged and
        dropped its only recorded commit, so sprint review reported a story merged
        that was still in progress.

        It is not counted as a story commit either: the files are upstream work the
        branch absorbed, not the story's own."""
        import story_metrics

        stories = [
            _s("story-001", "Auth", "in-progress", file_domain=["scripts/auth.py — x"]),
        ]
        commits = [
            commit_event(["scripts/auth.py"], story_id="story-001"),
            commit_event(
                ["scripts/unrelated.py"],
                story_id="story-001",
                is_merge=True,
                agent_id="main",
            ),
        ]
        result = story_metrics._attribute_commits(commits, stories)
        self.assertFalse(
            result["story-001"]["merged"],
            "a mid-story back-merge was read as the story shipping",
        )
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 1)


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
                agent_id="close_common",
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
            commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
                is_merge=True,
                agent_id="close_common",
            ),
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
                    agent_id="close_common",
                ),
            ]
            result = story_metrics.compute_story_analysis(smm_dir, events)
            assert result is not None
            story = result["per_story"][0]
            self.assertEqual(story["commits"], 1)
            self.assertTrue(story["merged"])


if __name__ == "__main__":
    unittest.main()

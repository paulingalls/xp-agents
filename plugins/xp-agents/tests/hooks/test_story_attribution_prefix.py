#!/usr/bin/env python3
"""Tests for Tier 0 of _resolve_story_id — the `[story-NNN]` commit prefix.

Split from test_story_attribution.py to keep files under 500 lines. Covers
the explicit-prefix tier: it wins for in-motion stories (in-progress /
reviewing / closing) and is ignored as a stale tag otherwise (done /
deferred).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commit_handling
from conftest import _HookTestCase, _s, _sprint_json


class TestResolveStoryIdPrefix(_HookTestCase):
    """Tier 0: `[story-NNN]` commit-message prefix attribution."""

    def test_tier0_commit_message_prefix_overrides_file_overlap(self):
        """[story-NNN] prefix in commit message wins over file-domain overlap.

        Real bug from sprint-033: solo agent with multiple in-progress
        stories had story-001 commits attributed to story-002 because the
        commit's files overlapped story-002's declared domain (the rename
        commit touched xp-sprint-close/SKILL.md which was in story-002's
        domain). Commit message prefix is the ground truth — every commit
        was authored as `[story-001] Rename merge-sprint...` — so the
        prefix overrides file-overlap when both are present.
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Marker",
                        "in-progress",
                        file_domain=["scripts/markers.py — new entry"],
                    ),
                    _s(
                        "story-002",
                        "Sprint-close edit",
                        "in-progress",
                        file_domain=["skills/xp-sprint-close/SKILL.md — append"],
                    ),
                ]
            )
        )
        # Files overlap story-002's domain only — but the message says story-001.
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["skills/xp-sprint-close/SKILL.md"],
            message="[story-001] Rename merge-sprint to merge-branch",
        )
        self.assertEqual(result, "story-001")

    def test_tier0_prefix_ignored_for_non_in_motion_story(self):
        """[story-NNN] prefix is ignored when that story is done/deferred.

        A prefix naming a non-in-motion (here: done) story is treated as a
        likely stale tag and falls through to file-overlap. In-motion stories
        (in-progress/reviewing/closing) are covered by the closing-status
        tests above.
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Marker",
                        "done",  # NOT in-progress
                        file_domain=["scripts/markers.py — new entry"],
                    ),
                    _s(
                        "story-002",
                        "Sprint-close edit",
                        "in-progress",
                        file_domain=["skills/xp-sprint-close/SKILL.md — append"],
                    ),
                ]
            )
        )
        # Message claims story-001 but story-001 isn't in-progress; fall
        # through to file-overlap (which picks story-002).
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["skills/xp-sprint-close/SKILL.md"],
            message="[story-001] Stale tag",
        )
        self.assertEqual(result, "story-002")

    def test_tier0_no_prefix_falls_through_to_file_overlap(self):
        """Commit messages without [story-NNN] prefix fall through to Tier 2."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py — login"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["scripts/auth.py"],
            message="Refactor login flow",
        )
        self.assertEqual(result, "story-001")

    def test_tier0_prefix_attributes_story_in_closing_status(self):
        """[story-NNN] prefix attributes a commit while the story is closing.

        Story-cadence review fixes (/xp-story-close Step 4.5b) are committed
        while the story is `closing` — no story is in-progress. The explicit
        `[story-NNN]` prefix must still attribute, or the review commit is
        dropped from per-story metrics (the "story commits = 0" bug).
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Accept preload",
                        "closing",
                        file_domain=["scripts/accept.py — preload"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["scripts/accept.py"],
            message="[story-001] review: typed inspect snapshot",
        )
        self.assertEqual(result, "story-001")

    def test_tier0_prefix_attributes_story_in_reviewing_status(self):
        """[story-NNN] prefix attributes a commit while the story is reviewing.

        `reviewing` is the other in-motion status besides `closing` that the
        story leaves `in-progress` for. Covered by the same
        IN_MOTION_STORY_STATUSES frozenset, but exercised explicitly so a
        regression in either status is caught.
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "reviewing",
                        file_domain=["scripts/auth.py — login"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["scripts/auth.py"],
            message="[story-001] review: tighten login",
        )
        self.assertEqual(result, "story-001")

    def test_tier0_prefix_ignored_for_deferred_story(self):
        """[story-NNN] prefix is ignored when the named story is deferred.

        `deferred` (like `done`) is not in-motion, so the prefix is a likely
        stale tag and falls through to file-overlap against the in-progress
        story.
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Deferred one",
                        "deferred",
                        file_domain=["scripts/a.py — x"],
                    ),
                    _s(
                        "story-002",
                        "In progress",
                        "in-progress",
                        file_domain=["scripts/b.py — y"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["scripts/b.py"],
            message="[story-001] stale tag",
        )
        self.assertEqual(result, "story-002")

    def test_tier0_prefix_wins_for_closing_story_over_concurrent_in_progress(self):
        """A closing story's tagged review commit beats a concurrent in-progress
        story whose domain the files happen to touch.

        Overlapping-frontier close: story-001 is closing while story-002 is
        still in-progress. A `[story-001] review:` commit touching story-002's
        declared domain must attribute to story-001 (the explicit tag), not
        fall through to file-overlap.
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Closing one",
                        "closing",
                        file_domain=["scripts/a.py — x"],
                    ),
                    _s(
                        "story-002",
                        "In progress",
                        "in-progress",
                        file_domain=["scripts/b.py — y"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["scripts/b.py"],  # overlaps story-002's domain
            message="[story-001] review: fix",
        )
        self.assertEqual(result, "story-001")


if __name__ == "__main__":
    unittest.main()

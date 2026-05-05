#!/usr/bin/env python3
"""Tests for _resolve_story_id — four-tier commit-to-story attribution.

Split from test_bash.py to keep files under 500 lines.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, _s, _sprint_json
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT


class TestResolveStoryId(_HookTestCase):
    """Tests for _resolve_story_id: four-tier commit-to-story attribution."""

    def test_tier1_teammate_reads_assignment_file(self):
        """Teammate with .story-assignment file returns its story_id."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "teammate-step-1")
        assignment.write_text("story-001")
        result = bash_post_tool._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/teammate-step-1",
            ["src/app.py"],
        )
        self.assertEqual(result, "story-001")

    def test_tier1_no_assignment_falls_through(self):
        """Teammate without assignment file falls through to tier 2/3."""
        result = bash_post_tool._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/teammate-step-1",
            ["src/app.py"],
        )
        self.assertIsNone(result)

    def test_tier2_solo_single_in_progress(self):
        """Solo sprint with one in-progress story attributes to it."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    )
                ],
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py"]
        )
        self.assertEqual(result, "story-001")

    def test_tier2_solo_multiple_tiebreak_by_overlap(self):
        """Multiple in-progress stories tiebreak by file domain overlap."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["src/ui.py", "src/util.py"]
        )
        self.assertEqual(result, "story-002")

    def test_tier2_multi_way_tie_returns_none(self):
        """Multiple in-progress stories with identical overlap → None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py", "src/ui.py"]
        )
        self.assertIsNone(result)

    def test_tier2_solo_multiple_no_overlap_returns_none(self):
        """Multiple in-progress stories with no overlap returns None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["unrelated.py"]
        )
        self.assertIsNone(result)

    def test_tier3_no_sprint_returns_none(self):
        """No sprint.json returns None."""
        result = bash_post_tool._resolve_story_id(self.smm_dir, "/proj", ["setup.py"])
        self.assertIsNone(result)

    def test_tier3_no_in_progress_stories(self):
        """Sprint with no in-progress stories returns None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "done",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py"]
        )
        self.assertIsNone(result)

    def test_commit_metadata_includes_story_id(self):
        """Commit event metadata includes story_id when resolved."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "teammate-step-1")
        assignment.write_text("story-003")

        with patch_commits(files=["a.py"], body="Add feature", head_sha="def456"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add feature'",
                    stdout="[main def456] Add feature\n 1 file changed",
                    cwd="/proj/.claude/worktrees/teammate-step-1",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(commit_ev), 1)
        self.assertEqual(commit_ev[0]["metadata"]["story_id"], "story-003")

    def test_commit_metadata_no_story_id_when_not_resolved(self):
        """Commit event metadata omits story_id when not resolved."""
        with patch_commits(files=["a.py"], body="Fix bug", head_sha="aaa111"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main aaa111] Fix bug\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(commit_ev), 1)
        self.assertNotIn("story_id", commit_ev[0]["metadata"])

    def test_solo_agent_ignores_marker_uses_file_domain(self):
        """Solo agent (name=main) ignores .story-assignment-main, uses Tier 2."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "main")
        assignment.write_text("story-001")
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py — login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py — layout"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(self.smm_dir, "/proj", ["src/ui.py"])
        self.assertEqual(result, "story-002")

    def test_solo_agent_single_story_ignores_stale_marker(self):
        """Solo agent with one in-progress story ignores stale marker."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "main")
        assignment.write_text("story-old")
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
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py"]
        )
        self.assertEqual(result, "story-001")

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
        result = bash_post_tool._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["skills/xp-sprint-close/SKILL.md"],
            message="[story-001] Rename merge-sprint to merge-branch",
        )
        self.assertEqual(result, "story-001")

    def test_tier0_prefix_must_match_in_progress_story(self):
        """[story-NNN] prefix only matches when that story is in-progress."""
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
        result = bash_post_tool._resolve_story_id(
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
        result = bash_post_tool._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["scripts/auth.py"],
            message="Refactor login flow",
        )
        self.assertEqual(result, "story-001")

    def test_teammate_still_reads_assignment_marker(self):
        """Teammates still use Tier 1 marker (regression guard)."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "teammate-step-1")
        assignment.write_text("story-001")
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py — login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py — layout"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/teammate-step-1",
            ["src/ui.py"],
        )
        self.assertEqual(result, "story-001")


if __name__ == "__main__":
    unittest.main()

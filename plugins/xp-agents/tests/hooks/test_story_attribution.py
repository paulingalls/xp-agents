#!/usr/bin/env python3
"""Tests for _resolve_story_id — three-tier commit-to-story attribution.

Split from test_bash.py to keep files under 500 lines.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
from conftest import _HookTestCase, _make_bash_input, _s, _sprint_json


class TestResolveStoryId(_HookTestCase):
    """Tests for _resolve_story_id: three-tier commit-to-story attribution."""

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
                        "M",
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
                        "M",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "M",
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
                        "M",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "M",
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
                        "M",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "M",
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
                        "M",
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

        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch(
                "commits.get_commit_message_body",
                return_value="Add feature",
            ),
            patch("commits.get_head_commit_hash", return_value="def456"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add feature'",
                    stdout="[main def456] Add feature\n 1 file changed",
                    cwd="/proj/.claude/worktrees/teammate-step-1",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(commit_ev), 1)
        self.assertEqual(commit_ev[0]["metadata"]["story_id"], "story-003")

    def test_commit_metadata_no_story_id_when_not_resolved(self):
        """Commit event metadata omits story_id when not resolved."""
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch(
                "commits.get_commit_message_body",
                return_value="Fix bug",
            ),
            patch("commits.get_head_commit_hash", return_value="aaa111"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main aaa111] Fix bug\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(commit_ev), 1)
        self.assertNotIn("story_id", commit_ev[0]["metadata"])

    def test_lead_agent_reads_story_assignment_main(self):
        """Lead agent (non-worktree) uses .story-assignment-main marker."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "main")
        assignment.write_text("story-002")
        result = bash_post_tool._resolve_story_id(self.smm_dir, "/proj", ["src/app.py"])
        self.assertEqual(result, "story-002")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: worktree agent ID and resolves trailer nudge.

Split from test_pre_tool_bash_gates.py to keep files under 500 lines.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from unittest.mock import patch

import _common
import markers
import pre_tool_bash
from conftest import (
    _HookTestCase,
    _make_bash_input,
    _ProbeTestHelpers,
    make_event,
)
from event_schema import EVENT_TYPE_CONCERN, METADATA_KEY_PROBE_CANDIDATES

_COMMIT_CMD = "git commit -m 'test'"


class TestPreToolBashWorktreeAgentId(_HookTestCase):
    """Commit gate reads markers under worktree-derived agent_id."""

    def test_worktree_cwd_reads_correct_markers(self):
        """Worktree cwd resolves agent_id for commit gate markers.

        With only simplify_done set under the worktree-derived agent_id,
        the gate must block on /xp-quality-review (proves it read the
        worktree-scoped marker, not main's empty cycle).
        """
        markers.set_review_flag(self.smm_dir, "teammate-story-001", "simplify_done")
        inp = _make_bash_input(
            command=_COMMIT_CMD,
            cwd="/proj/.claude/worktrees/teammate-story-001",
            agent_id="",
        )
        with patch(
            "commits.get_code_files_for_review",
            return_value=["a.py", "b.py", "c.py"],
        ):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(inp, smm_dir=self.smm_dir)
            self.assertIn("/xp-quality-review", str(ctx.exception))


class TestResolvesTrailerNudge(_ProbeTestHelpers, _HookTestCase):
    """Pre-commit nudge when staged files overlap open concerns."""

    def _write_concern(self, content: str, files: list[str]) -> str:
        event = make_event(
            EVENT_TYPE_CONCERN, content=content, severity="medium", files=files
        )
        self._write_events([event])
        return event["id"]

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_blocks_when_overlap_concern_and_no_trailer(self, *_mocks):
        """Staged files overlap an open concern AND the commit message lacks
        any Resolves-Event trailer → block. The advisory nudge arrived too
        late to influence the same commit (concern a47dda9f00bd: 4th
        attempt at making the trailer convention stick — escalating from
        nudge to block when the LLM has the candidate IDs in hand)."""
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD),
                smm_dir=self.smm_dir,
            )
        self.assertIn("Resolves-Event", str(ctx.exception))

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_explicit_none_trailer_bypasses_block(self, *_mocks):
        """`Resolves-Event: none` is the universal escape — the agent has
        considered the candidates and consciously declines to claim any."""
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        cmd = 'git commit -m "fix unrelated\n\nResolves-Event: none"'
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_mismatched_trailer_id_bypasses_block(self, *_mocks):
        """Any trailer presence (even with IDs that don't match the
        candidates) is treated as good-faith discharge. Pinning this
        choice deliberately: the gate cares whether the agent
        considered trailers, not whether the IDs are correct — the
        agent's intent is opaque and policing IDs would breed false
        positives."""
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        cmd = 'git commit -m "fix auth\n\nResolves-Event: deadbeef0000"'
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )
        # has_trailer=True with non-matching ID: gate bypassed, no nudge.
        self.assertIsNone(result)

    @patch("commits.get_staged_files", return_value=["scripts/other.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_no_concern_nudge_when_no_overlap(self, *_mocks):
        """No concern-specific nudge, but trailer reminder still appears."""
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD),
            smm_dir=self.smm_dir,
        )
        result = self._assert_not_none(result)
        self.assertNotIn("auth bypass", result)
        self.assertIn("Resolves-Event:", result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_no_nudge_when_trailer_present(self, *_mocks):
        cid = self._write_concern("auth bypass risk", ["scripts/auth.py"])
        cmd = f'git commit -m "fix auth\n\nResolves-Event: {cid}"'
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    def test_no_nudge_on_non_commit(self, *_mocks):
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        result = pre_tool_bash.run(
            _make_bash_input(command="ls -la"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_probe_status_event_emitted_before_block(self, *_mocks):
        """The probe status event is still written even when the commit
        is blocked for missing trailer — the audit trail records that
        the candidates were surfaced to the agent."""
        cid = self._write_concern("auth bypass risk", ["scripts/auth.py"])
        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD),
                smm_dir=self.smm_dir,
            )
        self.assertEqual(len(self._probes()), 1)
        self.assertEqual(
            self._probes()[0]["metadata"][METADATA_KEY_PROBE_CANDIDATES], [cid]
        )

    @patch("commits.get_staged_files", return_value=["scripts/other.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_no_probe_status_event_when_no_overlap(self, *_mocks):
        """No probe status event when staged files don't overlap concerns."""
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD),
            smm_dir=self.smm_dir,
        )
        self.assertEqual(len(self._probes()), 0)


def _multi_story_sprint():
    return {
        "sprint_id": "sprint-099",
        "stories": [
            {
                "id": "story-001",
                "title": "auth",
                "status": "in-progress",
                "file_domain": ["scripts/auth.py"],
            },
            {
                "id": "story-002",
                "title": "billing",
                "status": "in-progress",
                "file_domain": ["scripts/billing.py"],
            },
        ],
    }


_STORY_NUDGE_PREFIX = "Story attribution: staged files match"


class TestStoryProbeIntegration(_ProbeTestHelpers, _HookTestCase):
    """Pre-commit story-prefix nudge wired alongside the resolves-trailer probe."""

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("sprint_store.load_sprint")
    def test_multi_story_no_prefix_dominant_overlap_emits_nudge(
        self, mock_load, *_mocks
    ):
        mock_load.return_value = _multi_story_sprint()
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'wire something up'"),
            smm_dir=self.smm_dir,
        )
        result = self._assert_not_none(result)
        self.assertIn(_STORY_NUDGE_PREFIX, result)
        self.assertIn("story-001", result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("sprint_store.load_sprint")
    def test_multi_story_with_bracket_prefix_silent(self, mock_load, *_mocks):
        mock_load.return_value = _multi_story_sprint()
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m '[chore] cleanup'"),
            smm_dir=self.smm_dir,
        )
        if result is not None:
            self.assertNotIn(_STORY_NUDGE_PREFIX, result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("sprint_store.load_sprint")
    def test_single_story_silent(self, mock_load, *_mocks):
        sprint = _multi_story_sprint()
        sprint["stories"][1]["status"] = "ready"
        mock_load.return_value = sprint
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'subject'"),
            smm_dir=self.smm_dir,
        )
        if result is not None:
            self.assertNotIn(_STORY_NUDGE_PREFIX, result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("sprint_store.load_sprint")
    def test_combined_with_resolves_block(self, mock_load, *_mocks):
        """Both probes fire: resolves block AND story nudge present, story FIRST."""
        mock_load.return_value = _multi_story_sprint()
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="auth bypass risk",
            severity="medium",
            files=["scripts/auth.py"],
        )
        self._write_events([concern])
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD),
                smm_dir=self.smm_dir,
            )
        msg = str(ctx.exception)
        self.assertIn(_STORY_NUDGE_PREFIX, msg)
        self.assertIn("Resolves-Event", msg)
        self.assertLess(
            msg.index(_STORY_NUDGE_PREFIX),
            msg.index("Resolves-Event"),
            "Story nudge must precede Resolves-Event guidance",
        )

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("sprint_store.load_sprint")
    def test_combined_soft_nudge_no_block(self, mock_load, *_mocks):
        """Story nudge + no resolves candidates + no trailer → soft (no block).
        Story nudge precedes the trailer reminder (decision #3)."""
        mock_load.return_value = _multi_story_sprint()
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'wire something up'"),
            smm_dir=self.smm_dir,
        )
        result = self._assert_not_none(result)
        self.assertIn(_STORY_NUDGE_PREFIX, result)
        self.assertIn("Resolves-Event", result)
        self.assertLess(
            result.index(_STORY_NUDGE_PREFIX),
            result.index("Resolves-Event"),
            "Story nudge must precede the trailer reminder",
        )

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("sprint_store.load_sprint")
    def test_worktree_teammate_silent(self, mock_load, *_mocks):
        """Worktree teammate has story_assignment file → Tier 1 attributes;
        story probe stays silent."""
        import worktree

        mock_load.return_value = _multi_story_sprint()
        assignment = worktree.story_assignment_path(self.smm_dir, "teammate-step-1")
        assignment.parent.mkdir(parents=True, exist_ok=True)
        assignment.write_text("story-001")
        result = pre_tool_bash.run(
            _make_bash_input(
                command="git commit -m 'subject'",
                cwd="/proj/.claude/worktrees/teammate-step-1",
            ),
            smm_dir=self.smm_dir,
        )
        if result is not None:
            self.assertNotIn(_STORY_NUDGE_PREFIX, result)


if __name__ == "__main__":
    unittest.main()

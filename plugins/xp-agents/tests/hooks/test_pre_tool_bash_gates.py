#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: review cycle, accept gate, open questions.

Split from test_pre_tool_bash.py -- keeps gate-related test classes separate.
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
import security
from conftest import (
    _HookTestCase,
    _make_bash_input,
    make_event,
)

_COMMIT_CMD = "git commit -m 'test'"


class TestPreToolBashReviewCycle(_HookTestCase):
    """Tests for commit-gated review cycle in pre_tool_bash.py."""

    _CODE_FILES_PATCH = "commits.get_code_files_for_review"

    def test_above_threshold_blocks_no_simplify(self):
        """3+ code files, no flags set -> blocks for /simplify."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/simplify", str(ctx.exception))

    def test_above_threshold_blocks_no_quality_review(self):
        """simplify_done=True -> blocks for /xp-quality-review."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/xp-quality-review", str(ctx.exception))

    def test_above_threshold_blocks_no_security(self):
        """simplify + quality done -> blocks for /xp-security-triage."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/xp-security-triage", str(ctx.exception))

    def test_above_threshold_passes_all_done(self):
        """All 3 flags True -> commit allowed."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        markers.set_review_flag(self.smm_dir, "main", "security_review_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_below_threshold_blocks_without_security(self):
        """1 code file, staged code present, no security marker -> blocks."""
        with (
            patch(self._CODE_FILES_PATCH, return_value=["a.py"]),
            patch("security.has_staged_code_files", return_value=True),
        ):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/xp-security-triage", str(ctx.exception))

    def test_below_threshold_passes_with_security(self):
        """1 code file, security marker exists -> commit allowed."""
        security.write_security_triaged(self.smm_dir)
        with (
            patch(self._CODE_FILES_PATCH, return_value=["a.py"]),
            patch("security.has_staged_code_files", return_value=True),
        ):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_zero_code_files_passes(self):
        """No code files changed and no staged code -> commit allowed."""
        with (
            patch(self._CODE_FILES_PATCH, return_value=[]),
            patch("security.has_staged_code_files", return_value=False),
        ):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_no_code_files_preserves_security_marker(self):
        """No-code commit should NOT consume the security marker pre-commit."""
        security.write_security_triaged(self.smm_dir)
        with (
            patch(self._CODE_FILES_PATCH, return_value=[]),
            patch("security.has_staged_code_files", return_value=False),
        ):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )
        # Marker should still exist — consumption belongs in bash_post_tool
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_xp_agent_skips(self):
        """xp- agents bypass the review cycle gate."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD, agent_type="xp-housekeeper"),
                smm_dir=self.smm_dir,
            )

    def test_uses_last_review_commit(self):
        """Gate reads last_review_commit from marker."""
        markers.reset_review_cycle(self.smm_dir, "main", "abc123")
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        markers.set_review_flag(self.smm_dir, "main", "security_review_done")
        with patch(
            self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]
        ) as mock:
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )
            # Verify the commit hash was passed to get_code_files_for_review
            self.assertEqual(mock.call_args[0][1], "abc123")


class TestAcceptGate(_HookTestCase):
    """Accept gate blocks update-story done without /xp-accept."""

    _SPRINT_CMD = (
        "python3 /path/to/sprint_cli.py --smm-dir /tmp/smm update-story story-001 done"
    )

    def test_update_story_done_with_marker_blocks(self):
        """update-story done with ACCEPT marker should block."""
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(
                _make_bash_input(command=self._SPRINT_CMD),
                smm_dir=self.smm_dir,
            )

    def test_update_story_done_without_marker_allows(self):
        """update-story done without ACCEPT marker should allow."""
        result = pre_tool_bash.run(
            _make_bash_input(command=self._SPRINT_CMD),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_update_story_in_progress_with_marker_allows(self):
        """update-story in-progress should not be blocked."""
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        cmd = self._SPRINT_CMD.replace("done", "in-progress")
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_non_sprint_command_with_marker_allows(self):
        """Regular command should not be blocked by ACCEPT marker."""
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        result = pre_tool_bash.run(
            _make_bash_input(command="python3 -m unittest -v"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestPreToolBashDecisionOpenQuestions(_HookTestCase):
    """Decision-time nudge: open-questions context injected when
    `append.sh --type decision` is invoked without metadata.resolves.
    """

    _APPEND = "bash /plugin/smm/append.sh"

    def _decision_cmd(self, *extra: str) -> str:
        return " ".join(
            [
                self._APPEND,
                "--type",
                "decision",
                "--topic",
                "foo",
                "--content",
                "bar",
                *extra,
            ]
        )

    def test_decision_without_resolves_lists_open_questions(self):
        """Decision append without --metadata lists each open question."""
        q_open = make_event(
            "question",
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate on every request?",
        )
        q_resolved = make_event(
            "question",
            id="bbbbbbbbbbbb",
            topic="auth",
            content="Do we need SSO in v1?",
        )
        d_resolver = make_event(
            "decision",
            id="cccccccccccc",
            topic="auth",
            content="No SSO in v1",
            metadata={"resolves": ["bbbbbbbbbbbb"]},
        )
        self._write_events([q_open, q_resolved, d_resolver])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd()),
            smm_dir=self.smm_dir,
        )

        self.assertIsNotNone(result)
        self.assertIn("aaaaaaaaaaaa", result)
        self.assertIn("Should refresh tokens rotate", result)
        self.assertNotIn("bbbbbbbbbbbb", result)

    def test_decision_with_resolves_metadata_no_injection(self):
        """Decision append carrying --metadata resolves ... does not nudge."""
        q_open = make_event(
            "question",
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate on every request?",
        )
        self._write_events([q_open])

        # Shell-quoted JSON — mirrors how an agent composes the command.
        cmd = self._decision_cmd(
            "--metadata",
            "'" + '{"resolves":["aaaaaaaaaaaa"]}' + "'",
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_non_decision_append_no_injection(self):
        """Append of any non-decision type does not trigger the nudge."""
        q_open = make_event(
            "question",
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate?",
        )
        self._write_events([q_open])

        cmd = f"{self._APPEND} --type concern --content 'slow build' --severity medium"
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_no_open_questions_no_injection(self):
        """Fast-path: zero open questions means no nudge on decision."""
        self._write_events([])
        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd()),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_quoted_decision_text_is_ignored(self):
        """'--type decision' inside a quoted --content must not trigger the nudge."""
        q_open = make_event(
            "question",
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate?",
        )
        self._write_events([q_open])

        cmd = (
            f"{self._APPEND} --type concern --content "
            '"discussed append.sh --type decision previously" --severity low'
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)


class TestMainBranchGate(_HookTestCase):
    """Main-branch gate: nudge when committing on protected branch at stage >= 1."""

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_nudge_on_main_stage_1(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("story branch", result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=0)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_silent_at_stage_0(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="paul/story-001-feat")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_silent_on_feature_branch(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_escape_hatch_release(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command='git commit -m "[release] bump version"'),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_escape_hatch_chore(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command='git commit -m "[chore] update deps"'),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="master")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_nudge_on_master_stage_2(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("story branch", result)


class TestSprintBranchGate(_HookTestCase):
    """Sprint branch gate: nudge on direct commit to sprint branch."""

    @patch("identity.get_current_branch", return_value="paul/sprint-027-integration")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("branching.is_sprint_branch", return_value=True)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_nudge_on_sprint_branch_stage_2(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("sprint branch", result)
        self.assertIn("story branch", result)

    @patch("identity.get_current_branch", return_value="paul/sprint-027-integration")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("branching.is_sprint_branch", return_value=True)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_silent_at_stage_1(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="paul/story-001-feature")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("branching.is_sprint_branch", return_value=False)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_silent_on_story_branch(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="paul/sprint-027-integration")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("branching.is_sprint_branch", return_value=True)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_escape_hatch_bypasses_sprint_branch_gate(self, *_mocks):
        """[chore] / [release] prefix bypasses the sprint-branch nudge.

        Closes concern ef916d0f3c65: legitimate post-merge cleanup work
        on the sprint branch is inherently sprint-scope — needs an
        explicit escape hatch. Same convention as the protected-branch
        gate.
        """
        for prefix in ("[chore]", "[release]"):
            with self.subTest(prefix=prefix):
                result = pre_tool_bash.run(
                    _make_bash_input(
                        command=f'git commit -m "{prefix} post-merge cleanup"'
                    ),
                    smm_dir=self.smm_dir,
                )
                # Mirrors test_escape_hatch_release: with no code files and
                # no other nudges fired, a successful bypass returns None.
                self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

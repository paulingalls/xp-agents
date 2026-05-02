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

    def test_above_threshold_passes_all_done(self):
        """All flags True -> commit allowed."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_below_threshold_passes(self):
        """M-4: below-threshold commits (<3 code files) skip the review-cycle
        gate entirely. Tier 2/3 cover security at /xp-accept and close."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_zero_code_files_passes(self):
        """No code files changed -> commit allowed."""
        with patch(self._CODE_FILES_PATCH, return_value=[]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

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
    def test_silent_at_stage_0(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="paul/story-001-feat")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_silent_on_feature_branch(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
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
    def test_escape_hatch_chore(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command='git commit -m "[chore] update deps"'),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_escape_hatch_sprint_direct(self, *_mocks):
        # [sprint-direct] is the close-window bypass token per
        # constraint b2467c56ddbf. Should bypass the protected-branch gate.
        result = pre_tool_bash.run(
            _make_bash_input(command='git commit -m "[sprint-direct] cleanup"'),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="master")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
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
    def test_escape_hatch_bypasses_sprint_branch_gate(self, *_mocks):
        """[chore] / [release] / [sprint-direct] bypass the sprint-branch nudge.

        Closes concern ef916d0f3c65: legitimate post-merge cleanup work
        on the sprint branch is inherently sprint-scope — needs an
        explicit escape hatch. [sprint-direct] is the canonical token
        for the close-window flow per constraint b2467c56ddbf.
        """
        for prefix in ("[chore]", "[release]", "[sprint-direct]"):
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


class TestSubprocessConsolidation(_HookTestCase):
    """Story-007 regression: per `git commit` attempt, pre_tool_bash makes
    at most one `git diff --cached --name-only` subprocess invocation in the
    common path (no `-a` flag, no inline `git add`). Earlier the hook re-shelled
    multiple times to compute the same data derivable from the cached
    unified diff fetched at line 140.
    """

    def _fake_run(self, args, **kwargs):
        """Stand-in for subprocess.run that returns empty success."""
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        return mock_result

    def test_common_path_at_most_one_name_only_call(self):
        with patch("subprocess.run", side_effect=self._fake_run) as mock_run:
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

        name_only_calls = [
            call
            for call in mock_run.call_args_list
            if call.args
            and list(call.args[0]) == ["git", "diff", "--cached", "--name-only"]
        ]
        all_calls = [list(c.args[0]) if c.args else [] for c in mock_run.call_args_list]
        self.assertLessEqual(
            len(name_only_calls),
            1,
            f"Expected ≤1 `git diff --cached --name-only` call, got "
            f"{len(name_only_calls)}. All subprocess calls: {all_calls}",
        )


if __name__ == "__main__":
    unittest.main()

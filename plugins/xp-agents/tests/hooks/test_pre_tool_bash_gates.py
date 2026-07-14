#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: review cycle, accept gate, open questions.

Split from test_pre_tool_bash.py -- keeps gate-related test classes separate.
"""

import sys
import tempfile
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
from _branching_fixtures import write_system_context
from conftest import (
    _HookTestCase,
    _make_bash_input,
    make_event,
)
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_QUESTION

_COMMIT_CMD = "git commit -m 'test'"


class TestPreToolBashReviewCycle(_HookTestCase):
    """Tests for commit-gated review cycle in pre_tool_bash.py."""

    _CODE_FILES_PATCH = "commits.get_code_files_for_review"

    def test_above_threshold_blocks_without_quality_review(self):
        """3+ code files, no flags set -> blocks for /xp-quality-review.

        Per-increment review is now /xp-quality-review only (xp-code-reviewer
        self-finds correctness); /code-review no longer gates a commit."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/xp-quality-review", str(ctx.exception))
            self.assertNotIn("/code-review", str(ctx.exception))

    def test_simplify_done_alone_still_blocks(self):
        """simplify_done=True but quality_review_done=False -> still blocks.

        simplify_done no longer satisfies the per-commit gate; only
        quality_review_done clears it."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/xp-quality-review", str(ctx.exception))

    def test_above_threshold_passes_quality_review_only(self):
        """quality_review_done=True alone -> commit allowed (simplify_done
        not required)."""
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_below_threshold_passes(self):
        """M-4: below-threshold commits (<3 code files) skip the review-cycle
        gate entirely. /security-review covers the cumulative diff at
        /xp-{free,sprint,plan}-close Step 4.5."""
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

    def test_shipped_continuation_shape_with_marker_blocks(self):
        """/xp-accept Step 4 wraps the invocation across a shell line-continuation.

        The ACCEPT gate matched that shape for free while its regex looked only for
        `update-story <id> done`. Requiring `sprint_cli` on the SAME line (the merge
        gate's tightening, which this gate now shares) silently drops it — and this
        is the ONE shape production actually runs.
        """
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        shipped = (
            "python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir /tmp/smm \\\n"
            "  update-story story-001 done"
        )
        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(
                _make_bash_input(command=shipped),
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
            EVENT_TYPE_QUESTION,
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate on every request?",
        )
        q_resolved = make_event(
            EVENT_TYPE_QUESTION,
            id="bbbbbbbbbbbb",
            topic="auth",
            content="Do we need SSO in v1?",
        )
        d_resolver = make_event(
            EVENT_TYPE_DECISION,
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

        result = self._assert_not_none(result)
        self.assertIn("aaaaaaaaaaaa", result)
        self.assertIn("Should refresh tokens rotate", result)
        self.assertNotIn("bbbbbbbbbbbb", result)

    def test_decision_with_resolves_metadata_no_injection(self):
        """Decision append carrying --metadata resolves ... does not nudge."""
        q_open = make_event(
            EVENT_TYPE_QUESTION,
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
            EVENT_TYPE_QUESTION,
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
            EVENT_TYPE_QUESTION,
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


class TestPreToolBashDecisionSameTopic(_HookTestCase):
    """Decision-time nudge: when emitting on a topic with an existing
    unresolved decision, suggest metadata.supersedes/.resolves. Mirrors
    the same-topic check in concerns.py's superseded-decision detector
    but fires PRE-write so the agent can declare supersedence inline.
    """

    _APPEND = "bash /plugin/smm/append.sh"

    def _decision_cmd(self, topic: str, *extra: str) -> str:
        return " ".join(
            [
                self._APPEND,
                "--type",
                "decision",
                "--topic",
                topic,
                "--content",
                "bar",
                *extra,
            ]
        )

    def test_unresolved_same_topic_decision_triggers_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="Use camelCase",
        )
        self._write_events([prior])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("naming")),
            smm_dir=self.smm_dir,
        )

        result = self._assert_not_none(result)
        self.assertIn("111111111111", result)
        self.assertIn("naming", result)
        # Suggestion should mention both metadata keys to give the agent
        # the choice: supersedes (suppresses the flag) vs resolves
        # (also cascade-closes the prior decision).
        self.assertIn("supersedes", result)
        self.assertIn("resolves", result)

    def test_resolved_same_topic_decision_excluded_from_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="camelCase",
        )
        superseder = make_event(
            EVENT_TYPE_DECISION,
            id="222222222222",
            topic="naming",
            content="snake_case",
            metadata={"resolves": ["111111111111"]},
        )
        self._write_events([prior, superseder])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("naming")),
            smm_dir=self.smm_dir,
        )

        # Prior was explicitly superseded; superseder is the open one.
        result = self._assert_not_none(result)
        self.assertIn("222222222222", result)
        self.assertNotIn("111111111111", result)

    def test_metadata_supersedes_suppresses_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="camelCase",
        )
        self._write_events([prior])

        cmd = self._decision_cmd(
            "naming",
            "--metadata",
            "'" + '{"supersedes":["111111111111"]}' + "'",
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_metadata_resolves_suppresses_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="naming",
            content="camelCase",
        )
        self._write_events([prior])

        cmd = self._decision_cmd(
            "naming",
            "--metadata",
            "'" + '{"resolves":["111111111111"]}' + "'",
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_exempt_topic_no_nudge_even_with_unresolved_prior(self):
        """execution-mode is exempt: never nudge, even with unresolved priors.

        Mirrors concerns.py's SUPERSEDED_DECISION_EXEMPT_TOPICS — multiple
        decisions per session are part of the /xp-assign workflow, not
        silent supersession.
        """
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="execution-mode",
            content="Solo",
        )
        self._write_events([prior])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("execution-mode")),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_different_topic_no_nudge(self):
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="auth",
            content="No SSO in v1",
        )
        self._write_events([prior])

        result = pre_tool_bash.run(
            _make_bash_input(command=self._decision_cmd("execution-mode")),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)

    def test_no_topic_arg_no_nudge(self):
        """Decision without --topic can't have same-topic precedent."""
        prior = make_event(
            EVENT_TYPE_DECISION,
            id="111111111111",
            topic="execution-mode",
            content="Solo",
        )
        self._write_events([prior])

        # Decision command without --topic flag.
        cmd = f"{self._APPEND} --type decision --content 'bar'"
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )

        self.assertIsNone(result)


class TestMainBranchGate(_HookTestCase):
    """Main-branch gate: nudge when committing on protected branch at stage >= 1."""

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_nudge_on_main_stage_1(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        result = self._assert_not_none(result)
        self.assertIn("story branch", result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=0)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_silent_at_stage_0(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="paul/story-001-feat")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_silent_on_feature_branch(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_escape_hatch_release(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command='git commit -m "[release] bump version"'),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_escape_hatch_chore(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command='git commit -m "[chore] update deps"'),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("git_commits.is_git_commit", return_value=True)
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
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_nudge_on_master_stage_2(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        result = self._assert_not_none(result)
        self.assertIn("story branch", result)

    @patch("identity.get_current_branch", return_value="develop")
    @patch("branching.get_branching_stage", return_value=3)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_nudge_on_integration_branch_stage_3(self, *_mocks):
        """At stage 3 with ``integration_branch=develop``, a direct commit
        on the develop branch must trigger the protected-branch nudge.
        Today ``is_protected_branch`` hardcodes ``{main, master}`` and
        ignores the SMM-declared integration branch, so the nudge silently
        never fires.
        """
        write_system_context(
            self.smm_dir,
            stage=3,
            integration_branch="develop",
            protected_branches=["main"],
        )
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        result = self._assert_not_none(result)
        self.assertIn("develop", result)
        self.assertIn("story branch", result)


class TestSprintBranchGate(_HookTestCase):
    """Sprint branch gate: nudge on direct commit to sprint branch."""

    @patch("identity.get_current_branch", return_value="paul/sprint-027-integration")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("branching.is_sprint_branch", return_value=True)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_nudge_on_sprint_branch_stage_2(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        result = self._assert_not_none(result)
        self.assertIn("sprint branch", result)
        self.assertIn("story branch", result)

    @patch("identity.get_current_branch", return_value="paul/sprint-027-integration")
    @patch("branching.get_branching_stage", return_value=1)
    @patch("branching.is_sprint_branch", return_value=True)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_silent_at_stage_1(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="paul/story-001-feature")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("branching.is_sprint_branch", return_value=False)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_silent_on_story_branch(self, *_mocks):
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    @patch("identity.get_current_branch", return_value="paul/sprint-027-integration")
    @patch("branching.get_branching_stage", return_value=2)
    @patch("branching.is_sprint_branch", return_value=True)
    @patch("git_commits.is_git_commit", return_value=True)
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


class TestSprintBranchGateRespectsGitDashC(_HookTestCase):
    """`git -C <path> commit ...` from a sprint-branch cwd must branch-check
    <path>'s branch (story branch in a teammate worktree), not the input cwd.
    """

    @patch("branching.get_branching_stage", return_value=2)
    @patch("git_commits.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    def test_git_dash_c_routes_branch_check_to_target_path(self, *_mocks):
        """`git -C <wt> commit ...` from sprint-cwd checks <wt>'s branch."""
        # Real tmpdir so parse_effective_cwd's is_dir check passes —
        # without that the parser falls back to the input cwd.
        with tempfile.TemporaryDirectory() as wt_path:
            cmd = f"git -C {wt_path} commit -m 'fix bug'"

            def branch_lookup(cwd):
                # Orchestrator cwd → sprint branch (would trigger nudge).
                # Worktree cwd → story branch (must NOT trigger nudge).
                if cwd == wt_path:
                    return "paul/story-001-feature"
                return "paul/sprint-027-integration"

            def is_sprint_lookup(branch):
                return branch == "paul/sprint-027-integration"

            with (
                patch("identity.get_current_branch", side_effect=branch_lookup),
                patch("branching.is_sprint_branch", side_effect=is_sprint_lookup),
            ):
                result = pre_tool_bash.run(
                    _make_bash_input(command=cmd), smm_dir=self.smm_dir
                )
            # Effective branch is the story branch — no nudge expected.
            self.assertIsNone(
                result,
                "git -C <worktree> must route branch-check to the worktree, "
                "not the orchestrator's cwd",
            )


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

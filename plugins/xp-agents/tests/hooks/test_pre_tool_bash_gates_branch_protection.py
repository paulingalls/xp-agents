#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: branch-protection nudges and commit-gate
cwd/subprocess correctness.

Split from test_pre_tool_bash_gates.py -- keeps branch-protection and
cwd-retargeting gate tests separate from the review-cycle/accept and
decision-nudge gates.
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

import pre_tool_bash
from _branching_fixtures import write_system_context
from conftest import (
    _HookTestCase,
    _make_bash_input,
)

_COMMIT_CMD = "git commit -m 'test'"


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

        # Matched as a PREFIX, not an exact argv: this pinned the full list and
        # went vacuous the moment `-z` was appended — matching zero calls, which
        # sails through a `<= 1` assertion while measuring nothing at all.
        name_only_calls = [
            call
            for call in mock_run.call_args_list
            if call.args
            and list(call.args[0])[:4] == ["git", "diff", "--cached", "--name-only"]
        ]
        all_calls = [list(c.args[0]) if c.args else [] for c in mock_run.call_args_list]
        self.assertEqual(
            len(name_only_calls),
            1,
            f"Expected EXACTLY 1 `git diff --cached --name-only` call, got "
            f"{len(name_only_calls)}. Zero means this invariant has gone blind "
            f"(the argv changed shape); two means the gate re-shelled for a "
            f"list the caller already had. All subprocess calls: {all_calls}",
        )


class TestTheCommitGatesReadTheRepoTheCommitLandsIn(_HookTestCase):
    """`git -C <worktree> commit` retargets the REPO — so must every gate's read.

    The gates below the commit branch all shell out to git, and they were handed the
    hook's raw `cwd` while the commit itself ran in the `-C` target. In the main
    checkout nothing is staged, so `git diff --cached` comes back EMPTY: the tier-1
    security scan sees no diff, the lint gate finds no groups, and the commit lands
    with zero coverage from either. A silent no-op, in the pattern this project
    explicitly tells agents to PREFER over `cd` (feedback_cd_persists_in_bash).
    """

    def _seen_cwds(self, command: str, cwd: str) -> dict[str, str]:
        seen: dict[str, str] = {}

        def _diff(where: str) -> str:
            seen["diff"] = where
            return ""

        def _files(where: str) -> list[str]:
            seen["files"] = where
            return []

        def _gate(_staged: list[str], where: str) -> list[str]:
            seen["lint"] = where
            return []

        def _code_files(where: str, *_a, **_kw) -> list[str]:
            seen["review"] = where
            return []

        with (
            patch("commits.get_staged_diff", side_effect=_diff),
            patch("commits.get_staged_files", side_effect=_files),
            patch("staged_lint.staged_lint_gate", side_effect=_gate),
            patch("commits.get_code_files_for_review", side_effect=_code_files),
        ):
            pre_tool_bash.run(
                _make_bash_input(command=command, cwd=cwd), smm_dir=self.smm_dir
            )
        return seen

    def test_git_dash_C_retargets_every_staged_read(self):
        with tempfile.TemporaryDirectory() as worktree:
            seen = self._seen_cwds(f'git -C {worktree} commit -m "x"', "/tmp")

        self.assertEqual(seen["diff"], worktree, "tier-1 scanned the wrong repo")
        self.assertEqual(seen["files"], worktree, "the lint gate saw nothing staged")
        self.assertEqual(seen["lint"], worktree, "and resolved the wrong git root")
        self.assertEqual(seen["review"], worktree, "review cycle counted no files")

    def test_a_plain_commit_still_reads_the_hooks_own_cwd(self):
        """The control: no `-C`, no `cd` — nothing is retargeted."""
        with tempfile.TemporaryDirectory() as repo:
            seen = self._seen_cwds('git commit -m "x"', repo)

            self.assertEqual(
                set(seen.values()), {repo}, "every read stays in the hook's cwd"
            )


if __name__ == "__main__":
    unittest.main()

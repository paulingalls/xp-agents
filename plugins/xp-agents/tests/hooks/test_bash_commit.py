#!/usr/bin/env python3
"""Tests for bash_post_tool commit detection: xp-agent-type leak guard,
effective-cwd resolution (cd/-C parsing), and the single strip_quoted scan
wiring that feeds both.

Review-cycle marker reset, worktree-scoped markers, and multi-commit
sequences live in test_bash_commit_review_cycle.py.
Truncated stdout handling and free-session branch tagging live in
test_bash_commit_detection.py.
Green/red nudge gating (commit-after-green, TDD red gate, push warning)
lives in test_bash_commit_nudges.py.
QR linkage warnings and canonical action events (M2 sprint-041/042)
live in test_bash_commit_qr_linkage.py.
"""

import contextlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import bash_post_tool
import markers
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_COMMIT,
)


class TestCommitRecordingDespiteXpAgentType(_HookTestCase):
    """Commit events must record even when agent_type leaks an xp- prefix.

    Defensive against subagent identity leak: if a Bash tool call is tagged
    with `agent_type="xp-housekeeper"` (or similar xp- agent) the early-return on
    `is_xp_agent` would otherwise drop the commit event. Recording is not
    recursion-inducing — every git commit must leave a trace, regardless of
    which agent's stack the Bash call originated from.

    Established precedent: `subagent_stop.py:162-182` runs review-cycle flag
    handling above the same `is_xp_agent` skip with the comment "Review cycle
    flags must run before is_xp_agent skip because xp-quality-review starts
    with 'xp-' but still needs flag set." Same shape.
    """

    _LEAKED_AGENT_TYPE = "xp-leaked"

    @contextlib.contextmanager
    def _patch_commit_lookups(
        self,
        files: list[str] | None = None,
        body: str = "[story-001] foo",
        head_sha: str = "leakedabc1234",
    ):
        """Patch the commits.* lookups _handle_commit calls into git.

        Class-local wrapper that pins leak-path-specific defaults
        (`[story-001] foo` body, `leakedabc1234` SHA, scripts/x.py path)
        on top of the shared ``patch_commits`` helper.
        """
        with patch_commits(
            files=files or ["plugins/xp-agents/scripts/x.py"],
            body=body,
            head_sha=head_sha,
        ):
            yield

    def _run_leaked_commit(self):
        return bash_post_tool.run(
            _make_bash_input(
                command="git commit -m '[story-001] foo'",
                stdout="[main leakedabc] [story-001] foo\n 1 file changed",
                agent_type=self._LEAKED_AGENT_TYPE,
            ),
            smm_dir=self.smm_dir,
        )

    def test_xp_agent_type_does_not_block_commit_event(self):
        with self._patch_commit_lookups():
            self._run_leaked_commit()
        commit_events = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(commit_events), 1)

    def test_xp_agent_type_still_skips_non_commit_bash(self):
        result = bash_post_tool.run(
            _make_bash_input(
                command="echo hello",
                stdout="hello",
                agent_type=self._LEAKED_AGENT_TYPE,
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertEqual(self._read_events(), [])

    def test_xp_agent_type_does_not_run_lint_resolution(self):
        """Leaked agent_type must not invoke lint_resolution.resolve_lint_on_commit.

        Closes the 4th-of-4 side-effect coverage gap. resolve_lint_on_commit
        runs ruff per committed file and resolves matching lint concerns; on
        the leak path this would resolve concerns under the wrong identity.
        """
        with (
            self._patch_commit_lookups(),
            patch("lint_resolution.resolve_lint_on_commit") as lint_spy,
        ):
            self._run_leaked_commit()
        lint_spy.assert_not_called()

    def test_xp_agent_type_does_not_reset_main_review_cycle(self):
        """Leaked agent_type must not reset main's review-cycle flags."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")

        with self._patch_commit_lookups():
            result = self._run_leaked_commit()

        # Side effect blocked: review-cycle flags unchanged.
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])
        self.assertTrue(cycle["quality_review_done"])
        # No QR-warning leakage to the (leaked) caller.
        self.assertIsNone(result)

    def test_xp_agent_type_failed_commit_records_no_event(self):
        # parse_commit_message returns None when the response lacks the
        # [branch hash] msg line (failed pre-commit hook, rejected commit).
        # _handle_commit must early-return without writing — preserves the
        # graceful "failed commit doesn't poison state" semantic, even when
        # entered via an xp- agent_type leak.
        bash_post_tool.run(
            _make_bash_input(
                command="git commit -m 'x'",
                stdout="pre-commit hook failed: tests-integration",
                agent_type=self._LEAKED_AGENT_TYPE,
            ),
            smm_dir=self.smm_dir,
        )
        self.assertEqual(self._read_events(), [])


class TestPostCommitEffectiveCwd(_HookTestCase):
    """The trailer-extraction trio (get_committed_files / get_head_commit_hash
    / get_commit_message_body) must run against the *effective* cwd parsed
    from the bash command, not input_data.cwd.

    Bug source: an agent does ``cd <wt> && git commit && cd -`` to keep
    Stop hooks unpoisoned (per feedback memory cd_persists_in_bash). The
    PostToolUse:Bash hook fires AFTER the cd-back, so input_data.cwd is the
    orchestrator path, and reading HEAD from it returns the wrong commit
    (or nothing). The Resolves-Event auto-link to concerns then breaks.
    """

    def _run_with_command(self, command: str, *, cwd: str):
        """Drive bash_post_tool.run with the command, return the three
        commits.* mocks so the test can assert the cwd they were called with."""
        with (
            patch(
                "commits.get_head_commit_hash", return_value="abc1234567890"
            ) as head_spy,
            patch("commits.get_committed_files", return_value=["a.py"]) as files_spy,
            patch("commits.get_commit_message_body", return_value="msg") as body_spy,
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=command,
                    stdout="[main abc1234] msg\n 1 file changed",
                    cwd=cwd,
                ),
                smm_dir=self.smm_dir,
            )
        return head_spy, files_spy, body_spy

    def test_bare_git_commit_uses_input_cwd(self):
        """No cd, no -C — fall back to input_data.cwd (existing behavior)."""
        head_spy, files_spy, body_spy = self._run_with_command(
            "git commit -m 'x'", cwd="/orig/cwd"
        )
        head_spy.assert_called_with("/orig/cwd")
        files_spy.assert_called_with("/orig/cwd")
        body_spy.assert_called_with("/orig/cwd")

    def test_cd_then_git_commit_uses_worktree_cwd(self):
        """cd <wt> && git commit [&& cd -] — effective cwd is the worktree."""
        wt = Path(tempfile.mkdtemp())
        try:
            head_spy, files_spy, body_spy = self._run_with_command(
                f"cd {wt} && git commit -m 'x' && cd -",
                cwd="/orig/cwd",
            )
            head_spy.assert_called_with(str(wt))
            files_spy.assert_called_with(str(wt))
            # body is fetched from the effective repo as the first candidate;
            # the stdout-signal fallback reuses that body rather than re-shelling
            # `git log` (no redundant second call), so assert it was read from
            # the worktree — not that it was the LAST call.
            body_spy.assert_any_call(str(wt))
        finally:
            shutil.rmtree(wt)

    def test_git_dash_C_uses_dash_C_path(self):
        """git -C <wt> commit ... — effective cwd is the -C path."""
        wt = Path(tempfile.mkdtemp())
        try:
            head_spy, files_spy, body_spy = self._run_with_command(
                f"git -C {wt} commit -m 'x'",
                cwd="/orig/cwd",
            )
            head_spy.assert_called_with(str(wt))
            files_spy.assert_called_with(str(wt))
            body_spy.assert_any_call(str(wt))
        finally:
            shutil.rmtree(wt)

    def test_cd_to_nonexistent_dir_falls_back(self):
        """Parsed cd path that doesn't exist on disk — fall back, no error."""
        head_spy, files_spy, body_spy = self._run_with_command(
            "cd /surely/does/not/exist/xyz && git commit -m 'x'",
            cwd="/orig/cwd",
        )
        head_spy.assert_called_with("/orig/cwd")
        files_spy.assert_called_with("/orig/cwd")
        body_spy.assert_called_with("/orig/cwd")

    def test_path_capture_excludes_trailing_semicolon(self):
        """`cd /tmp; git commit` captures `/tmp`, not `/tmp;` — the path
        token regex must not absorb statement-boundary chars (`;`, `&`, `|`).
        Without the tightened capture, is_dir() would still reject `/tmp;`
        and silently fall back, masking the parser bug. Reviewer concern
        df69a9faa3c8 — fixed by tightening _PATH_TOKEN to `[^\\s;&|]+`."""
        wt = Path(tempfile.mkdtemp())
        try:
            head_spy, _files_spy, _body_spy = self._run_with_command(
                f"cd {wt}; git commit -m 'x'",
                cwd="/orig/cwd",
            )
            # If the regex absorbed `;`, the path would not match an existing
            # directory and we'd fall back to /orig/cwd. The tightened capture
            # yields the bare worktree path, validated by is_dir().
            head_spy.assert_called_with(str(wt))
        finally:
            shutil.rmtree(wt)

    def test_path_capture_excludes_trailing_pipe(self):
        """`cd /a||true && git commit` captures `/a` (terminator is `|`)."""
        wt = Path(tempfile.mkdtemp())
        try:
            head_spy, _files_spy, _body_spy = self._run_with_command(
                f"cd {wt}||true && git commit -m 'x'",
                cwd="/orig/cwd",
            )
            head_spy.assert_called_with(str(wt))
        finally:
            shutil.rmtree(wt)

    def test_effective_cwd_propagates_to_lint_resolution(self):
        """Same root cause that breaks the trailer trio also breaks lint
        auto-resolution (`lint_resolution.resolve_lint_on_commit` /
        `sweep_orphan_lint_concerns` shell `git -C cwd` for diffs and
        `worktree.normalize_path(file, cwd)` for matching). Both must
        receive the parsed effective_cwd, not input_data.cwd. xp-code-reviewer
        flagged this as concern fa4eb693f334 — same fixture, same fix.
        """
        wt = Path(tempfile.mkdtemp())
        try:
            with (
                patch("commits.get_head_commit_hash", return_value="abc"),
                patch("commits.get_committed_files", return_value=["a.py"]),
                patch("commits.get_commit_message_body", return_value="msg"),
                patch("lint_resolution.resolve_lint_on_commit") as resolve_spy,
                patch("lint_resolution.sweep_orphan_lint_concerns") as sweep_spy,
            ):
                bash_post_tool.run(
                    _make_bash_input(
                        command=f"cd {wt} && git commit -m 'x' && cd -",
                        stdout="[main abc] msg\n 1 file changed",
                        cwd="/orig/cwd",
                    ),
                    smm_dir=self.smm_dir,
                )
            self.assertEqual(resolve_spy.call_args.args[1], str(wt))
            self.assertEqual(sweep_spy.call_args.args[1], str(wt))
        finally:
            shutil.rmtree(wt)

    def test_effective_cwd_propagates_to_story_resolution(self):
        """`_resolve_story_id`'s Tier-1 worktree-assignment lookup also
        depends on cwd — a chained `cd <wt> && commit && cd -` would
        otherwise miss the assignment file and silently fall through to
        the file-domain heuristic. Spy on the helper to confirm the
        parsed worktree path reaches it."""
        wt = Path(tempfile.mkdtemp())
        try:
            with (
                patch("commits.get_head_commit_hash", return_value="abc"),
                patch("commits.get_committed_files", return_value=["a.py"]),
                patch("commits.get_commit_message_body", return_value="msg"),
                patch(
                    "commit_handling._resolve_story_id", return_value=None
                ) as story_spy,
            ):
                bash_post_tool.run(
                    _make_bash_input(
                        command=f"cd {wt} && git commit -m 'x' && cd -",
                        stdout="[main abc] msg\n 1 file changed",
                        cwd="/orig/cwd",
                    ),
                    smm_dir=self.smm_dir,
                )
            self.assertEqual(story_spy.call_args.args[1], str(wt))
        finally:
            shutil.rmtree(wt)

    def test_relative_cd_resolves_against_input_cwd(self):
        """`cd subdir && git commit` with a relative `subdir` resolves
        against input_data.cwd. Mirrors the real worktree shape:
        `cd .claude/worktrees/teammate-X && git commit ...` from a repo root.
        """
        repo = Path(tempfile.mkdtemp())
        sub = repo / "sub"
        sub.mkdir()
        try:
            head_spy, files_spy, body_spy = self._run_with_command(
                "cd sub && git commit -m 'x' && cd -",
                cwd=str(repo),
            )
            head_spy.assert_called_with(str(sub))
            files_spy.assert_called_with(str(sub))
            body_spy.assert_any_call(str(sub))
        finally:
            shutil.rmtree(repo)


class TestStripQuotedSingleScan(_HookTestCase):
    """bash_post_tool runs strip_quoted ONCE per Bash and threads the result
    into both is_git_commit and parse_effective_cwd. Pins the wire-up so
    nobody silently reintroduces the second re.DOTALL heredoc scan that
    each helper used to run independently."""

    def test_commit_shaped_bash_strips_once(self):
        with tempfile.TemporaryDirectory() as wt:
            with (
                patch(
                    "git_commits.strip_quoted",
                    side_effect=lambda cmd: cmd,
                ) as strip_spy,
                patch("commits.get_head_commit_hash", return_value="abc1234567890"),
                patch("commits.get_committed_files", return_value=["a.py"]),
                patch("commits.get_commit_message_body", return_value="msg"),
            ):
                bash_post_tool.run(
                    _make_bash_input(
                        command=f"cd {wt} && git commit -m 'fix' && cd -",
                        stdout="[main abc1234] fix\n 1 file changed",
                        cwd="/orig/cwd",
                    ),
                    smm_dir=self.smm_dir,
                )
            self.assertEqual(
                strip_spy.call_count,
                1,
                f"strip_quoted should run once per Bash, got {strip_spy.call_count}",
            )


if __name__ == "__main__":
    unittest.main()

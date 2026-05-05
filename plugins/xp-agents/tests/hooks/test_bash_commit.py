#!/usr/bin/env python3
"""Tests for bash_post_tool post-commit lifecycle: commit recording,
review cycle, worktree agent_id, green nudge, push warning.

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

import _common
import bash_post_tool
import markers
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, _ProbeTestHelpers, make_event
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_QR_COMPLETE,
)


class TestPostCommitNoProbeEvent(_ProbeTestHelpers, _HookTestCase):
    """Post-commit no longer emits probe status events (moved to pre-commit)."""

    def _run_auth_commit(self):
        with patch_commits(files=["scripts/auth.py"], body="Fix auth"):
            return bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix auth'",
                    stdout="[main abc123] Fix auth\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )

    def test_no_nudge_text_returned(self):
        self._seed_auth_concern()
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_STATUS,
                content="Quality review complete.",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            ),
        )
        result = self._run_auth_commit()
        self.assertIsNone(result)

    def test_no_probe_event_from_post_commit(self):
        self._seed_auth_concern()
        self._run_auth_commit()
        self.assertEqual(len(self._probes()), 0)


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
        commit_events = [
            e for e in self._read_events() if e.get("type") == EVENT_TYPE_COMMIT
        ]
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
            body_spy.assert_called_with(str(wt))
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
            body_spy.assert_called_with(str(wt))
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
                    "bash_post_tool._resolve_story_id", return_value=None
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
            body_spy.assert_called_with(str(sub))
        finally:
            shutil.rmtree(repo)


class TestBashPostToolReviewCycle(_HookTestCase):
    """Tests for review cycle marker reset after commit."""

    def test_commit_resets_review_cycle(self):
        """After commit, review cycle marker has new hash and cleared flags."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_head_commit_hash", return_value="newcommit123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'test'",
                    stdout="[main abc123] test\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(cycle["last_review_commit"], "newcommit123")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_commit_no_hash_skips_reset(self):
        """If git rev-parse fails, no marker written (no crash)."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_head_commit_hash", return_value=None),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'test'",
                    stdout="[main abc123] test\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_non_commit_no_reset(self):
        """Non-commit bash commands don't touch review cycle marker."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        bash_post_tool.run(
            _make_bash_input(command="echo hello", stdout="hello"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_failed_commit_preserves_review_cycle(self):
        """Pre-commit hook failure must not reset review flags."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch("commits.get_head_commit_hash", return_value="prevhash"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'test'",
                    stdout="ruff-check >\n\nFAILED\npre-commit hook failed",
                ),
                smm_dir=self.smm_dir,
            )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])
        self.assertTrue(cycle["quality_review_done"])

    def test_empty_stdout_preserves_markers(self):
        """Content-agnostic guard: any non-success stdout short-circuits effects."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        with patch("commits.get_head_commit_hash", return_value="prevhash"):
            bash_post_tool.run(
                _make_bash_input(command="git commit -m 'test'", stdout=""),
                smm_dir=self.smm_dir,
            )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])


class TestBashPostToolWorktreeAgentId(_HookTestCase):
    """Worktree cwd uses resolve_agent_id for commit handling."""

    def test_commit_resets_worktree_scoped_markers(self):
        """After commit, worktree-scoped markers are reset."""
        agent_id = "teammate-story-001"
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")
        markers.set_review_flag(self.smm_dir, agent_id, "quality_review_done")
        inp = _make_bash_input(
            command="git commit -m 'test'",
            stdout="[main abc123] test\n 1 file changed",
            agent_id="",
            cwd="/proj/.claude/worktrees/teammate-story-001",
        )
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch(
                "commits.get_head_commit_hash",
                return_value="newcommit123",
            ),
        ):
            bash_post_tool.run(inp, smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, agent_id)
        self.assertEqual(cycle["last_review_commit"], "newcommit123")
        self.assertFalse(cycle["simplify_done"])


class TestBashPostToolGreenNudge(_HookTestCase):
    """Tests for commit-after-green nudge in bash_post_tool."""

    def test_green_with_uncommitted_code_returns_nudge(self):
        """All tests pass + uncommitted code files -> nudge string returned."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        assert result is not None
        self.assertIn("commit", result.lower())

    def test_green_no_uncommitted_code_no_nudge(self):
        """All tests pass but no uncommitted code files -> no nudge."""
        with patch("commits.get_uncommitted_code_files", return_value=[]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_green_after_failure_confirms_resolution(self):
        """Tests pass after prior failure -> context confirms resolution."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 3 failed",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)

        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        assert result is not None
        self.assertIn("prior test failures resolved", result.lower())
        self.assertIn("commit", result.lower())

    def test_red_no_nudge(self):
        """Failing tests -> no nudge (even with uncommitted code)."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 3 passed, 2 failed in 1.2s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_xp_agent_no_nudge(self):
        """xp- agents never get the nudge (recursion guard)."""
        result = bash_post_tool.run(
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 0.3s =====",
                agent_type="simplify",
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_zero_passed_zero_failed_no_nudge(self):
        """Ambiguous output (0 passed, 0 failed) -> no nudge."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="no tests ran",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)


class TestBashPostToolPushNoLongerNudges(_HookTestCase):
    """git push must NOT trigger the session-end checklist.

    The Stop hook (session_end_warning.py) owns the legitimate single-
    fire nudge at actual session end. Mid-session pushes were treating
    every git push as a session-end signal — false positive that fired
    multiple times per iteration. Dropped to fix concern 1d18655aa396.
    """

    def test_push_with_unresolved_concerns_does_not_warn(self):
        self._write_events(
            [make_event(EVENT_TYPE_CONCERN, content="Open issue", severity="medium")]
        )
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_push_does_not_nudge_summary(self):
        self._write_events([make_event(EVENT_TYPE_STATUS, content="All done")])
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestBashPostToolMultiCommitSequence(_HookTestCase):
    """Multi-commit sequences in a single session must each record a commit
    event AND each reset review-cycle markers.

    Captures real-world bugs ec4c804139e4 (post-commit hook stops recording
    commit events after the first in a session — Resolves-Event trailers
    never auto-close targets) and 731915a2d4d2 (review-cycle markers persist
    across commits — second commit can pass the gate without re-running the
    cycle). Existing single-commit tests in TestBashPostToolReviewCycle pass,
    so the bugs only surface when two commits run back-to-back through
    bash_post_tool.run.
    """

    def _run_commit(self, *, head_sha: str, body: str, files: list[str]):
        with patch_commits(files=files, body=body, head_sha=head_sha):
            return bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'work'",
                    stdout=f"[main {head_sha[:7]}] work\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )

    def test_two_consecutive_commits_each_record_commit_event(self):
        """Bug ec4c804139e4: every successful code commit must produce a
        commit event in events.jsonl, not just the first."""
        self._run_commit(
            head_sha="aaaaaaa1111111", body="first commit", files=["scripts/a.py"]
        )
        self._run_commit(
            head_sha="bbbbbbb2222222", body="second commit", files=["scripts/b.py"]
        )

        commits = [e for e in self._read_events() if e.get("type") == EVENT_TYPE_COMMIT]
        hashes = [(e.get("metadata") or {}).get("commit_hash") for e in commits]
        self.assertEqual(
            len(commits),
            2,
            f"expected 2 commit events, got {len(commits)}: hashes={hashes}",
        )
        self.assertEqual(hashes, ["aaaaaaa1111111", "bbbbbbb2222222"])

    def test_resolves_event_trailer_auto_closes_open_concern(self):
        """Bug ec4c804139e4 (real-world fixture): commit 6cdd24f's body
        carried `Resolves-Event: 78ab5a70ca1b, 87e022ad0693` but neither
        concern auto-closed because the commit event itself was silently
        dropped, leaving metadata.resolves unwritten."""
        # Seed two open concerns matching the trailer IDs.
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN,
                    id="78ab5a70ca1b",
                    content="leading-slash drop",
                    severity="medium",
                ),
                make_event(
                    EVENT_TYPE_CONCERN,
                    id="87e022ad0693",
                    content="python-bias extension list",
                    severity="medium",
                ),
            ]
        )

        # Two-commit sequence: a benign first commit, then the real fixture.
        self._run_commit(
            head_sha="ccccccc3333333", body="warm up", files=["scripts/x.py"]
        )
        body_with_trailer = (
            "[free] auto-extract: capture leading-slash + expand language set\n"
            "\n"
            "Resolves-Event: 78ab5a70ca1b, 87e022ad0693\n"
        )
        self._run_commit(
            head_sha="6cdd24fcb5a0",
            body=body_with_trailer,
            files=["plugins/xp-agents/smm/event_builder.py"],
        )

        # The second commit event should carry both IDs in metadata.resolves.
        commits = [e for e in self._read_events() if e.get("type") == EVENT_TYPE_COMMIT]
        fixture_commits = [
            e
            for e in commits
            if (e.get("metadata") or {}).get("commit_hash") == "6cdd24fcb5a0"
        ]
        self.assertEqual(
            len(fixture_commits),
            1,
            f"fixture commit event missing; recorded={len(commits)}",
        )
        resolves = (fixture_commits[0].get("metadata") or {}).get("resolves") or []
        self.assertIn("78ab5a70ca1b", resolves)
        self.assertIn("87e022ad0693", resolves)

    def test_git_dash_C_commit_form_records_commit_event(self):
        """Bug ec4c804139e4 root cause: `git -C <path> commit ...` form
        is not recognized by is_git_commit's `\\bgit\\s+commit\\b` regex,
        so the post-commit hook never enters _handle_commit. The agent
        adopted `git -C` to avoid cd-poisoning Stop hooks (per feedback
        memory cd_persists_in_bash); that change silently broke the
        commit detector. 14 commits in sprint-052's free session went
        unrecorded for this reason."""
        real_command = (
            "git -C /Users/paulingalls/src/projects/xp-agents add scripts/x.py "
            "&& git -C /Users/paulingalls/src/projects/xp-agents commit -m "
            "\"$(cat <<'EOF'\n"
            "[free] tighten regex\n\n"
            "Resolves-Event: deadbeef0001\n"
            'EOF\n)"'
        )
        real_stdout = (
            "[paulingalls/some-branch abc1234] [free] tighten regex\n"
            " 1 file changed, 5 insertions(+), 2 deletions(-)\n"
        )
        with patch_commits(
            files=["scripts/x.py"],
            body="[free] tighten regex\n\nResolves-Event: deadbeef0001\n",
            head_sha="abc1234567890",
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=real_command,
                    stdout=real_stdout,
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )
        commits = [e for e in self._read_events() if e.get("type") == EVENT_TYPE_COMMIT]
        self.assertEqual(
            len(commits),
            1,
            "git -C <path> commit form must be recognized by is_git_commit "
            "and produce a commit event",
        )

    def test_real_world_b679c79_command_records_commit_event(self):
        """Replay commit b679c79 verbatim (real bash command + real git
        stdout). One of the 14 silent failures from sprint-052's free
        session. If the bug is in command/stdout shape, this surfaces it."""
        real_command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "[free] author-time concern --files nudge\n"
            "\n"
            "Mirror xp-close-reviewer.md:127's --files discipline across the other\n"
            "concern-filing surfaces:\n"
            "\n"
            "- xp-code-reviewer.md: explicit MUST sentence after the recording\n"
            "  template (concerns naming source paths must populate --files).\n"
            "\n"
            "Backstops A2's auto-extract: explicit always beats fallback.\n"
            "\n"
            "Resolves-Event: c008a0479ecd\n"
            "EOF\n"
            ')"'
        )
        real_stdout = (
            "[paulingalls/free-2026-05-03-concern-files-earlier-catch b679c79c1c2] "
            "[free] author-time concern --files nudge\n"
            " 3 files changed, 27 insertions(+), 8 deletions(-)\n"
        )
        # Seed an open concern matching the trailer ID.
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN,
                    id="c008a0479ecd",
                    content="auto-extract concern",
                    severity="medium",
                ),
            ]
        )
        with patch_commits(
            files=[
                "plugins/xp-agents/agents/xp-code-reviewer.md",
                "plugins/xp-agents/agents/xp-system-analyzer.md",
                "plugins/xp-agents/skills/xp-accept/SKILL.md",
            ],
            body=(
                "[free] author-time concern --files nudge\n\n"
                "Resolves-Event: c008a0479ecd\n"
            ),
            head_sha="b679c79c1c2645fd0ea13bc9ada0711609d7595e",
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=real_command,
                    stdout=real_stdout,
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )

        commits = [e for e in self._read_events() if e.get("type") == EVENT_TYPE_COMMIT]
        self.assertEqual(
            len(commits),
            1,
            f"real-world b679c79 commit must record an event, got {len(commits)}",
        )
        resolves = (commits[0].get("metadata") or {}).get("resolves") or []
        self.assertIn("c008a0479ecd", resolves)

    def test_second_commit_also_resets_review_markers(self):
        """Bug 731915a2d4d2: review-cycle markers must reset after EVERY
        successful code commit, not just the first."""
        # Simulate /simplify + /xp-quality-review before commit 1.
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self._run_commit(
            head_sha="hash1111111111", body="first", files=["scripts/a.py"]
        )
        cycle1 = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle1["simplify_done"], "commit 1 must clear simplify_done")
        self.assertFalse(
            cycle1["quality_review_done"], "commit 1 must clear quality_review_done"
        )
        self.assertEqual(cycle1["last_review_commit"], "hash1111111111")

        # Simulate /simplify + /xp-quality-review again before commit 2.
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self._run_commit(
            head_sha="hash2222222222", body="second", files=["scripts/b.py"]
        )
        cycle2 = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle2["simplify_done"], "commit 2 must clear simplify_done")
        self.assertFalse(
            cycle2["quality_review_done"], "commit 2 must clear quality_review_done"
        )
        self.assertEqual(cycle2["last_review_commit"], "hash2222222222")


if __name__ == "__main__":
    unittest.main()

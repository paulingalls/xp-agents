#!/usr/bin/env python3
"""Tests for bash_post_tool post-commit lifecycle: commit recording,
review cycle, worktree agent_id, green nudge, push warning.

QR linkage warnings and canonical action events (M2 sprint-041/042)
live in test_bash_commit_qr_linkage.py.
"""

import contextlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import markers
import security
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, _ProbeTestHelpers, make_event
from event_schema import STATUS_ACTION_QR_COMPLETE


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
                "status",
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
    with `agent_type="xp-security-reviewer"` (or similar) the early-return on
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
        commit_events = [e for e in self._read_events() if e.get("type") == "commit"]
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

    def test_xp_agent_type_does_not_consume_main_security_marker(self):
        """Leaked agent_type must not consume main's security marker.

        Under the original hoist (commit 44698fe), a Bash tagged with leaked
        agent_type drove _handle_commit to completion — including
        security.consume_security_triaged(agent_id), which would wipe main's
        marker when agent_id resolved to 'main' in the leak path. The
        commit event must still land (recording is the priority), but
        marker mutations under wrong identity are unsafe.
        """
        security.write_security_triaged(self.smm_dir, "main")
        self.assertTrue(security.security_triaged_exists(self.smm_dir, "main"))

        with self._patch_commit_lookups():
            self._run_leaked_commit()

        # Commit event still recorded — the bug fix is preserved.
        commit_events = [e for e in self._read_events() if e.get("type") == "commit"]
        self.assertEqual(len(commit_events), 1)
        # Side effect blocked: security marker still present.
        self.assertTrue(
            security.security_triaged_exists(self.smm_dir, "main"),
            "leaked-type Bash should not consume main's security marker",
        )

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


class TestBashPostToolReviewCycle(_HookTestCase):
    """Tests for review cycle marker reset after commit."""

    def test_commit_resets_review_cycle(self):
        """After commit, review cycle marker has new hash and cleared flags."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "security_review_done")
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
        self.assertFalse(cycle["security_review_done"])

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
        markers.set_review_flag(self.smm_dir, "main", "security_review_done")
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
        self.assertTrue(cycle["security_review_done"])

    def test_failed_commit_preserves_security_marker(self):
        """Pre-commit hook failure must not consume the security-triaged marker."""
        security.write_security_triaged(self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))
        with patch("commits.get_head_commit_hash", return_value="prevhash"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'test'",
                    stdout="ruff-check >\n\nFAILED\npre-commit hook failed",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_empty_stdout_preserves_markers(self):
        """Content-agnostic guard: any non-success stdout short-circuits effects."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        security.write_security_triaged(self.smm_dir)
        with patch("commits.get_head_commit_hash", return_value="prevhash"):
            bash_post_tool.run(
                _make_bash_input(command="git commit -m 'test'", stdout=""),
                smm_dir=self.smm_dir,
            )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])
        self.assertTrue(security.security_triaged_exists(self.smm_dir))


class TestBashPostToolWorktreeAgentId(_HookTestCase):
    """Worktree cwd uses resolve_agent_id for commit handling."""

    def test_commit_resets_worktree_scoped_markers(self):
        """After commit, worktree-scoped markers are reset."""
        agent_id = "teammate-story-001"
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")
        markers.set_review_flag(self.smm_dir, agent_id, "security_review_done")
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
        self.assertIsNotNone(result)
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
            "concern", content="Test failures detected: 3 failed", severity="high"
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
        self.assertIsNotNone(result)
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
            [make_event("concern", content="Open issue", severity="medium")]
        )
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_push_does_not_nudge_summary(self):
        self._write_events([make_event("status", content="All done")])
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

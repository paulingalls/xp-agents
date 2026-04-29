#!/usr/bin/env python3
"""Tests for bash_post_tool post-commit behaviors: review cycle,
worktree markers, green nudge, push warning, QR linkage.

Split from test_bash.py.
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
        """Leaked agent_type must not invoke _resolve_lint_on_commit.

        Closes the 4th-of-4 side-effect coverage gap. _resolve_lint_on_commit
        runs ruff per committed file and resolves matching lint concerns; on
        the leak path this would resolve concerns under the wrong identity.
        """
        with (
            self._patch_commit_lookups(),
            patch.object(bash_post_tool, "_resolve_lint_on_commit") as lint_spy,
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


class TestBashPostToolPushWarning(_HookTestCase):
    """Tests for git push session-end checklist nudge."""

    def test_push_with_unresolved_concerns_warns(self):
        """git push with unresolved concerns returns session-end checklist."""
        self._write_events(
            [make_event("concern", content="Open issue", severity="medium")]
        )
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("concern", result.lower())

    def test_push_always_nudges_summary(self):
        """git push always nudges session summary for user."""
        self._write_events([make_event("status", content="All done")])
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("summarize", result.lower())

    def test_push_xp_agent_skips(self):
        """xp- agents skip push warning."""
        result = bash_post_tool.run(
            _make_bash_input(
                command="git push origin main",
                stdout="",
                agent_type="xp-nav",
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestQRLinkageWarning(_ProbeTestHelpers, _HookTestCase):
    """Per-commit quality-review linkage warning."""

    def _seed_commit_event(self, agent_id: str = "main") -> str:
        ev = make_event("commit", agent_id=agent_id, content="Prior commit")
        _common.append_safe(self.smm_dir, ev)
        return ev["id"]

    def _seed_qr_status(self, agent_id: str = "xp-quality-review") -> str:
        ev = make_event(
            "status",
            agent_id=agent_id,
            content="Quality review complete. No issues: [].",
            metadata={"action": STATUS_ACTION_QR_COMPLETE},
        )
        _common.append_safe(self.smm_dir, ev)
        return ev["id"]

    def _run_commit(
        self,
        agent_id: str = "main",
        committed_files: list[str] | None = None,
    ) -> str | None:
        with patch_commits(
            files=committed_files or ["src/app.py"],
            body="Fix stuff",
            head_sha="def456",
        ):
            return bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix stuff'",
                    stdout="[main def456] Fix stuff\n 1 file changed",
                    cwd=str(self.smm_dir),
                    agent_id=agent_id,
                ),
                smm_dir=self.smm_dir,
            )

    def test_qr_event_between_commits_no_warning(self):
        self._seed_commit_event()
        self._seed_qr_status()
        result = self._run_commit()
        if result:
            self.assertNotIn("quality review", result.lower())

    def test_no_qr_event_since_previous_commit_warns(self):
        self._seed_commit_event()
        result = self._run_commit()
        self.assertIsNotNone(result)
        self.assertIn("quality review", result.lower())

    def test_no_marker_no_qr_event_warns(self):
        result = self._run_commit()
        self.assertIsNotNone(result)
        self.assertIn("quality review", result.lower())

    def test_back_to_back_commits_second_warns(self):
        self._seed_commit_event()
        self._seed_qr_status()
        self._seed_commit_event()
        result = self._run_commit()
        self.assertIsNotNone(result)
        self.assertIn("quality review", result.lower())

    def test_qr_from_different_agent_still_suppresses(self):
        self._seed_commit_event()
        self._seed_qr_status(agent_id="xp-quality-review")
        result = self._run_commit()
        if result:
            self.assertNotIn("quality review", result.lower())


class TestResolutionComputationCount(_HookTestCase):
    """Verify _handle_commit computes resolutions exactly once."""

    def test_multi_file_commit_computes_resolutions_once(self):
        """Multiple committed files should not re-compute resolutions per file."""
        import resolution
        import worktree

        cwd = str(self.smm_dir)
        norm_a = worktree.normalize_path("scripts/auth.py", cwd)
        norm_b = worktree.normalize_path("scripts/routes.py", cwd)

        c1 = make_event(
            "concern",
            content=f"Lint errors in {norm_a}:\nE302",
            severity="medium",
        )
        c2 = make_event(
            "concern",
            content=f"Lint errors in {norm_b}:\nE303",
            severity="medium",
        )
        self._write_events([c1, c2])

        with (
            patch_commits(
                files=["scripts/auth.py", "scripts/routes.py"],
                body="Fix lint",
            ),
            patch("lint_check.detect_linter_config", return_value=("ruff", None)),
            patch("lint_check.run_linter", return_value=None),
            patch(
                "resolution.compute_resolutions",
                wraps=resolution.compute_resolutions,
            ) as mock_compute,
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix lint'",
                    stdout="[main abc123] Fix lint\n 2 files changed",
                    cwd=cwd,
                ),
                smm_dir=self.smm_dir,
            )
            self.assertEqual(mock_compute.call_count, 1)


class TestCheckQRLinkagePhrasings(unittest.TestCase):
    """_check_qr_linkage recognizes varied QR completion phrasings."""

    def test_qr_abbreviation_satisfies_nudge(self):
        events = [
            make_event("commit", content="prior commit", agent_id="main"),
            make_event(
                "status",
                content="QR complete. Fixed: chrome.ts",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            ),
        ]
        result = bash_post_tool._check_qr_linkage(events, "main")
        self.assertIsNone(result)


class TestM2CommitSuccessAction(_HookTestCase):
    """sprint-042 M2: type=commit events carry metadata.action=commit_success
    alongside the existing commit_hash/code_commit/code_file_count fields."""

    def test_commit_event_carries_commit_success_action(self):
        with patch_commits(files=["scripts/foo.py"], body="Add foo"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add foo'",
                    stdout="[main abc1234] Add foo\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commits = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(commits), 1)
        metadata = commits[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "commit_success")
        # Existing metadata fields stay populated.
        self.assertIn("commit_hash", metadata)
        self.assertTrue(metadata.get("code_commit"))


class TestM2LintResolvedAction(_HookTestCase):
    """sprint-042 M2: lint resolver event carries metadata.action=lint_resolved."""

    def test_lint_resolved_event_carries_action(self):
        # Seed an unresolved lint concern that matches the file we'll commit.
        from concerns import LINT_CONCERN_PREFIX

        seeded = make_event(
            "concern",
            content=f"{LINT_CONCERN_PREFIX}scripts/foo.py: 1 error (X)",
            files=["scripts/foo.py"],
        )
        _common.append_safe(self.smm_dir, seeded)

        # Force the linter to report no errors so the concern resolves.
        # Patch normalize_path to identity so the seeded relative path matches
        # the committed file path exactly (no cwd-prefixing).
        with (
            patch_commits(files=["scripts/foo.py"], body="Fix lint"),
            patch("worktree.normalize_path", side_effect=lambda p, _cwd: p),
            patch(
                "lint_check.detect_linter_config",
                return_value=("ruff", "ruff.toml"),
            ),
            patch("lint_check.run_linter", return_value=None),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix lint'",
                    stdout="[main abc1234] Fix lint\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        resolvers = [
            e
            for e in events
            if e.get("type") == "status"
            and "Lint concern resolved" in e.get("content", "")
        ]
        self.assertEqual(len(resolvers), 1)
        metadata = resolvers[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "lint_resolved")


if __name__ == "__main__":
    unittest.main()

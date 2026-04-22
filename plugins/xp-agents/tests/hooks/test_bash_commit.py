#!/usr/bin/env python3
"""Tests for bash_post_tool post-commit behaviors: probe dedup, review cycle,
worktree markers, green nudge, push warning, QR linkage.

Split from test_bash.py.
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
import markers
import security
from conftest import _HookTestCase, _make_bash_input, _ProbeTestHelpers, make_event


class TestResolvesProbeDedup(_ProbeTestHelpers, _HookTestCase):
    """REVIEW_FINGERPRINT marker suppresses post-commit nudge when matching."""

    def _run_auth_commit(self, agent_id: str = "main"):
        with (
            patch("commits.get_committed_files", return_value=["scripts/auth.py"]),
            patch("commits.get_commit_message_body", return_value="Fix auth"),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            return bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix auth'",
                    stdout="[main abc123] Fix auth\n 1 file changed",
                    cwd=str(self.smm_dir),
                    agent_id=agent_id,
                ),
                smm_dir=self.smm_dir,
            )

    def _write_fingerprint_marker(self, files: list[str], concern_ids: list[str]):
        import resolves_probe

        fp = resolves_probe.compute_fingerprint(
            files, concern_ids, cwd=str(self.smm_dir)
        )
        markers.marker_write(
            self.smm_dir,
            markers.REVIEW_FINGERPRINT,
            {"fingerprint": fp, "candidate_ids": concern_ids},
            "main",
        )
        return fp

    def test_fingerprint_match_suppresses_nudge_and_status_event(self):
        cid = self._seed_auth_concern()
        self._write_fingerprint_marker(["scripts/auth.py"], [cid])

        result = self._run_auth_commit()

        self.assertIsNone(result)
        self.assertEqual(self._probes(), [])

    def test_fingerprint_files_mismatch_emits_nudge_only(self):
        cid = self._seed_auth_concern()
        self._write_fingerprint_marker(["scripts/other.py"], [cid])

        result = self._run_auth_commit()

        self.assertIsNotNone(result)
        self.assertIn(cid, result)
        self.assertEqual(self._probes(), [])

    def test_fingerprint_concern_ids_mismatch_emits_nudge_only(self):
        cid = self._seed_auth_concern()
        self._write_fingerprint_marker(["scripts/auth.py"], ["different_id"])

        result = self._run_auth_commit()

        self.assertIsNotNone(result)
        self.assertIn(cid, result)
        self.assertEqual(self._probes(), [])

    def test_no_marker_emits_both_nudge_and_status_event(self):
        cid = self._seed_auth_concern()

        result = self._run_auth_commit()

        self.assertIsNotNone(result)
        self.assertIn(cid, result)
        self.assertEqual(len(self._probes()), 1)

    def test_marker_consumed_after_read(self):
        cid = self._seed_auth_concern()
        self._write_fingerprint_marker(["scripts/auth.py"], [cid])

        self._run_auth_commit()

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.REVIEW_FINGERPRINT, "main")
        )


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
        )
        _common.append_safe(self.smm_dir, ev)
        return ev["id"]

    def _run_commit(
        self,
        agent_id: str = "main",
        committed_files: list[str] | None = None,
    ) -> str | None:
        files = committed_files or ["src/app.py"]
        with (
            patch("commits.get_committed_files", return_value=files),
            patch("commits.get_commit_message_body", return_value="Fix stuff"),
            patch("commits.get_head_commit_hash", return_value="def456"),
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

    def _write_fingerprint_marker(
        self, files: list[str], agent_id: str = "main"
    ) -> None:
        import resolves_probe

        fp = resolves_probe.compute_fingerprint(files, [], cwd=str(self.smm_dir))
        markers.marker_write(
            self.smm_dir,
            markers.REVIEW_FINGERPRINT,
            {"fingerprint": fp, "candidate_ids": []},
            agent_id,
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

    def test_marker_match_suppresses_warning(self):
        self._seed_commit_event()
        self._write_fingerprint_marker(["src/app.py"])
        result = self._run_commit()
        if result:
            self.assertNotIn("quality review", result.lower())

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
            patch(
                "commits.get_committed_files",
                return_value=["scripts/auth.py", "scripts/routes.py"],
            ),
            patch("commits.get_commit_message_body", return_value="Fix lint"),
            patch("commits.get_head_commit_hash", return_value="abc123"),
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


if __name__ == "__main__":
    unittest.main()

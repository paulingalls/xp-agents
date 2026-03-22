#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: commit security gate, file-modification heuristic."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash
import security
from conftest import (
    _HookTestCase,
    _make_bash_input,
    make_event,
)


class TestPreToolBashNoDelta(_HookTestCase):
    """M5: Verify no delta/context injection for bash tools."""

    def test_bash_no_context_injection(self):
        """Bash (non-commit) no longer gets Active Context."""
        events = [
            make_event("goal", content="Ship v1"),
            make_event("decision", content="Use REST", topic="api-style"),
        ]
        self._write_events(events)
        result = pre_tool_bash.run(
            _make_bash_input(command="npm test"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-context", result)
            self.assertNotIn("smm-delta", result)

    def test_bash_commit_no_delta(self):
        """Bash with git commit no longer gets delta."""
        events = [make_event("decision", content="Use REST", topic="api-style")]
        self._write_events(events)
        # Write triage marker so commit isn't blocked
        security.write_security_triaged(self.smm_dir)
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'test'"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)
            self.assertNotIn("smm-context", result)


class TestPreToolBashCommitGate(_HookTestCase):
    """Tests for git commit security triage gate in pre_tool_bash.py."""

    def _commit_input(self, command: str = "git commit -m 'test'", **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": "/tmp",
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_is_git_commit_positive(self):
        """is_git_commit detects various git commit commands."""
        self.assertTrue(security.is_git_commit("git commit"))
        self.assertTrue(security.is_git_commit("git commit -m 'msg'"))
        self.assertTrue(security.is_git_commit("git commit --amend"))

    def test_is_git_commit_negative(self):
        """is_git_commit rejects non-commit commands."""
        self.assertFalse(security.is_git_commit("git push origin main"))
        self.assertFalse(security.is_git_commit("git pull"))
        self.assertFalse(security.is_git_commit("echo commit"))

    def test_is_git_commit_ignores_quoted_strings(self):
        """is_git_commit must not match 'git commit' inside quoted arguments."""
        self.assertFalse(
            security.is_git_commit('append.sh --content "before git commit"')
        )
        self.assertFalse(security.is_git_commit("echo 'git commit is great'"))
        self.assertFalse(security.is_git_commit('echo "not a git commit"'))
        # But real git commit with quoted message still matches
        self.assertTrue(security.is_git_commit('git commit -m "fix bug"'))

    def test_is_git_commit_ignores_heredocs(self):
        """is_git_commit must not match 'git commit' inside heredoc content."""
        heredoc_cmd = (
            "cat <<'SMMEOF' | python3 save_smm.py\n"
            "- Run swiftlint before git commit\n"
            "SMMEOF"
        )
        self.assertFalse(security.is_git_commit(heredoc_cmd))
        # Unquoted delimiter too
        heredoc_unquoted = "cat <<EOF | python3 save_smm.py\nbefore git commit\nEOF"
        self.assertFalse(security.is_git_commit(heredoc_unquoted))

    def test_commit_blocked_without_marker(self):
        """git commit is blocked when no triage marker exists."""
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("/xp-security-triage", str(ctx.exception))

    def test_commit_passes_with_marker(self):
        """git commit passes when triage marker exists."""
        security.write_security_triaged(self.smm_dir)
        pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)

    def test_commit_no_smm_degrades(self):
        """git commit with no SMM dir passes through (no crash)."""
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        pre_tool_bash.run(self._commit_input(), smm_dir=fake_dir)

    def test_commit_xp_agent_skips(self):
        """xp- agents skip the commit gate."""
        pre_tool_bash.run(
            self._commit_input(agent_type="xp-housekeeping"),
            smm_dir=self.smm_dir,
        )

    def test_non_commit_bash_not_affected(self):
        """Non-commit Bash commands don't trigger commit gate."""
        inp = self._commit_input(command="git status")
        pre_tool_bash.run(inp, smm_dir=self.smm_dir)

    def test_push_not_gated(self):
        """git push is NOT gated (moved to commit)."""
        inp = self._commit_input(command="git push origin main")
        # Should not raise, even without marker
        pre_tool_bash.run(inp, smm_dir=self.smm_dir)

    def test_marker_symlink_rejected(self):
        """Symlink marker is rejected — commit is blocked."""
        real_file = self.smm_dir / "real_target"
        real_file.write_text("x")
        link = security.security_triaged_path(self.smm_dir)
        link.symlink_to(real_file)
        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)


class TestCommitGateCodeFilesOnly(_HookTestCase):
    """Security triage gate only fires for commits with production code files."""

    def test_has_staged_code_files_no_git(self):
        """Non-git directory returns True (err on side of requiring triage)."""
        self.assertTrue(security.has_staged_code_files("/tmp"))

    def test_has_staged_code_files_with_add_command(self):
        """Command with git add checks unstaged files too."""
        # Can't easily test the actual git behavior in unit tests,
        # but verify the command parameter is accepted
        self.assertTrue(
            security.has_staged_code_files("/tmp", "git add . && git commit -m 'x'")
        )

    def test_has_staged_code_files_with_commit_a(self):
        """Command with git commit -am checks unstaged files too."""
        self.assertTrue(security.has_staged_code_files("/tmp", "git commit -am 'x'"))

    def test_is_code_file_classification(self):
        """is_code_file correctly classifies files."""
        self.assertTrue(security.is_code_file("src/app.ts"))
        self.assertTrue(security.is_code_file("main.py"))
        self.assertFalse(security.is_code_file("README.md"))
        self.assertFalse(security.is_code_file("package.json"))
        self.assertFalse(security.is_code_file("logo.png"))


if __name__ == "__main__":
    unittest.main()

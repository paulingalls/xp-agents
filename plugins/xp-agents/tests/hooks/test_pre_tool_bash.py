#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: commit security gate, file-modification heuristic."""

import sys
import tempfile
import unittest
from pathlib import Path

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
            "cat <<'SMMEOF' | python3 smm_cli.py\n"
            "- Run swiftlint before git commit\n"
            "SMMEOF"
        )
        self.assertFalse(security.is_git_commit(heredoc_cmd))
        # Unquoted delimiter too
        heredoc_unquoted = "cat <<EOF | python3 smm_cli.py\nbefore git commit\nEOF"
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
        """is_code_file correctly classifies code files across languages."""
        # Python
        self.assertTrue(security.is_code_file("main.py"))
        self.assertTrue(security.is_code_file("src/utils.pyi"))
        # JavaScript / TypeScript
        self.assertTrue(security.is_code_file("src/app.ts"))
        self.assertTrue(security.is_code_file("src/app.js"))
        self.assertTrue(security.is_code_file("src/App.tsx"))
        self.assertTrue(security.is_code_file("src/App.jsx"))
        # Go
        self.assertTrue(security.is_code_file("cmd/server.go"))
        # Rust
        self.assertTrue(security.is_code_file("src/main.rs"))
        # Java / Kotlin / Scala
        self.assertTrue(security.is_code_file("src/Main.java"))
        self.assertTrue(security.is_code_file("src/Main.kt"))
        self.assertTrue(security.is_code_file("src/Main.scala"))
        # Ruby
        self.assertTrue(security.is_code_file("lib/app.rb"))
        # C / C++
        self.assertTrue(security.is_code_file("src/main.c"))
        self.assertTrue(security.is_code_file("src/main.cpp"))
        self.assertTrue(security.is_code_file("include/header.h"))
        # C#
        self.assertTrue(security.is_code_file("src/Program.cs"))
        # Swift
        self.assertTrue(security.is_code_file("Sources/App.swift"))
        # PHP
        self.assertTrue(security.is_code_file("src/index.php"))
        # Dart
        self.assertTrue(security.is_code_file("lib/main.dart"))
        # Elixir
        self.assertTrue(security.is_code_file("lib/app.ex"))
        self.assertTrue(security.is_code_file("lib/app.exs"))
        # Shell
        self.assertTrue(security.is_code_file("scripts/build.sh"))

    def test_is_code_file_excludes_non_code(self):
        """is_code_file excludes docs, config, images, and lock files."""
        # Docs
        self.assertFalse(security.is_code_file("README.md"))
        self.assertFalse(security.is_code_file("docs/guide.txt"))
        self.assertFalse(security.is_code_file("docs/api.rst"))
        # Config
        self.assertFalse(security.is_code_file("package.json"))
        self.assertFalse(security.is_code_file("config.yaml"))
        self.assertFalse(security.is_code_file("pyproject.toml"))
        self.assertFalse(security.is_code_file(".gitignore"))
        self.assertFalse(security.is_code_file(".env"))
        self.assertFalse(security.is_code_file(".editorconfig"))
        self.assertFalse(security.is_code_file(".prettierignore"))
        self.assertFalse(security.is_code_file(".eslintignore"))
        # Images
        self.assertFalse(security.is_code_file("logo.png"))
        self.assertFalse(security.is_code_file("icon.svg"))
        # Lock files
        self.assertFalse(security.is_code_file("package-lock.json"))
        # Special names
        self.assertFalse(security.is_code_file("LICENSE"))
        self.assertFalse(security.is_code_file("Makefile"))
        self.assertFalse(security.is_code_file("Dockerfile"))


class TestPreToolBashReviewCycle(_HookTestCase):
    """Tests for commit-gated review cycle in pre_tool_bash.py."""

    _CODE_FILES_PATCH = "commits.get_code_files_for_review"

    def _commit_input(self, **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'test'"},
            "cwd": "/tmp",
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_above_threshold_blocks_no_simplify(self):
        """3+ code files, no flags set -> blocks for /simplify."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
            self.assertIn("/simplify", str(ctx.exception))

    def test_above_threshold_blocks_no_quality_review(self):
        """simplify_done=True -> blocks for /xp-quality-review."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
            self.assertIn("/xp-quality-review", str(ctx.exception))

    def test_above_threshold_blocks_no_security(self):
        """simplify + quality done -> blocks for /xp-security-triage."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
            self.assertIn("/xp-security-triage", str(ctx.exception))

    def test_above_threshold_passes_all_done(self):
        """All 3 flags True -> commit allowed."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        markers.set_review_flag(self.smm_dir, "main", "security_review_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)

    def test_below_threshold_blocks_without_security(self):
        """1 code file, staged code present, no security marker -> blocks."""
        with (
            patch(self._CODE_FILES_PATCH, return_value=["a.py"]),
            patch("security.has_staged_code_files", return_value=True),
        ):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
            self.assertIn("/xp-security-triage", str(ctx.exception))

    def test_below_threshold_passes_with_security(self):
        """1 code file, security marker exists -> commit allowed."""
        security.write_security_triaged(self.smm_dir)
        with (
            patch(self._CODE_FILES_PATCH, return_value=["a.py"]),
            patch("security.has_staged_code_files", return_value=True),
        ):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)

    def test_zero_code_files_passes(self):
        """No code files changed and no staged code -> commit allowed."""
        with (
            patch(self._CODE_FILES_PATCH, return_value=[]),
            patch("security.has_staged_code_files", return_value=False),
        ):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)

    def test_no_code_files_preserves_security_marker(self):
        """No-code commit should NOT consume the security marker pre-commit."""
        security.write_security_triaged(self.smm_dir)
        with (
            patch(self._CODE_FILES_PATCH, return_value=[]),
            patch("security.has_staged_code_files", return_value=False),
        ):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        # Marker should still exist — consumption belongs in bash_post_tool
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_xp_agent_skips(self):
        """xp- agents bypass the review cycle gate."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(
                self._commit_input(agent_type="xp-housekeeping"),
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
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
            # Verify the commit hash was passed to get_code_files_for_review
            self.assertEqual(mock.call_args[0][1], "abc123")


class TestTriageExemption(_HookTestCase):
    """Non-code commits auto-set triage marker with exempt_reason."""

    _CODE_FILES_PATCH = "commits.get_code_files_for_review"
    _STAGED_PATCH = "security.has_staged_code_files"

    def _commit_input(self, **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'docs update'"},
            "cwd": "/tmp",
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_no_code_files_auto_sets_marker(self):
        """Doc-only commit auto-sets triage marker with exempt_reason."""
        with (
            patch(self._CODE_FILES_PATCH, return_value=[]),
            patch(self._STAGED_PATCH, return_value=False),
        ):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))
        data = markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED)
        self.assertEqual(data["exempt_reason"], "no-code-files")

    def test_code_files_still_require_triage(self):
        """Commit with code files still requires manual triage."""
        with (
            patch(self._CODE_FILES_PATCH, return_value=[]),
            patch(self._STAGED_PATCH, return_value=True),
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)

    def test_write_security_triaged_with_exempt_reason(self):
        """write_security_triaged accepts optional exempt_reason."""
        security.write_security_triaged(self.smm_dir, exempt_reason="no-code-files")
        data = markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED)
        self.assertIn("ts", data)
        self.assertEqual(data["exempt_reason"], "no-code-files")

    def test_write_security_triaged_without_exempt_reason(self):
        """write_security_triaged without exempt_reason has no exempt_reason key."""
        security.write_security_triaged(self.smm_dir)
        data = markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED)
        self.assertIn("ts", data)
        self.assertNotIn("exempt_reason", data)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: commit security gate, file-modification heuristic."""

import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import pre_tool_bash
import security
import security_patterns  # noqa: F401 - shim import: fail loudly if module renamed
import security_scanner  # noqa: F401 - shim import: fail loudly if module renamed
from conftest import (
    _HookTestCase,
    _make_bash_input,
    _ProbeTestHelpers,
    make_event,
)
from event_schema import METADATA_KEY_PROBE_CANDIDATES
from markers import write_review_cycle


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
        """is_git_commit must not match 'git commit' inside quoted args."""
        self.assertFalse(
            security.is_git_commit('append.sh --content "before git commit"')
        )
        self.assertFalse(security.is_git_commit("echo 'git commit is great'"))
        self.assertFalse(security.is_git_commit('echo "not a git commit"'))
        # But real git commit with quoted message still matches
        self.assertTrue(security.is_git_commit('git commit -m "fix bug"'))

    def test_is_git_commit_ignores_heredocs(self):
        """is_git_commit must not match 'git commit' in heredoc content."""
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
            self._commit_input(agent_type="xp-housekeeper"),
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
        """Symlink marker is rejected -- commit is blocked."""
        real_file = self.smm_dir / "real_target"
        real_file.write_text("x")
        link = security.security_triaged_path(self.smm_dir)
        link.symlink_to(real_file)
        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)


class TestCommitGateCodeFilesOnly(_HookTestCase):
    """Security triage gate only fires for commits with code files."""

    def test_has_staged_code_files_no_git(self):
        """Non-git directory returns True (err on requiring triage)."""
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
        """is_code_file correctly classifies code files."""
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
        """is_code_file excludes docs, config, images, lock files."""
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
        data = markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED, "main")
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
        data = markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        self.assertIn("ts", data)
        self.assertEqual(data["exempt_reason"], "no-code-files")

    def test_write_security_triaged_without_exempt_reason(self):
        """write_security_triaged without exempt_reason has no key."""
        security.write_security_triaged(self.smm_dir)
        data = markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        self.assertIn("ts", data)
        self.assertNotIn("exempt_reason", data)


class TestResolvesTrailerReminder(_HookTestCase):
    """Always remind about Resolves-Event trailer on commits."""

    @patch("commits.get_staged_files", return_value=["src/app.py"])
    def test_commit_without_trailer_gets_reminder(self, _mock):
        security.write_security_triaged(self.smm_dir)
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'fix bug'"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Resolves-Event:", result)

    @patch("commits.get_staged_files", return_value=["src/app.py"])
    def test_commit_with_trailer_no_reminder(self, _mock):
        security.write_security_triaged(self.smm_dir)
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'fix bug\n\nResolves-Event: none'"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestPreToolBashPassesCommitMessage(_ProbeTestHelpers, _HookTestCase):
    """Pre-commit probe scoring uses commit_message for keyword ranking."""

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    def test_keyword_in_commit_message_ranks_matching_concern_first(self, _mock):
        cid_no_keyword = self._seed_auth_concern("zzz cleanup")
        cid_keyword = self._seed_auth_concern("tokens leak")
        security.write_security_triaged(self.smm_dir)

        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(
                _make_bash_input(command="git commit -m 'fix tokens issue'"),
                smm_dir=self.smm_dir,
            )

        probes = self._probes()
        self.assertEqual(len(probes), 1)
        candidates = probes[0]["metadata"][METADATA_KEY_PROBE_CANDIDATES]
        self.assertLess(
            candidates.index(cid_keyword),
            candidates.index(cid_no_keyword),
            "keyword-matching concern should rank higher when commit_message"
            " carries the keyword",
        )


class TestTier1SecurityScan(_HookTestCase):
    """Story-003: Tier 1 deterministic scan must run before the review-cycle gate."""

    _AKIA_DIFF = (
        "diff --git a/src/cfg.py b/src/cfg.py\n"
        "--- a/src/cfg.py\n"
        "+++ b/src/cfg.py\n"
        "@@ -1,1 +1,2 @@\n"
        " existing\n"
        '+aws_key = "AKIAIOSFODNN7EXAMPLE"\n'
    )
    _CLEAN_DIFF = (
        "diff --git a/src/cfg.py b/src/cfg.py\n"
        "--- a/src/cfg.py\n"
        "+++ b/src/cfg.py\n"
        "@@ -1,1 +1,2 @@\n"
        " existing\n"
        '+greeting = "hello"\n'
    )

    def _commit_input(self, command: str = "git commit -m 'fix'") -> dict:
        return _make_bash_input(command=command)

    def _satisfy_review_cycle(self) -> None:
        """Write all markers so the existing review-cycle gate would pass."""
        security.write_security_triaged(self.smm_dir)
        write_review_cycle(
            self.smm_dir,
            "main",
            {
                "last_review_commit": "",
                "simplify_done": True,
                "quality_review_done": True,
                "security_review_done": True,
            },
        )

    @patch("commits.get_staged_diff")
    def test_tier1_blocks_aws_key_in_staged_diff(self, mock_diff):
        """AC #1: staged AKIA literal raises BlockedError naming pattern + file:line."""
        mock_diff.return_value = self._AKIA_DIFF
        security.write_security_triaged(self.smm_dir)
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("aws-access-key", msg)
        self.assertIn("src/cfg.py", msg)

    @patch("commits.get_staged_diff")
    def test_tier1_passes_clean_diff(self, mock_diff):
        """AC #2: a clean staged diff does not raise a Tier 1 BlockedError."""
        mock_diff.return_value = self._CLEAN_DIFF
        security.write_security_triaged(self.smm_dir)
        # May still return an additional-context string (e.g. trailer reminder),
        # but must not raise BlockedError from Tier 1.
        try:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        except _common.BlockedError as e:
            self.fail(f"Clean diff should not block; got: {e}")

    @patch("commits.get_staged_diff")
    def test_tier1_skipped_for_non_commit(self, mock_diff):
        """AC #3: non-commit Bash does not invoke the Tier 1 scanner."""
        pre_tool_bash.run(
            self._commit_input(command="git status"),
            smm_dir=self.smm_dir,
        )
        mock_diff.assert_not_called()

    @patch("commits.get_staged_diff")
    def test_tier1_blocks_even_when_review_cycle_satisfied(self, mock_diff):
        """AC #4 capstone: Tier 1 fires even with all review-cycle flags green."""
        mock_diff.return_value = self._AKIA_DIFF
        self._satisfy_review_cycle()
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("aws-access-key", msg)
        self.assertIn("src/cfg.py:2", msg)

    @patch("commits.get_staged_diff")
    def test_tier1_fails_closed_on_git_failure(self, mock_diff):
        """git diff failure (None) must block, not silently bypass Tier 1."""
        mock_diff.return_value = None
        security.write_security_triaged(self.smm_dir)
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("git diff", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()

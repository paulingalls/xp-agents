#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: no-delta injection, commit-gate detection,
code-file classification, and cwd-heredoc parsing.

Split into test_pre_tool_bash_security_scan.py, test_pre_tool_bash_staged_ruff.py,
and test_pre_tool_bash_staged_lint_polyglot.py for the security-scan and
staged-lint gate classes.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import code_files
import commits
import git_commits
import pre_tool_bash
import security_patterns  # noqa: F401 - shim import: fail loudly if module renamed
import security_scanner  # noqa: F401 - shim import: fail loudly if module renamed
from conftest import (
    _HookTestCase,
    _make_bash_input,
    make_event,
)
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_GOAL


class TestPreToolBashNoDelta(_HookTestCase):
    """M5: Verify no delta/context injection for bash tools."""

    def test_bash_no_context_injection(self):
        """Bash (non-commit) no longer gets Active Context."""
        events = [
            make_event(EVENT_TYPE_GOAL, content="Ship v1"),
            make_event(EVENT_TYPE_DECISION, content="Use REST", topic="api-style"),
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
        events = [
            make_event(EVENT_TYPE_DECISION, content="Use REST", topic="api-style")
        ]
        self._write_events(events)
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'test'"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)
            self.assertNotIn("smm-context", result)


class TestPreToolBashCommitGate(_HookTestCase):
    """Tests for the is_git_commit detector in pre_tool_bash.py."""

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
        self.assertTrue(git_commits.is_git_commit("git commit"))
        self.assertTrue(git_commits.is_git_commit("git commit -m 'msg'"))
        self.assertTrue(git_commits.is_git_commit("git commit --amend"))

    def test_is_git_commit_negative(self):
        """is_git_commit rejects non-commit commands."""
        self.assertFalse(git_commits.is_git_commit("git push origin main"))
        self.assertFalse(git_commits.is_git_commit("git pull"))
        self.assertFalse(git_commits.is_git_commit("echo commit"))

    def test_is_git_commit_ignores_quoted_strings(self):
        """is_git_commit must not match 'git commit' inside quoted args."""
        self.assertFalse(
            git_commits.is_git_commit('append.sh --content "before git commit"')
        )
        self.assertFalse(git_commits.is_git_commit("echo 'git commit is great'"))
        self.assertFalse(git_commits.is_git_commit('echo "not a git commit"'))
        # But real git commit with quoted message still matches
        self.assertTrue(git_commits.is_git_commit('git commit -m "fix bug"'))

    def test_is_git_commit_ignores_heredocs(self):
        """is_git_commit must not match 'git commit' in heredoc content."""
        heredoc_cmd = (
            "cat <<'SMMEOF' | python3 smm_cli.py\n"
            "- Run swiftlint before git commit\n"
            "SMMEOF"
        )
        self.assertFalse(git_commits.is_git_commit(heredoc_cmd))
        # Unquoted delimiter too
        heredoc_unquoted = "cat <<EOF | python3 smm_cli.py\nbefore git commit\nEOF"
        self.assertFalse(git_commits.is_git_commit(heredoc_unquoted))

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


class TestIsCodeFile(_HookTestCase):
    """is_code_file classifies files for code-vs-doc routing."""

    def test_is_code_file_classification(self):
        """is_code_file correctly classifies code files."""
        # Python
        self.assertTrue(code_files.is_code_file("main.py"))
        self.assertTrue(code_files.is_code_file("src/utils.pyi"))
        # JavaScript / TypeScript
        self.assertTrue(code_files.is_code_file("src/app.ts"))
        self.assertTrue(code_files.is_code_file("src/app.js"))
        self.assertTrue(code_files.is_code_file("src/App.tsx"))
        self.assertTrue(code_files.is_code_file("src/App.jsx"))
        # Go
        self.assertTrue(code_files.is_code_file("cmd/server.go"))
        # Rust
        self.assertTrue(code_files.is_code_file("src/main.rs"))
        # Java / Kotlin / Scala
        self.assertTrue(code_files.is_code_file("src/Main.java"))
        self.assertTrue(code_files.is_code_file("src/Main.kt"))
        self.assertTrue(code_files.is_code_file("src/Main.scala"))
        # Ruby
        self.assertTrue(code_files.is_code_file("lib/app.rb"))
        # C / C++
        self.assertTrue(code_files.is_code_file("src/main.c"))
        self.assertTrue(code_files.is_code_file("src/main.cpp"))
        self.assertTrue(code_files.is_code_file("include/header.h"))
        # C#
        self.assertTrue(code_files.is_code_file("src/Program.cs"))
        # Swift
        self.assertTrue(code_files.is_code_file("Sources/App.swift"))
        # PHP
        self.assertTrue(code_files.is_code_file("src/index.php"))
        # Dart
        self.assertTrue(code_files.is_code_file("lib/main.dart"))
        # Elixir
        self.assertTrue(code_files.is_code_file("lib/app.ex"))
        self.assertTrue(code_files.is_code_file("lib/app.exs"))
        # Shell
        self.assertTrue(code_files.is_code_file("scripts/build.sh"))

    def test_is_code_file_excludes_non_code(self):
        """is_code_file excludes docs, config, images, lock files."""
        # Docs
        self.assertFalse(code_files.is_code_file("README.md"))
        self.assertFalse(code_files.is_code_file("docs/guide.txt"))
        self.assertFalse(code_files.is_code_file("docs/api.rst"))
        # Config
        self.assertFalse(code_files.is_code_file("package.json"))
        self.assertFalse(code_files.is_code_file("config.yaml"))
        self.assertFalse(code_files.is_code_file("pyproject.toml"))
        self.assertFalse(code_files.is_code_file(".gitignore"))
        self.assertFalse(code_files.is_code_file(".env"))
        self.assertFalse(code_files.is_code_file(".editorconfig"))
        self.assertFalse(code_files.is_code_file(".prettierignore"))
        self.assertFalse(code_files.is_code_file(".eslintignore"))
        # Images
        self.assertFalse(code_files.is_code_file("logo.png"))
        self.assertFalse(code_files.is_code_file("icon.svg"))
        # Lock files
        self.assertFalse(code_files.is_code_file("package-lock.json"))
        # Special names
        self.assertFalse(code_files.is_code_file("LICENSE"))
        self.assertFalse(code_files.is_code_file("Makefile"))
        self.assertFalse(code_files.is_code_file("Dockerfile"))


def _heredoc_commit(prefix: str, body: str) -> str:
    """Build `<prefix> git commit -m "$(cat <<'EOF'\\n<body>\\nEOF\\n)"`."""
    return f"{prefix} git commit -m \"$(cat <<'EOF'\n{body}\nEOF\n)\""


class TestParseEffectiveCwdHeredoc(unittest.TestCase):
    """story-014: parse_effective_cwd must skip heredoc commit-message bodies.

    A meta-commit body that quotes `cd /tmp` or `git -C /elsewhere` would
    otherwise trick the matcher into retargeting cwd, because the bare
    `is_dir()` filter accepts real paths even when they appear inside the
    message body. Tests construct realistic commit invocations using a real
    tempdir as the outer cwd target so the validator returns it.
    """

    def test_heredoc_body_cd_does_not_retarget(self):
        """AC1: `cd /tmp` inside a heredoc commit body must NOT win."""
        with tempfile.TemporaryDirectory() as outer:
            command = _heredoc_commit(
                f"cd {outer} &&",
                "Refactor: simplify foo\n\ncd /tmp && rm -rf workspace",
            )
            result = commits.parse_effective_cwd(command, fallback=outer)
            self.assertEqual(result, outer)
            self.assertNotEqual(result, "/tmp")

    def test_normal_cd_then_commit_unchanged(self):
        """AC2: happy path — `cd /path && git commit` resolves to /path."""
        with tempfile.TemporaryDirectory() as outer:
            command = f"cd {outer} && git commit -m 'fix bug'"
            result = commits.parse_effective_cwd(command, fallback="/")
            self.assertEqual(result, outer)

    def test_git_dash_c_before_heredoc_wins(self):
        """AC3: `git -C /elsewhere commit` followed by heredoc keeps -C target."""
        # The `_heredoc_commit` helper hardcodes `git commit`; AC3 needs the
        # `git -C <p> commit` shape, so build the command inline.
        with tempfile.TemporaryDirectory() as elsewhere:
            command = (
                f"git -C {elsewhere} commit -m \"$(cat <<'EOF'\n"
                "Document migration\n\ncd /tmp && do something\n"
                "EOF\n"
                ')"'
            )
            result = commits.parse_effective_cwd(command, fallback="/")
            self.assertEqual(result, elsewhere)

    def test_meta_commit_body_does_not_retarget(self):
        """AC4: meta-commit body with `cd /tmp` at line-start does not poison cwd."""
        with tempfile.TemporaryDirectory() as worktree_dir:
            command = _heredoc_commit(
                f"cd {worktree_dir} &&",
                "[story-014] Document the cd-poisoning workaround\n"
                "\n"
                "Old recipe (DO NOT USE):\n"
                "cd /tmp && git status\n"
                "Better:\n"
                "git -C /elsewhere status",
            )
            result = commits.parse_effective_cwd(command, fallback="/")
            self.assertEqual(result, worktree_dir)
            self.assertNotEqual(result, "/tmp")


if __name__ == "__main__":
    unittest.main()

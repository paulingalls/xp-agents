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
import code_files
import commits
import coordination
import git_commits
import pre_tool_bash
import security_patterns  # noqa: F401 - shim import: fail loudly if module renamed
import security_scanner  # noqa: F401 - shim import: fail loudly if module renamed
from conftest import (
    _HookTestCase,
    _make_bash_input,
    make_event,
)
from event_schema import (
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
)
from markers import write_review_cycle


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
        write_review_cycle(
            self.smm_dir,
            "main",
            {
                "last_review_commit": "",
                "simplify_done": True,
                "quality_review_done": True,
            },
        )

    @patch("commits.get_staged_diff")
    def test_tier1_blocks_aws_key_in_staged_diff(self, mock_diff):
        """AC #1: staged AKIA literal raises BlockedError naming pattern + file:line."""
        mock_diff.return_value = self._AKIA_DIFF
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("aws-access-key", msg)
        self.assertIn("src/cfg.py", msg)

    @patch("commits.get_staged_diff")
    def test_tier1_passes_clean_diff(self, mock_diff):
        """AC #2: a clean staged diff does not raise a Tier 1 BlockedError."""
        mock_diff.return_value = self._CLEAN_DIFF
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
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("git diff", str(ctx.exception).lower())


class TestStagedRuffGate(_HookTestCase):
    """Story-007: ruff F401/F811 enforcement deferred from edit-time to staging.

    pre_tool_bash invokes lint_check.run_linter_batch('ruff', staged_py_files,
    context='staging') ONCE per commit (story-020 phase 3 — was per-file
    via run_ruff). A non-empty code list raises BlockedError naming the
    offending paths/codes — the only place these codes are enforced.
    """

    _CLEAN_DIFF = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )

    def _commit_input(self) -> dict:
        return _make_bash_input(command="git commit -m 'fix\n\nResolves-Event: none'")

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_staged_py_with_F401_blocks_commit(self, mock_batch, _files, _diff):
        """A staged .py file with unused-import F401 raises BlockedError at commit."""
        mock_batch.return_value = {"src/app.py": ["F401"]}
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("F401", msg)
        self.assertIn("src/app.py", msg)
        # The block must call run_linter_batch with context="staging" (NOT edit)
        call_kwargs = mock_batch.call_args.kwargs
        self.assertEqual(call_kwargs.get("context"), "staging")
        # And it must batch — one fork covers all staged files.
        mock_batch.assert_called_once()

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_staged_py_with_F811_blocks_commit(self, mock_batch, _files, _diff):
        """A staged .py file with F811 (redefinition-of-unused) blocks at commit."""
        mock_batch.return_value = {"src/app.py": ["F811"]}
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("F811", str(ctx.exception))

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch", return_value={"src/app.py": []})
    def test_clean_staged_py_does_not_block(self, _batch, _files, _diff):
        """A staged .py file with no ruff findings does not raise BlockedError."""
        try:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        except _common.BlockedError as e:
            self.fail(f"Clean staged file should not block; got: {e}")

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["docs/README.md", "config.yml"])
    @patch("lint_check.run_linter_batch")
    def test_non_python_staged_files_skip_ruff(self, mock_batch, _files, _diff):
        """Non-.py staged files must not invoke ruff (would error on bad input)."""
        # Other gates may fire — we only assert the batch was not called
        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        mock_batch.assert_not_called()

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_non_deferred_codes_do_not_block_commit(self, mock_batch, _files, _diff):
        """E302 (non-deferred) at staging time must NOT block — that's outside
        story-007's deferral scope; non-F401/F811 codes already surface as
        concerns at edit time."""
        mock_batch.return_value = {"src/app.py": ["E302"]}
        try:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        except _common.BlockedError as e:
            self.fail(f"Non-deferred code should not block; got: {e}")

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_mixed_codes_block_only_on_deferred(self, mock_batch, _files, _diff):
        """When ruff reports F401 alongside E302, the block only names F401."""
        mock_batch.return_value = {"src/app.py": ["F401", "E302"]}
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("F401", msg)
        self.assertNotIn("E302", msg)

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/a.py", "docs/README.md"])
    @patch("lint_check.run_linter_batch", return_value={"src/a.py": []})
    def test_only_py_files_passed_to_ruff(self, mock_batch, _files, _diff):
        """When mixing .py and non-.py, only the .py paths are batched."""
        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        # Single batch invocation, .py paths only in the `paths` arg.
        mock_batch.assert_called_once()
        args, kwargs = mock_batch.call_args
        # args[0] is linter_name, args[1] is paths (or kwargs)
        paths = args[1] if len(args) > 1 else kwargs.get("paths")
        self.assertEqual(paths, ["src/a.py"])

    # --- story-007 caller-side fail-closed ---

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch", return_value={})
    def test_empty_batch_with_py_paths_fails_closed(self, _batch, _files, _diff):
        """Empty batch with non-empty py_paths must block, not silently pass."""
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception).lower()
        self.assertIn("ruff", msg)

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch(
        "commits.get_staged_files", return_value=["src/a.py", "src/b.py", "src/c.py"]
    )
    @patch("lint_check.run_linter_batch", return_value={"src/a.py": [], "src/b.py": []})
    def test_partial_batch_coverage_fails_closed(self, _batch, _files, _diff):
        """Batch returns coverage for 2 of 3 staged .py files — the missing
        path could harbor F401/F811 the gate never saw. Block, name the
        missing path so the agent can act."""
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("src/c.py", str(ctx.exception))

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["docs/README.md"])
    @patch("lint_check.run_linter_batch", return_value={})
    def test_no_py_paths_does_not_fail_closed(self, mock_batch, _files, _diff):
        """No .py files staged → no batch call, no fail-closed. The
        empty-batch sentinel only triggers when py_paths was non-empty."""
        try:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        except _common.BlockedError as e:
            self.fail(f"No-py-paths case must not block; got: {e}")
        mock_batch.assert_not_called()


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


class TestPreToolBashCoordinationConflict(_HookTestCase):
    """story-004: Bash file-modification on a coordination-claimed file must
    block (BlockedError + concern), not just warn. Closes the Advisory bypass
    where teammates could `mv`/`sed -i` over a claimed path.

    Mirrors the pre_tool_write.check_working_on_overlap pattern: same
    'CONFLICT:' message shape, same severity=high concern with the target
    file in `files`, same fail-stop on first hit.
    """

    _TARGET = "/tmp/src/foo.py"
    _OTHER_AGENT = "teammate-other"

    def _claim_target(self, agent_id: str = _OTHER_AGENT) -> None:
        coordination.update_coordination(self.smm_dir, agent_id, [self._TARGET])

    def _bash(self, command: str, **overrides) -> dict:
        return _make_bash_input(command=command, **overrides)

    def _latest_concern(self) -> dict | None:
        events_path = self.smm_dir / "events.jsonl"
        if not events_path.exists():
            return None
        for line in reversed(events_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            import json as _json

            ev = _json.loads(line)
            if ev.get("type") == _common.CONCERN:
                return ev
        return None

    def test_sed_conflict_blocks_with_concern(self):
        """AC #1: sed -i on a claimed file raises BlockedError + appends concern."""
        self._claim_target()
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(
                self._bash(f"sed -i 's/a/b/' {self._TARGET}"),
                smm_dir=self.smm_dir,
            )
        msg = str(ctx.exception)
        self.assertIn("CONFLICT", msg)
        self.assertIn(self._OTHER_AGENT, msg)
        concern = self._latest_concern()
        self.assertIsNotNone(concern, "Bash conflict must append a concern event")
        assert concern is not None  # narrow for type-checker
        self.assertEqual(concern.get("severity"), "high")
        self.assertIn(self._TARGET, concern.get("files", []))

    def test_mv_conflict_blocks_naming_target(self):
        """AC #2: mv onto a claimed file raises BlockedError naming the target."""
        self._claim_target()
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(
                self._bash(f"mv tmp {self._TARGET}"),
                smm_dir=self.smm_dir,
            )
        self.assertIn(self._TARGET, str(ctx.exception))

    def test_no_conflict_does_not_block(self):
        """Regression guard: no overlapping claim → no raise, no concern."""
        # Same-agent claim must not self-conflict.
        coordination.update_coordination(self.smm_dir, "main", [self._TARGET])
        try:
            pre_tool_bash.run(
                self._bash(f"mv tmp {self._TARGET}"),
                smm_dir=self.smm_dir,
            )
        except _common.BlockedError as e:
            self.fail(f"Same-agent claim must not conflict; got: {e}")
        self.assertIsNone(
            self._latest_concern(),
            "No concern should be appended when there is no conflict",
        )

    def test_xp_agent_skips_conflict_check(self):
        """Regression guard: xp- agents bypass conflict detection (existing
        is_xp_agent short-circuit). Pins the contract so a future refactor
        cannot accidentally subject xp- agents to teammate-coordination locks.
        """
        self._claim_target()
        # No raise expected — xp- agent_type skips the whole hook.
        pre_tool_bash.run(
            self._bash(
                f"mv tmp {self._TARGET}",
                agent_type="xp-housekeeper",
            ),
            smm_dir=self.smm_dir,
        )


if __name__ == "__main__":
    unittest.main()

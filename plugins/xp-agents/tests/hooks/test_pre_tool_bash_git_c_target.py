#!/usr/bin/env python3
"""The commit gates must fail CLOSED when the `git -C` target is unknowable.

`parse_effective_cwd` resolves a `-C` path with `is_dir()`, but a PreToolUse hook
only ever sees RAW command text. When the path hides behind a shell construct the
shell would expand (`$WT`, `${W}`, `$(cmd)`, a bare `~`), the parse silently
returns the CALLER's cwd — and every gate below then reads the wrong repo:

    tier-1 secret scan  ->  `git diff --cached` returns "" -> `if diff:` is falsy
    staged lint gate    ->  no staged files -> no groups
    review-cycle gate   ->  0 code files -> never arms
    branch guard        ->  reads the caller's branch -> false warning

Only the last one is audible, which is why this surfaced as a branch-guard
complaint (concern 6fac319bd49d) rather than as the security-gate bypass it
actually is (concern 06e323555020).

`TestTheCommitGatesReadTheRepoTheCommitLandsIn` in
test_pre_tool_bash_gates_branch_protection.py already pins the LITERAL-path
retargeting. These tests cover the form that literal path cannot reach, and which
our own close prose used to mandate: `git -C ${TEAMMATE_CWD} commit`.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from unittest.mock import patch

import _common
import pre_tool_bash
from conftest import _HookTestCase, _make_bash_input


class TestUnresolvableDashCFailsClosed(_HookTestCase):
    """A commit whose destination repo cannot be determined is refused."""

    def _run(self, command: str, cwd: str = "/tmp"):
        return pre_tool_bash.run(
            _make_bash_input(command=command, cwd=cwd), smm_dir=self.smm_dir
        )

    def _assert_blocked(self, command: str):
        with self.assertRaises(_common.BlockedError) as ctx:
            self._run(command)
        return str(ctx.exception)

    @patch("git_commits.is_git_commit", return_value=True)
    def test_quoted_variable_is_blocked(self, *_mocks):
        """The exact form xp-story-close used to mandate."""
        message = self._assert_blocked('git -C "$WT" commit -m "x"')
        self.assertIn("Cannot determine which repo", message)

    @patch("git_commits.is_git_commit", return_value=True)
    def test_braced_variable_is_blocked(self, *_mocks):
        self._assert_blocked('git -C ${TEAMMATE_CWD} commit -m "x"')

    @patch("git_commits.is_git_commit", return_value=True)
    def test_command_substitution_is_blocked(self, *_mocks):
        self._assert_blocked('git -C "$(git rev-parse --show-toplevel)" commit -m "x"')

    @patch("git_commits.is_git_commit", return_value=True)
    def test_bare_tilde_is_blocked(self, *_mocks):
        self._assert_blocked('git -C ~/wt commit -m "x"')

    @patch("git_commits.is_git_commit", return_value=True)
    def test_block_names_the_actionable_fix(self, *_mocks):
        """A refusal that doesn't say what to do instead just moves the problem."""
        message = self._assert_blocked('git -C "$WT" commit -m "x"')
        self.assertIn("literal absolute path", message)


class TestTheBlockDoesNotOverreach(_HookTestCase):
    """Fail-closed must not become fail-often: three forms stay permitted."""

    def _run(self, command: str, cwd: str):
        return pre_tool_bash.run(
            _make_bash_input(command=command, cwd=cwd), smm_dir=self.smm_dir
        )

    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("commits.get_staged_files", return_value=[])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_literal_path_still_proceeds(self, *_mocks):
        with tempfile.TemporaryDirectory() as worktree:
            self._run(f'git -C {worktree} commit -m "x"', "/tmp")

    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("commits.get_staged_files", return_value=[])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_plain_commit_still_proceeds(self, *_mocks):
        with tempfile.TemporaryDirectory() as repo:
            self._run('git commit -m "x"', repo)

    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("commits.get_staged_files", return_value=[])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_single_quoted_variable_still_proceeds(self, *_mocks):
        """Single quotes suppress expansion, so git gets a literal path and aborts
        on its own. Nothing lands, so there is nothing for us to fail closed over."""
        self._run("git -C '$WT' commit -m \"x\"", "/tmp")

    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("commits.get_staged_files", return_value=[])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_quoted_tilde_still_proceeds(self, *_mocks):
        """Quoting defeats tilde expansion — same literal-abort case."""
        self._run('git -C "~/wt" commit -m "x"', "/tmp")


class TestTheBlockPreemptsEveryDownstreamGate(_HookTestCase):
    """The block must fire BEFORE the first git read, or the gates it protects
    have already run against the wrong repo by the time it raises."""

    @patch("git_commits.is_git_commit", return_value=True)
    def test_no_gate_reads_the_callers_repo(self, *_mocks):
        reads: list[str] = []

        def _record(where, *_a, **_kw):
            reads.append(where)
            return ""

        with (
            patch("commits.get_staged_diff", side_effect=_record),
            patch("commits.get_staged_files", side_effect=_record),
            patch("commits.get_code_files_for_review", side_effect=_record),
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_bash.run(
                _make_bash_input(command='git -C "$WT" commit -m "x"', cwd="/tmp"),
                smm_dir=self.smm_dir,
            )

        self.assertEqual(
            reads, [], "a gate read the caller's repo before the block fired"
        )


class TestShippedProseNeverMandatesABlockedForm(unittest.TestCase):
    """The gate and the docs must agree.

    This story exists because `xp-story-close/SKILL.md` mandated
    `git -C ${TEAMMATE_CWD} commit` — the exact form the gate now refuses. A
    prose warning alone would regress the next time that section is edited.

    Scoped deliberately: instruction prose (`.md`) only, and only commit-shaped
    invocations. Shell files legitimately run `git -C "$VAR"` for reads
    (`skills/_preload_diff.sh` does), and comments that merely mention
    `git -C <path>` as a placeholder are not instructions.
    """

    _COMMIT_SHAPED = re.compile(
        r"git\s+-C\s+(?P<path>\S+)[^\n]*?\bgit\s+-C\s+\S+\s+(?:commit|add)\b"
        r"|git\s+-C\s+(?P<solo>\S+)\s+(?:commit|add|stash|merge|push)\b"
    )

    def test_no_shipped_md_instructs_a_variable_dash_c_commit(self):
        plugin_root = Path(__file__).parent.parent.parent
        offenders: list[str] = []

        for md in plugin_root.rglob("*.md"):
            if "/tests/" in str(md):
                continue
            for lineno, line in enumerate(
                md.read_text(encoding="utf-8").splitlines(), 1
            ):
                for m in self._COMMIT_SHAPED.finditer(line):
                    path = m.group("path") or m.group("solo") or ""
                    if "$" in path or path.lstrip("`\"'").startswith("~"):
                        rel = md.relative_to(plugin_root)
                        offenders.append(f"{rel}:{lineno}: {line.strip()}")

        self.assertEqual(
            offenders,
            [],
            "shipped prose instructs a `git -C` commit the gate will refuse; "
            "substitute the literal absolute path:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()

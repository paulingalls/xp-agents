#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: commit-time staged-lint gate (any language).

Split from test_pre_tool_bash.py -- keeps the any-language staged-lint gate
tests (linter-per-ecosystem routing) separate from the Python/ruff path.
"""

import contextlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import lint_check
import pre_tool_bash
import security_patterns  # noqa: F401 - shim import: fail loudly if module renamed
import security_scanner  # noqa: F401 - shim import: fail loudly if module renamed
from conftest import (
    _HookTestCase,
    _make_bash_input,
    _mock_ruff_result,
)


class TestStagedLintGateAnyLanguage(_HookTestCase):
    """THE STORY. The commit-time lint gate enforces in every language.

    Before this, `_staged_ruff_findings` hardcoded ruff: a TS/Rust/Go repo staged
    no `.py` files, the findings list came back empty, and the gate silently
    enforced NOTHING. The old code's `lang-ok` marker was honest that this was a
    no-op and argued the no-op was harmless — but harmlessness is not coverage.
    Every other lang-ok marker in the tree says "the other languages still work,
    via the table." That one said "the other languages get nothing."

    Now: detect the linter from the ecosystem's own config file (already
    table-driven), run it, block on what it found. A new language is a ROW in
    linters.py, never a branch here.

    These fixtures are built from scratch rather than reusing _LintTmpDirMixin,
    which seeds `ruff.toml` unconditionally — a Python config in a repo that is
    supposed to prove the gate works with NO Python in it would defeat the test.
    """

    def setUp(self):
        super().setUp()
        self.repo = Path(tempfile.mkdtemp())
        subprocess.run(
            ["git", "init", "-q"], cwd=str(self.repo), check=True, capture_output=True
        )
        self._git_root_patch = patch(
            "worktree.resolve_git_root", return_value=str(self.repo)
        )
        self._git_root_patch.start()

    def tearDown(self):
        self._git_root_patch.stop()
        shutil.rmtree(self.repo, ignore_errors=True)
        super().tearDown()

    def _seed(self, *files: str) -> None:
        """Create each path (with parents) under the fixture repo and STAGE it.

        The gate lints the index, so a seeded file only counts if it is staged.
        """
        for f in files:
            p = self.repo / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x\n")
        subprocess.run(
            ["git", "add", "-A"], cwd=str(self.repo), check=True, capture_output=True
        )

    def _commit_input(self) -> dict:
        return _make_bash_input(
            command="git commit -m 'fix\n\nResolves-Event: none'",
            cwd=str(self.repo),
        )

    @contextlib.contextmanager
    def _linter(self, *, returncode: int, output: str = "", on_path: bool = True):
        """Mock the linter subprocess. Patches lint_check's bindings — that is
        where subprocess/shutil live, and deliberately stayed."""
        with (
            patch(
                "lint_check.shutil.which",
                return_value="/usr/bin/tool" if on_path else None,
            ),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=returncode, stdout=output
            )
            yield mock_run

    def _run(self, staged: list[str]) -> str | None:
        with (
            patch("commits.get_staged_diff", return_value="diff --git a/x b/x\n"),
            patch("commits.get_staged_files", return_value=staged),
        ):
            return pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)

    # --- AC1: a non-Python project's linter blocks the commit ---

    def test_staged_ts_with_unused_import_is_blocked_by_eslint(self):
        """AC1 + AC2. The headline case. A TS repo, an unused import, no Python
        anywhere — the commit is BLOCKED, and the human sees eslint's own words.

        AC2 rides along: eslint exits 0 when only warnings fire, and
        `no-unused-vars` is `warn` in many configs. This mock exits 1 because the
        strictness column put `--max-warnings=0` on the argv (asserted below) —
        without it, this exact run would have exited 0 and read as clean.
        """
        self._seed("eslint.config.mjs", "src/app.ts")
        eslint_says = (
            "/src/app.ts\n"
            "  1:10  warning  'readFile' is defined but never used  no-unused-vars\n"
            "\n✖ 1 problem (0 errors, 1 warning)\n"
        )
        with (
            self._linter(returncode=1, output=eslint_says) as mock_run,
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            self._run(["src/app.ts"])
        msg = str(ctx.exception)
        self.assertIn("no-unused-vars", msg, "eslint's own output must reach the human")
        self.assertIn("eslint", msg.lower())
        cmd = mock_run.call_args[0][0]
        self.assertIn("eslint", cmd)
        self.assertIn("--max-warnings=0", cmd)
        self.assertNotIn("ruff", cmd)

    def test_staged_go_is_blocked_by_its_own_table_row(self):
        """AC1. Not an eslint special case — Go routes to golangci-lint off the
        same table. A new language is a row, not a branch."""
        self._seed(".golangci.yml", "cmd/server.go")
        go_says = "cmd/server.go:5:2: `io` imported and not used (typecheck)"
        with (
            self._linter(returncode=1, output=go_says) as mock_run,
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            self._run(["cmd/server.go"])
        self.assertIn("imported and not used", str(ctx.exception))
        self.assertIn("golangci-lint", mock_run.call_args[0][0])

    # --- AC5: a missing CONFIG skips; a missing BINARY fails closed ---

    def test_no_linter_config_for_the_ecosystem_skips(self):
        """AC5, first half. A Ruby file in a repo with no rubocop config: there
        is no linter to run, and a missing linter is not a finding. Skip — do not
        block, do not fork."""
        self._seed("lib/app.rb")
        with self._linter(returncode=1, output="should never run") as mock_run:
            result = self._run(["lib/app.rb"])
        mock_run.assert_not_called()
        if result:
            self.assertNotIn("blocked", result.lower())

    def test_configured_linter_with_missing_binary_fails_closed(self):
        """AC5, second half, and the distinction that must NOT be folded into
        "degrade gracefully": the ecosystem's config IS present, so the project
        declares it lints — the gate simply could not run the tool. That is a bad
        read, and the SMM constraint says gates fail CLOSED on a bad read."""
        self._seed("eslint.config.mjs", "src/app.ts")
        with (
            self._linter(returncode=0, on_path=False),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            self._run(["src/app.ts"])
        msg = str(ctx.exception).lower()
        self.assertIn("eslint", msg)

    # --- AC3: a project-scoped row degrades, it does not block ---

    def test_project_scoped_clippy_degrades_instead_of_blocking(self):
        """AC3. `cargo clippy -- -D warnings` compiles the WHOLE crate and exits
        non-zero for a pre-existing warning in a file the commit never touched.
        Blocking on that would block every commit in the repo, unfixably — you
        cannot fix it by fixing your own diff. So the gate degrades: it does not
        block, and it says why rather than going quiet."""
        self._seed("Cargo.toml", "src/main.rs")
        with self._linter(
            returncode=101, output="warning: unused import in some/other/file.rs"
        ) as mock_run:
            try:
                result = self._run(["src/main.rs"])
            except _common.BlockedError as e:
                self.fail(f"A project-scoped linter must not block the commit: {e}")
        mock_run.assert_not_called()
        assert result is not None
        self.assertIn("clippy", result.lower())

    # --- AC6: Python parity, through the same door ---

    def test_python_still_blocks_through_the_generic_path(self):
        """AC6. Python is no longer special-cased — it is one row among many. It
        must still block, or the story traded Python's enforcement for everyone
        else's."""
        self._seed("ruff.toml", "src/app.py")
        ruff_says = "src/app.py:3:5: E302 expected 2 blank lines, found 1"
        with (
            self._linter(returncode=1, output=ruff_says) as mock_run,
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            self._run(["src/app.py"])
        self.assertIn("E302", str(ctx.exception))
        self.assertIn("ruff", mock_run.call_args[0][0])

    def test_the_whole_gate_cannot_outlive_the_harness_hook_timeout(self):
        """The budget is a TOTAL across every linter group, not a per-group one.

        BATCH_TIMEOUT_CAP_S bounds ONE batch, and the reasoning behind its value
        ("40s leaves ~20s of headroom under the harness's 60s hook timeout") is
        only sound for ONE. The gate runs a batch per LINTER GROUP, and the test
        below proves two groups is a real repo shape — so two hung linters would
        burn 2 x CAP of wall clock, three would burn 3 x.

        Past the harness's hook timeout the harness KILLS the hook. A killed hook
        exits no 2, so it does not block: the commit is waved through UNLINTED.
        The bigger per-batch budget this story added — to avoid an unfixable
        block on a slow-but-honest linter — must not buy that back as a fail-OPEN
        on a hung one, which is strictly the worse direction to be wrong in.

        Here both linters burn every second they are handed.
        """
        self._seed("ruff.toml", "eslint.config.mjs", "src/app.py", "web/app.ts")
        elapsed = 0.0

        def _burn_the_whole_budget(*_args, **kwargs):
            nonlocal elapsed
            elapsed += float(kwargs["timeout"])
            return _mock_ruff_result(returncode=0)

        with (
            patch("staged_lint.time.monotonic", side_effect=lambda: elapsed),
            patch("lint_check.shutil.which", return_value="/usr/bin/tool"),
            patch("lint_check.subprocess.run", side_effect=_burn_the_whole_budget),
            contextlib.suppress(_common.BlockedError),
        ):
            self._run(["src/app.py", "web/app.ts"])

        self.assertLessEqual(
            elapsed,
            lint_check.BATCH_TIMEOUT_CAP_S,
            "linter groups must SHARE one budget, not each get a full one — a "
            "gate that outlives the harness hook timeout fails OPEN",
        )

    def test_an_exhausted_budget_fails_closed_rather_than_skipping_the_linter(self):
        """And when the budget IS spent, the groups that never ran are a bad
        read, not a pass. Running out of time is exactly the state where the
        temptation to shrug is strongest and the cost is highest: the unlinted
        file ships. Block, and say the budget ran out."""
        self._seed("ruff.toml", "eslint.config.mjs", "src/app.py", "web/app.ts")

        def _burn_the_whole_budget(*_args, **kwargs):
            return _mock_ruff_result(returncode=0)

        # The clock jumps past the deadline the moment the first group returns.
        clock = iter([0.0, 0.0, 999.0, 999.0, 999.0])
        with (
            patch("staged_lint.time.monotonic", side_effect=lambda: next(clock)),
            patch("lint_check.shutil.which", return_value="/usr/bin/tool"),
            patch("lint_check.subprocess.run", side_effect=_burn_the_whole_budget),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            self._run(["src/app.py", "web/app.ts"])
        msg = str(ctx.exception).lower()
        self.assertIn("budget", msg)
        self.assertIn("ruff", msg, "the linter that never got to run must be named")

    def test_a_config_style_flag_the_tool_rejects_does_not_block_the_commit(self):
        """THE gate-level outcome, not just the runner's: a flag WE composed must
        never be what blocks a commit.

        The gate ships eslint `--no-warn-ignored` for flat config, and that option
        landed in 8.51 while flat config is recognized from 8.21 — so every project
        in that window is handed an option its binary rejects: non-zero WITH output,
        which the gate reads as findings. The committer sees a block naming a flag
        they never wrote and cannot fix from their diff.
        """
        self._seed("eslint.config.mjs", "web/app.ts")

        def _reject_the_composed_flag(*args, **kwargs):
            if "--no-warn-ignored" in args[0]:
                return _mock_ruff_result(
                    returncode=2, stdout="Invalid option '--warn-ignored'"
                )
            return _mock_ruff_result(returncode=0)

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/tool"),
            patch("lint_check.subprocess.run", side_effect=_reject_the_composed_flag),
        ):
            # No BlockedError: the retry without the optional flag ran clean.
            self._run(["web/app.ts"])

    def test_an_optional_flag_retry_stays_inside_the_shared_budget(self):
        """The retry is a SECOND process, and it spends the same wall clock.

        `optional_flag_retry` re-runs a batch whose flag the tool rejected. That
        recovery must not buy back the fail-OPEN the budget above exists to
        prevent: hand the retry a fresh full timeout and one linter group can
        burn 2 x its slice, which is the same N-fold breach — just with N=2 and
        no second linter needed.

        Here eslint burns every second it is handed and then answers with its
        usage-error code, so the retry fires on a budget that is already spent.
        """
        self._seed("eslint.config.mjs", "web/app.ts")
        elapsed = 0.0

        def _burn_the_whole_budget(*args, **kwargs):
            nonlocal elapsed
            elapsed += float(kwargs["timeout"])
            rejected = "--no-warn-ignored" in args[0]
            return _mock_ruff_result(
                returncode=2 if rejected else 0,
                stdout="Invalid option '--warn-ignored'" if rejected else "",
            )

        with (
            patch("staged_lint.time.monotonic", side_effect=lambda: elapsed),
            patch("lint_check.shutil.which", return_value="/usr/bin/tool"),
            patch("lint_check.subprocess.run", side_effect=_burn_the_whole_budget),
            contextlib.suppress(_common.BlockedError),
        ):
            self._run(["web/app.ts"])

        self.assertLessEqual(
            elapsed,
            lint_check.BATCH_TIMEOUT_CAP_S,
            "a retry must come out of the batch's own budget, not double it — a "
            "gate that outlives the harness hook timeout fails OPEN",
        )

    def test_a_polyglot_repo_routes_each_file_to_its_own_linter(self):
        """A monorepo with Python AND TypeScript: each staged file reaches the
        linter that claims it. One fork per linter, not one per file."""
        self._seed("ruff.toml", "eslint.config.mjs", "src/app.py", "web/app.ts")
        with self._linter(returncode=0) as mock_run:
            self._run(["src/app.py", "web/app.ts"])
        invoked = [c[0][0][0] for c in mock_run.call_args_list]
        self.assertIn("ruff", invoked)
        self.assertIn("npx", invoked)  # eslint runs via npx
        self.assertEqual(len(invoked), 2, "one fork per linter")


if __name__ == "__main__":
    unittest.main()

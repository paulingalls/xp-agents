#!/usr/bin/env python3
"""Tests for lint detection, concern content, and output summarization.

Split from test_lint.py to keep files under the 500-line target.
"""

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
import linters
from concerns import TEST_CONCERN_RE
from conftest import (
    _HookTestCase,
    _LintTmpDirMixin,
    _make_write_input,
    _mock_ruff_result,
)

_WATERMARK_ID = "test-lint-detection"


class TestDetectLinterConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_detects_ruff_config(self):
        (self.tmpdir / "ruff.toml").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        assert result is not None
        self.assertEqual(result[0], "ruff")

    def test_detects_eslint_config(self):
        (self.tmpdir / ".eslintrc.json").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        assert result is not None
        self.assertEqual(result[0], "eslint")

    def test_detects_pyproject_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        assert result is not None
        self.assertEqual(result[0], "ruff")

    def test_no_config_returns_none(self):
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNone(result)


class TestLintConcernContent(_LintTmpDirMixin, _HookTestCase):
    """Lint concern events should be concise summaries, not full ruff output."""

    def test_lint_concern_is_summary_not_full_output(self):
        """Concern content should have file + error codes, not full ruff output."""
        target = self._lint_tmpdir / "app.py"
        target.write_text("def f():\n    pass\n")
        # Use E302 (non-deferred) — story-007 defers F401/F811 to staging,
        # so F401 alone produces no concern at edit time. This test exercises
        # the summary-vs-full-output contract, not F401 specifically.
        full_output = (
            "app.py:1:1: E302 expected 2 blank lines, found 0\n"
            " --> app.py:1:1\n"
            "  |\n"
            "1 | def f():\n"
            "  | ^^^\n"
            "help: Add blank lines\n"
            "\n"
            "Found 1 error.\n"
        )
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
            patch("lint_check.detect_linter_config", return_value=("ruff", "")),
        ):
            mock_run.return_value = _mock_ruff_result(returncode=1, stdout=full_output)
            lint_check.run(
                _make_write_input(
                    tool_input={"file_path": str(target), "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        content = concerns[0]["content"]
        self.assertIn("app.py", content)
        self.assertNotIn("-->", content)
        self.assertNotIn("help:", content)
        self.assertIn("E302", content)


class TestSummarizeLintOutput(unittest.TestCase):
    """Unit tests for _summarize_lint_output across linter formats."""

    def test_ruff_codes(self):
        output = "F401 `os` imported but unused\nI001 unsorted imports\n"
        result = lint_check._summarize_lint_output(output)
        self.assertIn("F401", result)
        self.assertIn("I001", result)
        self.assertIn("2 errors", result)

    def test_eslint_rules(self):
        output = (
            "  1:10  error  'foo' is unused  no-unused-vars\n"
            "  3:1   warning  Unexpected console  no-console\n"
        )
        result = lint_check._summarize_lint_output(output)
        self.assertIn("no-unused-vars", result)
        self.assertIn("no-console", result)

    def test_eslint_scoped_plugin_rules(self):
        output = "  5:1  error  Unexpected any  @typescript-eslint/no-explicit-any\n"
        result = lint_check._summarize_lint_output(output)
        self.assertIn("@typescript-eslint/no-explicit-any", result)

    def test_eslint_compact_format(self):
        output = "/file.js: line 1, col 10, Error - unused. (no-unused-vars)\n"
        result = lint_check._summarize_lint_output(output)
        self.assertIn("no-unused-vars", result)

    def test_no_codes_fallback(self):
        result = lint_check._summarize_lint_output("Something went wrong")
        self.assertEqual(result, "errors found")

    def test_deduplicates_codes(self):
        output = "F401 unused\nF401 unused again\nF401 third time\n"
        result = lint_check._summarize_lint_output(output)
        self.assertIn("3 errors", result)
        self.assertEqual(result.count("F401"), 1)

    def test_caps_at_5_codes(self):
        output = "\n".join(f"E{i:03d} error" for i in range(100, 108))
        result = lint_check._summarize_lint_output(output)
        self.assertIn("+3 more", result)

    def test_4plus_letter_ruff_prefixes(self):
        """Code-reuse simplify finding: _summarize_lint_output had the same
        [A-Z]{1,3}\\d{3,4} bug as run_ruff (concern 56a0e138ef8e). 4+ letter
        ruff plugin prefixes (PERF, FURB, FAST, ASYNC) were silently dropped
        from the summary the user sees, even when run_ruff parsed them
        correctly."""
        output = (
            "PERF401 use list comprehension\n"
            "FURB169 use isinstance not type comparison\n"
            "ASYNC100 unnecessary trio.fail_after\n"
        )
        result = lint_check._summarize_lint_output(output)
        self.assertIn("PERF401", result)
        self.assertIn("FURB169", result)
        self.assertIn("ASYNC100", result)
        self.assertIn("3 errors", result)


class TestLinterTableColumns(unittest.TestCase):
    """The two columns that make "non-zero exit" a sufficient finding signal.

    The gate reads only the exit code (see run_linter_batch). That is sound ONLY
    if two things hold per linter, and out of the box neither does:

    (a) STRICTNESS — some linters exit 0 even when they found something. eslint
        exits 0 when only *warnings* fire, and `no-unused-vars` is `warn` in many
        popular configs — so the headline case of this whole story (a staged .ts
        with an unused import) would sail straight through the gate. swiftlint
        and `dart analyze` share the shape.

    (b) FILE SCOPE — some linters cannot lint a single file at all. `cargo clippy
        -- -D warnings` lints the whole crate and exits non-zero if ANY warning
        exists anywhere, staged or not. A Rust repo with one pre-existing warning
        in an untouched file would have every commit blocked, unfixably.

    Both are per-row DATA, not branches: a flag column and a capability column.
    Note what they are NOT — a map of per-language rule codes
    ({eslint: no-unused-vars, clippy: unused_imports}). That would be a hardcoded
    model of each language's rule semantics, the exact leak the guardrail forbids,
    and test_no_language_leak.py could not see it (it only scans extension
    predicates). A strictness flag says "be strict"; it does not say what strict
    means in that language. The linter decides that.
    """

    def test_eslint_carries_a_strictness_flag(self):
        """Without --max-warnings=0, eslint exits 0 on a warn-level finding and
        the gate reads a repo full of unused imports as clean."""
        self.assertIn("--max-warnings=0", linters.linter_command("eslint"))

    def test_swiftlint_and_dart_carry_strictness_flags(self):
        self.assertIn("--strict", linters.linter_command("swiftlint"))
        self.assertIn("--fatal-infos", linters.linter_command("dart-analyze"))

    def test_ruff_needs_no_strictness_flag(self):
        """ruff already exits non-zero on any finding. A row only carries a flag
        when its linter would otherwise lie about having found nothing."""
        self.assertEqual(
            linters.linter_command("ruff"),
            ["ruff", "check", "--output-format=concise"],
        )

    def test_strictness_flag_reaches_the_commit_gate_argv(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("eslint", ["src/a.ts"], cwd="/tmp")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--max-warnings=0", cmd)
        # ...and before the `--` separator, or eslint reads it as a filename.
        self.assertLess(cmd.index("--max-warnings=0"), cmd.index("--"))

    def test_strictness_flag_reaches_edit_time_argv(self):
        """The command table is SHARED with the edit-time run_linter path. The
        flag applies there too, on purpose: if the gate blocks at commit on a
        warn-level finding that edit-time never mentioned, the agent gets
        ambushed by a rule it was never told about."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter("eslint", "src/a.ts")
        self.assertIn("--max-warnings=0", mock_run.call_args[0][0])

    def test_edit_time_run_linter_still_reports_findings(self):
        """Pin against regression: the shared-table change must not disturb
        edit-time's contract (output on non-zero, None on clean)."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1, stdout="  1:10  warning  'foo' is unused  no-unused-vars"
            )
            found = lint_check.run_linter("eslint", "src/a.ts")
            mock_run.return_value = _mock_ruff_result()
            clean = lint_check.run_linter("eslint", "src/a.ts")
        assert found is not None
        self.assertIn("no-unused-vars", found)
        self.assertIsNone(clean)

    def test_project_scoped_rows_are_not_file_scoped(self):
        """These lint the whole project and exit non-zero on state that has
        nothing to do with the staged files. The gate must DEGRADE on them, not
        block — a pre-existing warning in an untouched file is not something the
        committing agent can fix by fixing its own diff."""
        for linter in ("clippy", "checkstyle", "detekt", "credo", "dotnet-format"):
            self.assertFalse(
                linters.is_file_scoped(linter),
                msg=f"{linter} lints the whole project — it cannot judge one file",
            )

    def test_file_scoped_rows_can_judge_one_file(self):
        for linter in ("ruff", "flake8", "eslint", "golangci-lint", "rubocop"):
            self.assertTrue(linters.is_file_scoped(linter))

    def test_every_row_has_a_scope_answer(self):
        """No silent gap: a new linter row must be classified, not defaulted by
        accident. is_file_scoped answers for every command row there is."""
        for linter in linters.LINTER_COMMANDS:
            self.assertIsInstance(linters.is_file_scoped(linter), bool)


class TestRunLinterBatchScaledTimeout(unittest.TestCase):
    """run_linter_batch timeout scales with len(eligible) per story-007.

    Formula: ``min(CAP, BATCH_BASE + PER_PATH * N)`` — small batches get one
    base interval, large batches stay bounded by CAP so a hung linter can't
    stall the commit gate forever. The empty-on-timeout sentinel contract is
    pinned by test_lint.TestRunLinterBatch.
    """

    def _captured_timeout(self, n_paths: int) -> float:
        paths = [f"f{i}.py" for i in range(n_paths)]
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", paths, cwd="/tmp")
        return float(mock_run.call_args.kwargs["timeout"])

    def _expected(self, n: int) -> float:
        return min(
            lint_check.BATCH_TIMEOUT_CAP_S,
            lint_check.BATCH_TIMEOUT_BASE_S + lint_check.BATCH_TIMEOUT_PER_PATH_S * n,
        )

    def test_batch_budget_is_not_the_edit_time_budget(self):
        """The batch budget must be materially larger than the edit-time one,
        because the two have OPPOSITE failure semantics.

        An edit-time timeout returns None: no nudge, nobody blocked. A batch
        timeout is `unverified`, and the commit gate fails CLOSED on it — it
        BLOCKS. Sharing one 5s number was safe only while the batch ran ruff and
        nothing else; the gate now dispatches per the linter table, so the batch
        runs `npx eslint`, `golangci-lint run`, `dart analyze` — tools whose cold
        start alone (npx bin resolution, a TS program build, package type-check)
        routinely exceeds 5s on a real repo.

        A timeout is also the ONE unverified cause the agent cannot act on: it
        cannot make golangci-lint faster. Too small a budget therefore blocks
        every commit in that ecosystem, unfixably — the exact failure the
        project-scoped DEGRADE row exists to avoid, arriving through a different
        door. Budget for a real linter; the CAP still bounds a hung one.
        """
        self.assertGreater(
            lint_check.BATCH_TIMEOUT_BASE_S,
            lint_check.LINTER_BASE_TIMEOUT_S,
            "commit-gate batch budget must not inherit the edit-time per-file one",
        )
        self.assertGreaterEqual(
            self._captured_timeout(1),
            30.0,
            "a one-file commit must budget for a real linter's cold start",
        )

    def test_batch_cap_stays_inside_the_harness_hook_budget(self):
        """And the budget has a CEILING, for the opposite reason.

        The gate only blocks because the hook exits 2. A hook the HARNESS kills
        for overrunning its own timeout (60s default; pre_tool_bash registers no
        override) exits no such thing — so a batch that outlives the harness does
        not fail closed, it fails OPEN, and the commit sails through unlinted.
        That is strictly worse than the block the larger budget exists to avoid.

        So the CAP is bounded on BOTH sides, and this is the side you cannot see
        in a test of the linter alone. Leave headroom for the rest of the hook
        (tier-1 diff scan, git forks, SMM loads). Raising the CAP past this means
        raising the hook's registered timeout FIRST.
        """
        self.assertLessEqual(
            lint_check.BATCH_TIMEOUT_CAP_S,
            45.0,
            "a batch that outlives the harness hook timeout fails OPEN, not closed",
        )

    def test_n1_below_cap(self):
        self.assertAlmostEqual(self._captured_timeout(1), self._expected(1), places=6)

    def test_n20_below_cap(self):
        self.assertAlmostEqual(self._captured_timeout(20), self._expected(20), places=6)

    def test_at_cap_boundary(self):
        # N=100 with default constants saturates the min() to the literal cap.
        self.assertEqual(self._captured_timeout(100), lint_check.BATCH_TIMEOUT_CAP_S)

    def test_above_cap_clamped(self):
        self.assertEqual(self._captured_timeout(500), lint_check.BATCH_TIMEOUT_CAP_S)

    def test_uses_eligible_not_input_count(self):
        """Non-.py paths are filtered out before scaling — the timeout
        sizes against what ruff actually sees, not the raw input list."""
        paths = ["a.py"] + [f"x{i}.md" for i in range(19)]
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", paths, cwd="/tmp")
        self.assertAlmostEqual(
            float(mock_run.call_args.kwargs["timeout"]),
            self._expected(1),
            places=6,
        )


import bash_failure  # noqa: E402
from event_helpers import events_of_type  # noqa: E402
from event_schema import EVENT_TYPE_CONCERN  # noqa: E402


class TestBashFailureConcernContent(_HookTestCase):
    """Test failure concern events should be concise, not full pytest output."""

    def test_test_failure_concern_is_summary(self):
        """Concern should identify test file, not dump full traceback."""
        bash_failure.run(
            {
                "session_id": "t",
                "tool_input": {
                    "command": "cd /foo && uv run pytest tests/test_bar.py -v"
                },
                "error": (
                    "Exit code 1\n"
                    "===== test session starts =====\n"
                    "FAILED tests/test_bar.py::test_thing - AssertionError\n"
                    "===== 1 failed, 2 passed =====\n"
                ),
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        content = concerns[0]["content"]
        # The gate reads concerns through TEST_CONCERN_RE, so that — not any
        # one prefix — is the contract. This command is compound, and its
        # payload corroborates real counts, so the concern reports those
        # ("Test failures detected: 1 failed") rather than a bare exit code.
        self.assertRegex(content, TEST_CONCERN_RE)
        self.assertNotIn("test session starts", content)
        self.assertLess(len(content), 200)


if __name__ == "__main__":
    unittest.main()

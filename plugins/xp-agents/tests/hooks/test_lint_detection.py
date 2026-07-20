#!/usr/bin/env python3
"""Tests for lint detection, concern content, and output summarization.

Split from test_lint.py to keep files under the 500-line target.

Further split across sibling modules to stay under the cap:
  - test_lint_detection_linter_table.py — the strictness/file-scope registry
    columns that make "non-zero exit" a sufficient finding signal
  - test_lint_detection_batch_timeout.py — run_linter_batch's scaled timeout
    and the bash-failure concern content
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
from conftest import (
    _HookTestCase,
    _LintTmpDirMixin,
    _make_write_input,
    _mock_ruff_result,
)
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN

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


if __name__ == "__main__":
    unittest.main()

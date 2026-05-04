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
from conftest import _HookTestCase, _make_write_input


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


class TestLintConcernContent(_HookTestCase):
    """Lint concern events should be concise summaries, not full ruff output."""

    def test_lint_concern_is_summary_not_full_output(self):
        """Concern content should have file + error codes, not full ruff output."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        target = tmpdir / "app.py"
        target.write_text("import os\n")
        full_output = (
            "F401 [*] `os` imported but unused\n"
            " --> app.py:1:8\n"
            "  |\n"
            "1 | import os\n"
            "  |        ^^\n"
            "help: Remove unused import\n"
            "\n"
            "Found 1 error.\n"
        )
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
                patch("lint_check.detect_linter_config", return_value=("ruff", "")),
            ):
                mock_run.return_value = type(
                    "R",
                    (),
                    {"returncode": 1, "stdout": full_output, "stderr": ""},
                )()
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": str(target), "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
            self.assertEqual(len(concerns), 1)
            content = concerns[0]["content"]
            self.assertIn("app.py", content)
            self.assertNotIn("-->", content)
            self.assertNotIn("help:", content)
            self.assertIn("F401", content)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)


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


import bash_failure  # noqa: E402
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
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
        self.assertEqual(len(concerns), 1)
        content = concerns[0]["content"]
        self.assertIn("Test command failed", content)
        self.assertNotIn("test session starts", content)
        self.assertLess(len(content), 200)


if __name__ == "__main__":
    unittest.main()

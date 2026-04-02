#!/usr/bin/env python3
"""Tests for lint_check.py hook.

Split from the original test_post_tool.py.
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

# ===========================================================================
# lint_check.py tests — Milestone 3.3
# ===========================================================================


class TestDetectLinterConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_detects_ruff_config(self):
        (self.tmpdir / "ruff.toml").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ruff")

    def test_detects_eslint_config(self):
        (self.tmpdir / ".eslintrc.json").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "eslint")

    def test_detects_pyproject_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ruff")

    def test_no_config_returns_none(self):
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNone(result)


class TestLintCheck(_HookTestCase):
    def test_no_config_skips_non_code_files(self):
        """Non-code files (md, txt, yml, etc.) should not trigger linter nudge."""
        for filename in ("README.md", "notes.txt", "config.yml", ".gitignore"):
            # Reset flag each iteration
            (self.smm_dir / ".lint-warned").unlink(missing_ok=True)
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": filename, "content": "x"},
                ),
                smm_dir=self.smm_dir,
            )
            self.assertIsNone(result, f"Should not nudge for {filename}")
            self.assertFalse(
                (self.smm_dir / ".lint-warned").exists(),
                f"Should not create .lint-warned for {filename}",
            )

    def test_no_config_nudges_for_code_files(self):
        """Code files should trigger linter nudge."""
        for filename in ("app.py", "index.js", "main.go", "lib.rs"):
            (self.smm_dir / ".lint-warned").unlink(missing_ok=True)
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": filename, "content": "x"},
                ),
                smm_dir=self.smm_dir,
            )
            self.assertIsNotNone(result, f"Should nudge for {filename}")

    def test_no_config_nudges_once(self):
        result = lint_check.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        # Should return a nudge string, not write a question event
        self.assertIsNotNone(result)
        self.assertIn("linter", result.lower())
        # No question events written
        events = _common.read_events_raw(self.smm_dir)
        questions = [e for e in events if e.get("type") == "question"]
        self.assertEqual(len(questions), 0)
        # Flag file should exist
        self.assertTrue((self.smm_dir / ".lint-warned").exists())

    def test_no_config_second_time_silent(self):
        (self.smm_dir / ".lint-warned").touch()
        result = lint_check.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        events = _common.read_events_raw(self.smm_dir)
        questions = [e for e in events if e.get("type") == "question"]
        self.assertEqual(len(questions), 0)

    def test_linter_binary_missing(self):
        # Create a ruff.toml in a temp dir but ruff isn't on PATH
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with patch("lint_check.shutil.which", return_value=None):
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_clean_lint_no_event(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
                )()
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_errors_appends_concern(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R",
                    (),
                    {
                        "returncode": 1,
                        "stdout": "src/app.py:1:1: E302 expected 2 blank lines",
                        "stderr": "",
                    },
                )()
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 1)
            self.assertEqual(concerns[0].get("severity"), "medium")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_timeout(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.run_linter", return_value=None),
            ):
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_xp_agent_skips(self):
        lint_check.run(
            _make_write_input(agent_type="xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        lint_check.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )

    def test_ruff_skips_json_file(self):
        """ruff should not run against .json files — they are not Python."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with patch("lint_check.shutil.which", return_value="/usr/bin/ruff"):
                result = lint_check.run_linter("ruff", str(tmpdir / "hooks.json"))
            self.assertIsNone(result)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_ruff_runs_on_python_file(self):
        """ruff should still run on .py files."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
                )()
                result = lint_check.run_linter("ruff", str(tmpdir / "app.py"))
            self.assertIsNone(result)  # clean — no errors
            mock_run.assert_called_once()
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_run_linter_passes_cwd(self):
        """run_linter should pass cwd to subprocess so relative paths resolve."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
            )()
            lint_check.run_linter("ruff", "src/app.py", cwd="/projects/myapp")
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("cwd"), "/projects/myapp")

    def test_detect_skips_linter_for_wrong_extension(self):
        """detect_linter_config should skip eslint for .py files."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "eslint.config.js").touch()
        (tmpdir / "ruff.toml").touch()
        try:
            result = lint_check.detect_linter_config(
                str(tmpdir), str(tmpdir), file_path="src/app.py"
            )
            self.assertIsNotNone(result)
            self.assertEqual(result[0], "ruff")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_detect_returns_eslint_for_js_files(self):
        """detect_linter_config should return eslint for .js files."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "eslint.config.js").touch()
        (tmpdir / "ruff.toml").touch()
        try:
            result = lint_check.detect_linter_config(
                str(tmpdir), str(tmpdir), file_path="src/app.js"
            )
            self.assertIsNotNone(result)
            self.assertEqual(result[0], "eslint")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_detect_walks_from_file_directory(self):
        """detect_linter_config should start from the file's dir, not cwd."""
        tmpdir = Path(tempfile.mkdtemp())
        # eslint at root, ruff in subdirectory
        (tmpdir / "eslint.config.js").touch()
        subdir = tmpdir / "apps" / "agent"
        subdir.mkdir(parents=True)
        pyproject = subdir / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\ntarget-version = 'py311'\n")
        try:
            # File is in apps/agent/ — should find ruff there, not eslint at root
            result = lint_check.detect_linter_config(
                str(tmpdir), str(tmpdir), file_path="apps/agent/foo.py"
            )
            self.assertIsNotNone(result)
            self.assertEqual(result[0], "ruff")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_errors_return_context(self):
        """Lint errors should return additionalContext string."""
        (self.smm_dir / ".lint-warned").touch()  # suppress no-config warning
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        target = tmpdir / "app.py"
        target.write_text("import os\n")
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
                patch("lint_check.detect_linter_config", return_value=("ruff", "")),
            ):
                mock_run.return_value = type(
                    "R",
                    (),
                    {"returncode": 1, "stdout": "unused import", "stderr": ""},
                )()
                result = lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": str(target), "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            self.assertIsNotNone(result)
            self.assertIn("Lint errors", result)
            self.assertIn("unused import", result)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_clean_lint_returns_none(self):
        """Clean lint should return None (no additionalContext)."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        target = tmpdir / "app.py"
        target.write_text("x = 1\n")
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
                patch("lint_check.detect_linter_config", return_value=("ruff", "")),
            ):
                mock_run.return_value = type(
                    "R",
                    (),
                    {"returncode": 0, "stdout": "", "stderr": ""},
                )()
                result = lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": str(target), "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            self.assertIsNone(result)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)


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
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 1)
            content = concerns[0]["content"]
            # Should have the file path (for matching)
            self.assertIn("app.py", content)
            # Should NOT have the full ruff context (arrows, help text)
            self.assertNotIn("-->", content)
            self.assertNotIn("help:", content)
            # Should mention the error code
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
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        content = concerns[0]["content"]
        # Should still match TEST_CONCERN_RE for resolution
        self.assertIn("Test command failed", content)
        # Should NOT contain the full pytest output
        self.assertNotIn("test session starts", content)
        # Should be short
        self.assertLess(len(content), 200)


if __name__ == "__main__":
    unittest.main()

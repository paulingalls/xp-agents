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
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_QUESTION

# ===========================================================================
# lint_check.py tests — Milestone 3.3
# ===========================================================================


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
        assert result is not None
        self.assertIn("linter", result.lower())
        # No question events written
        events = _common.read_events_raw(self.smm_dir)
        questions = events_of_type(events, EVENT_TYPE_QUESTION)
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
        questions = events_of_type(events, EVENT_TYPE_QUESTION)
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
            concerns = events_of_type(events, EVENT_TYPE_CONCERN)
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
            concerns = events_of_type(events, EVENT_TYPE_CONCERN)
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
            concerns = events_of_type(events, EVENT_TYPE_CONCERN)
            self.assertEqual(len(concerns), 1)
            self.assertEqual(concerns[0].get("severity"), "medium")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_concern_not_duplicated(self):
        """Second lint run for same file should not append duplicate concern."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            mock_result = type(
                "R",
                (),
                {
                    "returncode": 1,
                    "stdout": "src/app.py:1:1: E302 expected 2 blank lines",
                    "stderr": "",
                },
            )()
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run", return_value=mock_result),
            ):
                inp = _make_write_input(
                    tool_input={"file_path": "src/app.py", "content": "x"},
                    cwd=str(tmpdir),
                )
                lint_check.run(inp, smm_dir=self.smm_dir)
                lint_check.run(inp, smm_dir=self.smm_dir)
            events = _common.read_events_raw(self.smm_dir)
            concerns = events_of_type(events, EVENT_TYPE_CONCERN)
            self.assertEqual(len(concerns), 1, "Duplicate lint concern appended")
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
            concerns = events_of_type(events, EVENT_TYPE_CONCERN)
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_xp_agent_skips(self):
        lint_check.run(
            _make_write_input(agent_type="xp-housekeeper"),
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
            assert result is not None
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
            assert result is not None
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
            assert result is not None
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
                    {
                        "returncode": 1,
                        "stdout": "app.py:1:1: F841 unused variable",
                        "stderr": "",
                    },
                )()
                result = lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": str(target), "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            assert result is not None
            self.assertIn("Lint errors", result)
            self.assertIn("F841", result)
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


# ===========================================================================
# Story-007: ruff F401/F811 deferred from edit-time to staging-time
# ===========================================================================


class TestRunRuffContext(_HookTestCase):
    """run_ruff is the single source of truth for ruff invocation.

    'edit' context drops F401/F811 (defer to staging — they false-positive
    mid-edit during multi-step replace_all migrations); 'staging' preserves
    them so the commit gate catches truly-unused imports.
    """

    def _ruff_stdout(self, body: str) -> object:
        return type("R", (), {"returncode": 1, "stdout": body, "stderr": ""})()

    def test_run_ruff_filters_F401_in_edit_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = self._ruff_stdout(
                "app.py:1:1: F401 [*] `os` imported but unused\n"
                "app.py:3:5: E302 expected 2 blank lines\n"
                "Found 2 errors.\n"
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertNotIn("F401", codes)
        self.assertIn("E302", codes)

    def test_run_ruff_filters_F811_in_edit_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = self._ruff_stdout(
                "app.py:5:1: F811 redefinition of unused `foo`\nFound 1 error.\n"
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertEqual(codes, [])

    def test_run_ruff_preserves_F401_in_staging_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = self._ruff_stdout(
                "app.py:1:1: F401 [*] `os` imported but unused\nFound 1 error.\n"
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertIn("F401", codes)

    def test_run_ruff_preserves_F811_in_staging_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = self._ruff_stdout(
                "app.py:5:1: F811 redefinition of unused `foo`\nFound 1 error.\n"
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertIn("F811", codes)

    def test_run_ruff_filtered_text_excludes_filtered_lines(self):
        """In 'edit' context, filtered output text should NOT mention F401."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = self._ruff_stdout(
                "app.py:1:1: F401 [*] `os` imported but unused\n"
                "app.py:3:5: E302 expected 2 blank lines\n"
                "Found 2 errors.\n"
            )
            _codes, text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertNotIn("F401", text)
        self.assertIn("E302", text)

    def test_run_ruff_returns_empty_when_ruff_clean(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
            )()
            codes, text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertEqual(codes, [])
        self.assertEqual(text, "")

    def test_run_ruff_returns_empty_when_binary_missing(self):
        with patch("lint_check.shutil.which", return_value=None):
            codes, text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertEqual(codes, [])
        self.assertEqual(text, "")

    def test_run_ruff_parses_multi_letter_codes(self):
        """Ruff plugin namespaces (RUF, PLR, ANN, UP, ...) use 2-3 letter
        prefixes. A single-letter regex would silently drop them — codes=[]
        flips has_errors to False and the lint error never surfaces."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = self._ruff_stdout(
                "app.py:1:1: RUF059 unpacked variable\n"
                "app.py:2:1: PLR0915 too many statements\n"
                "app.py:3:1: UP007 use X | Y\n"
                "Found 3 errors.\n"
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertIn("RUF059", codes)
        self.assertIn("PLR0915", codes)
        self.assertIn("UP007", codes)

    def test_run_ruff_parses_4plus_letter_prefixes(self):
        """Block-fix (concern 56a0e138ef8e): the {1,3}-letter regex bound still
        silently drops 4+ letter ruff plugin codes (PERF, FURB, FAST, ASYNC).
        When the regex misses, codes=[] flips has_errors=False and the lint
        error vanishes at edit time — same failure class as the single-letter
        bug that was previously fixed but not widely enough."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = self._ruff_stdout(
                "app.py:1:1: PERF401 use list comprehension\n"
                "app.py:2:1: FURB169 use isinstance not type comparison\n"
                "app.py:3:1: ASYNC100 unnecessary trio.fail_after\n"
                "Found 3 errors.\n"
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertIn("PERF401", codes)
        self.assertIn("FURB169", codes)
        self.assertIn("ASYNC100", codes)


class TestLintEditContextFilters(_HookTestCase):
    """End-to-end: lint_check.run() is the 'edit' context entry point.

    A file whose only ruff finding is F401 must NOT raise a concern and
    must NOT return additionalContext — F401 enforcement is deferred to
    the commit-gate staging check in pre_tool_bash.
    """

    def test_F401_only_returns_no_concern_at_edit_time(self):
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
                    {
                        "returncode": 1,
                        "stdout": (
                            "app.py:1:1: F401 [*] `os` imported but unused\n"
                            "Found 1 error.\n"
                        ),
                        "stderr": "",
                    },
                )()
                result = lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": str(target), "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            self.assertIsNone(result, "F401 must not surface at edit time")
            events = _common.read_events_raw(self.smm_dir)
            concerns = events_of_type(events, EVENT_TYPE_CONCERN)
            self.assertEqual(
                len(concerns), 0, "F401 must not raise concern at edit time"
            )
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_non_F401_still_surfaces_at_edit_time(self):
        """E302 (non-deferred code) still creates a concern at edit time."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        target = tmpdir / "app.py"
        target.write_text("def f():\n    pass\n")
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
                patch("lint_check.detect_linter_config", return_value=("ruff", "")),
            ):
                mock_run.return_value = type(
                    "R",
                    (),
                    {
                        "returncode": 1,
                        "stdout": (
                            "app.py:1:1: E302 expected 2 blank lines\nFound 1 error.\n"
                        ),
                        "stderr": "",
                    },
                )()
                result = lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": str(target), "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            assert result is not None
            self.assertIn("E302", result)
            events = _common.read_events_raw(self.smm_dir)
            concerns = events_of_type(events, EVENT_TYPE_CONCERN)
            self.assertEqual(len(concerns), 1)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()

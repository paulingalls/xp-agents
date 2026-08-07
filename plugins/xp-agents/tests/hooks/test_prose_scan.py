#!/usr/bin/env python3
"""Unit tests for the prose measurement scan (`tests/_prose_scan.py`).

Every counting case writes a temp module and runs the production scanner over
it — read -> ast.parse -> tokenize, the same pipeline the CLI uses. An
in-memory AST node would bypass file I/O and hide a regression in either
layer.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _pin_helpers import rel, shipped_files_by_root
from _prose_scan import format_report, scan_file, scan_roots
from test_file_size_pin import _line_count, _root_of

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "xp-agents"


class TestScanFileCounts(unittest.TestCase):
    """The counting pipeline, exercised end-to-end on real files."""

    def _write(self, td: str, src: str) -> Path:
        path = Path(td) / "fixture_module.py"
        path.write_text(src)
        return path

    def test_known_docstring_comment_code_split_scans_to_exact_numbers(self):
        src = (
            "#!/usr/bin/env python3\n"
            '"""One.\n'
            "Two.\n"
            'Three."""\n'
            "\n"
            "x = 1  # a comment\n"
            's = "not # a comment"\n'
        )
        with tempfile.TemporaryDirectory() as td:
            result = scan_file(self._write(td, src))

        self.assertEqual(result.total_lines, 7)
        self.assertEqual(result.docstring_lines, 3)
        self.assertEqual(result.comment_lines, 1)
        self.assertEqual(result.max_docstring_lines, 3)
        self.assertEqual(result.long_docstrings, 0)

    def test_a_shebang_is_not_counted_as_a_comment(self):
        src = "#!/usr/bin/env python3\nx = 1\n"
        with tempfile.TemporaryDirectory() as td:
            result = scan_file(self._write(td, src))

        self.assertEqual(result.comment_lines, 0)

    def test_a_hash_inside_a_string_literal_is_not_counted_as_a_comment(self):
        src = 's = "value # not a comment"\n'
        with tempfile.TemporaryDirectory() as td:
            result = scan_file(self._write(td, src))

        self.assertEqual(result.comment_lines, 0)

    def _docstring_module(self, n: int) -> str:
        body = "\n".join(f"line{i}" for i in range(n))
        return f'"""{body}"""\n'

    def test_a_24_line_docstring_is_not_long(self):
        with tempfile.TemporaryDirectory() as td:
            result = scan_file(self._write(td, self._docstring_module(24)))

        self.assertEqual(result.max_docstring_lines, 24)
        self.assertEqual(result.long_docstrings, 0)

    def test_a_25_line_docstring_is_long(self):
        with tempfile.TemporaryDirectory() as td:
            result = scan_file(self._write(td, self._docstring_module(25)))

        self.assertEqual(result.max_docstring_lines, 25)
        self.assertEqual(result.long_docstrings, 1)

    def test_denominator_agrees_with_the_file_size_pin_on_a_real_file(self):
        real_file = _PLUGIN_ROOT / "tests" / "_pin_helpers.py"
        result = scan_file(real_file)

        self.assertEqual(result.total_lines, _line_count(real_file))


class TestParseFailuresAreNotSilentlyClean(unittest.TestCase):
    """A file that fails to parse must surface as its own signal, never as a
    clean (0% prose) file that happens to have no docstrings or comments."""

    def test_a_syntax_error_is_reported_as_a_parse_failure(self):
        with tempfile.TemporaryDirectory() as td:
            plugin_root = Path(td)
            scripts = plugin_root / "scripts"
            smm = plugin_root / "smm"
            skill_scripts = plugin_root / "skills" / "foo" / "scripts"
            for d in (scripts, smm, skill_scripts):
                d.mkdir(parents=True)
            (scripts / "good.py").write_text('"""Fine."""\nx = 1\n')
            (scripts / "bad.py").write_text("def broken(:\n")
            (smm / "good.py").write_text("x = 1\n")
            (skill_scripts / "good.py").write_text("x = 1\n")

            roots = scan_roots(plugin_root)

        self.assertEqual(len(roots["scripts"].parse_failures), 1)
        failure_path, _message = roots["scripts"].parse_failures[0]
        self.assertEqual(failure_path.name, "bad.py")
        self.assertEqual(len(roots["scripts"].files), 1)


class TestScanRootsShape(unittest.TestCase):
    """`scan_roots` covers all three shipped roots on the real tree, each
    non-empty -- a narrowed selection is exactly the failure mode the sister
    `_shipped_root_shortfalls` check exists to catch."""

    def test_scan_roots_returns_all_three_keys_nonempty(self):
        roots = scan_roots(_PLUGIN_ROOT)

        self.assertEqual(set(roots.keys()), {"scripts", "smm", "skills"})
        for name, root in roots.items():
            self.assertGreater(len(root.files), 0, msg=name)


class TestShippedFilesByRootAgreesWithTheFileSizePin(unittest.TestCase):
    """The new grouped primitive must classify every real path exactly like
    the sister pin's independent `_root_of`, which predates it."""

    def test_every_real_path_agrees_with_root_of(self):
        grouped = shipped_files_by_root(_PLUGIN_ROOT)

        for group, paths in grouped.items():
            expected = "skills/*/scripts" if group == "skills" else group
            for path in paths:
                self.assertEqual(_root_of(rel(path, _REPO_ROOT)), expected)


class TestCLI(unittest.TestCase):
    """The CLI is invoked with `--root` and prints without asserting
    anything -- reporting only, per this milestone's constraint."""

    def test_a_single_root_report_prints_that_roots_line_and_exits_cleanly(self):
        roots = scan_roots(_PLUGIN_ROOT)
        report = format_report({"smm": roots["smm"]})

        self.assertIn("root=smm", report)

    def test_real_subprocess_invocation_prints_the_frozen_root_line(self):
        """Must actually spawn a subprocess -- an in-process `main([...])`
        call passes even when the standalone import path is broken, which is
        the precise failure this test exists to catch."""
        result = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "tests" / "_prose_scan.py"),
                "--root",
                "scripts",
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("root=scripts", result.stdout)


if __name__ == "__main__":
    unittest.main()

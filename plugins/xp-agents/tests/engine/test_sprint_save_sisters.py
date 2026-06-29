#!/usr/bin/env python3
"""Tests for sprint_save._auto_include_sister_tests.

Extracted from tests/hooks/test_sprint_start.py in sprint-108 M1 (story-001).
Folds concern 2097e2759873: _auto_include_sister_tests takes project_root as a
direct argument and never calls _resolve_project_root, so the prior
_make_git_project(self._tmp) setup was dead — a real `git init` whose result the
code under test never consulted. These tests stage files under a plain tmpdir
and pass it straight through, no git required.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
# Temporary skill-scripts path for sister_tests (still skill-layer until
# story-002 relocates it into smm/); story-002 drops this + the sister_tests
# import once sister_tests lives in smm/ (conftest already adds smm/).
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent / "skills" / "xp-sprint-start" / "scripts"),
)

import sister_tests  # pyright: ignore[reportMissingImports]
import sprint_save
from conftest import _SMMTestCase


class TestAutoIncludeSisterTests(_SMMTestCase):
    """_auto_include_sister_tests appends discovered sister-test paths to
    each story's file_domain, dedups against existing entries, and skips
    entries already marked as sisters (prevents sister-of-sister)."""

    def setUp(self):
        super().setUp()

        self._tmp = Path(tempfile.mkdtemp(prefix="story-004-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self._tmp)]))
        self.mod = sprint_save
        self.sister_tests = sister_tests

    def _make_layout(self, convention: str = "python_pytest"):
        return self.sister_tests.BUILTIN_LAYOUTS[convention]

    def _write_file(self, rel: str, content: str = "") -> Path:
        p = self._tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_python_pytest_layout_appends_existing_sister(self):
        self._write_file("src/foo.py", "x = 1")
        self._write_file("tests/test_foo.py", "def test_x(): pass")
        data = {"stories": [{"id": "s1", "file_domain": ["src/foo.py — impl"]}]}
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        self.assertIn(
            "tests/test_foo.py — sister test for src/foo.py",
            data["stories"][0]["file_domain"],
        )

    def test_no_sister_on_disk_is_noop(self):
        self._write_file("src/foo.py", "x = 1")
        data = {"stories": [{"id": "s1", "file_domain": ["src/foo.py — impl"]}]}
        before = list(data["stories"][0]["file_domain"])
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        self.assertEqual(data["stories"][0]["file_domain"], before)

    def test_dedups_existing_manual_sister(self):
        self._write_file("src/foo.py", "x = 1")
        self._write_file("tests/test_foo.py", "def test_x(): pass")
        data = {
            "stories": [
                {
                    "id": "s1",
                    "file_domain": [
                        "src/foo.py — impl",
                        "tests/test_foo.py — manual",
                    ],
                }
            ]
        }
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        paths = [e.split(" — ")[0] for e in data["stories"][0]["file_domain"]]
        self.assertEqual(paths.count("tests/test_foo.py"), 1)

    def test_skips_sister_marked_entries(self):
        """An entry whose note is 'sister test for X' must NOT be re-walked
        (sister-of-sister discovery would expand file_domain unboundedly)."""
        self._write_file("src/foo.py", "x = 1")
        self._write_file("tests/test_foo.py", "def test_x(): pass")
        self._write_file("tests/test_test_foo.py", "def test_meta(): pass")
        data = {
            "stories": [
                {
                    "id": "s1",
                    "file_domain": [
                        "src/foo.py — impl",
                        "tests/test_foo.py — sister test for src/foo.py",
                    ],
                }
            ]
        }
        self.mod._auto_include_sister_tests(data, self._make_layout(), self._tmp)
        for entry in data["stories"][0]["file_domain"]:
            self.assertNotIn(
                "test_test_foo.py",
                entry,
                f"sister-of-sister leaked: {entry}",
            )


if __name__ == "__main__":
    unittest.main()

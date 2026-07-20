#!/usr/bin/env python3
"""Shared test infrastructure for the test_lint*.py sibling modules.

Not `test_`-prefixed, so pytest/unittest discovery never collects it directly.
Extracted from test_lint.py because `_StagedGitRepo` is used by TestCase
classes that landed in different sibling files after the split (staged-gate
branch tests and staged-gate edge-case tests) — duplicating it would let the
two copies drift.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path


class _StagedGitRepo(unittest.TestCase):
    """A real git repo the staged-lint gate can resolve a root + index from."""

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(self.repo), check=True, capture_output=True
        )

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Tester")
        (self.repo / "ruff.toml").touch()

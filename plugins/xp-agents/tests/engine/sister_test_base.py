#!/usr/bin/env python3
"""Shared base for the engine sister-test suites.

``_DiscoveryTestCase`` and ``_touch`` are imported by
``test_sister_discovery.py`` and ``test_sister_layouts.py`` so exactly one
definition exists. Co-located here (relocated from tests/hooks/) so the engine
suite no longer reaches cross-suite into the hooks dir for its base.

The filename is intentionally NOT ``test_*.py``, so neither pytest nor
``python3 -m unittest discover`` collects it as a test module. The cluster is
stdlib-only (no sister_tests dependency), so this module needs no sys.path
insert of its own.
"""

import shutil
import tempfile
import unittest
from pathlib import Path


def _make_tmp_project() -> Path:
    """Create and return a fresh temp project dir (caller registers cleanup)."""
    return Path(tempfile.mkdtemp(prefix="sister_tests_"))


def _touch(root: Path, rel: str) -> None:
    """Create an empty file at ``root/rel``, including parent dirs."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


class _DiscoveryTestCase(unittest.TestCase):
    """Base: gives each test a temp project_root with auto-cleanup."""

    def setUp(self):
        self.root = _make_tmp_project()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

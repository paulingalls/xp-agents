#!/usr/bin/env python3
"""Tests for story_metrics.py — extract_file_domain_paths."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import conftest  # noqa: F401 — git env cleanup


class TestExtractFileDomainPaths(unittest.TestCase):
    def test_extracts_path_before_dash(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths(
            ["scripts/auth.py \u2014 add login", "tests/test_auth.py \u2014 auth tests"]
        )
        self.assertEqual(paths, {"scripts/auth.py", "tests/test_auth.py"})

    def test_plain_path_without_description(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths(["scripts/auth.py"])
        self.assertEqual(paths, {"scripts/auth.py"})

    def test_empty_list(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths([])
        self.assertEqual(paths, set())

    def test_mixed_formats(self):
        import story_metrics

        paths = story_metrics.extract_file_domain_paths(
            ["scripts/auth.py \u2014 add login", "scripts/plain.py"]
        )
        self.assertEqual(paths, {"scripts/auth.py", "scripts/plain.py"})


if __name__ == "__main__":
    unittest.main()

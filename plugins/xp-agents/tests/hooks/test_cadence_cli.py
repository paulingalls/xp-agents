#!/usr/bin/env python3
"""Tests for cadence_cli.py: read|write the session review cadence marker.

The dedicated entry point lets SKILL.md (WRITE) and the preload shell
helper (READ) stop inlining a `python3 -c` markers bootstrap. Thin layer
over markers.read_review_cadence / write_review_cadence.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _CADENCE_CLI_PY, _HookTestCase, run_cli


class TestCadenceCLI(_HookTestCase):
    def test_read_defaults_to_commit_when_unset(self):
        """No marker -> fail-safe 'commit' (markers.read_review_cadence default)."""
        result = run_cli(_CADENCE_CLI_PY, ["read"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "commit")

    def test_write_story_then_read(self):
        write = run_cli(_CADENCE_CLI_PY, ["write", "story"], self.smm_dir)
        self.assertEqual(write.returncode, 0, write.stderr)
        read = run_cli(_CADENCE_CLI_PY, ["read"], self.smm_dir)
        self.assertEqual(read.stdout.strip(), "story")

    def test_write_commit_then_read(self):
        run_cli(_CADENCE_CLI_PY, ["write", "story"], self.smm_dir)
        run_cli(_CADENCE_CLI_PY, ["write", "commit"], self.smm_dir)
        read = run_cli(_CADENCE_CLI_PY, ["read"], self.smm_dir)
        self.assertEqual(read.stdout.strip(), "commit")

    def test_write_invalid_cadence_rejected(self):
        """argparse choices rejects unknown values at the boundary."""
        result = run_cli(_CADENCE_CLI_PY, ["write", "bogus"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bogus", result.stderr)

    def test_write_requires_a_value(self):
        result = run_cli(_CADENCE_CLI_PY, ["write"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_no_subcommand_errors(self):
        result = run_cli(_CADENCE_CLI_PY, [], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

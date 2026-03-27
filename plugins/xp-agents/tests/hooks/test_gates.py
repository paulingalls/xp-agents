#!/usr/bin/env python3
"""Tests for security triage marker helpers.

Simplify gate tests removed in M3 (commit-gated review cycle replaces Stop gates).
TDD stop gate tests are in test_stop_gates.py.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import security
from conftest import _HookTestCase

# ===========================================================================
# Security triage marker helpers — replaces hash-based tracker
# ===========================================================================


class TestSecurityTriageMarker(_HookTestCase):
    """Tests for security triage marker helpers in security.py."""

    def test_triaged_path(self):
        """security_triaged_path returns correct path."""
        path = security.security_triaged_path(self.smm_dir)
        self.assertEqual(path, self.smm_dir / ".security-triaged")

    def test_write_and_exists(self):
        """write_security_triaged creates file, security_triaged_exists finds it."""
        security.write_security_triaged(self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_not_exists_when_missing(self):
        """security_triaged_exists returns False when no marker file."""
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_consume_deletes_marker(self):
        """consume_security_triaged removes the marker."""
        security.write_security_triaged(self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))
        security.consume_security_triaged(self.smm_dir)
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_consume_no_op_when_missing(self):
        """consume_security_triaged is safe when marker doesn't exist."""
        security.consume_security_triaged(self.smm_dir)  # no crash

    def test_rejects_symlink(self):
        """security_triaged_exists returns False for symlinks."""
        real_file = self.smm_dir / "real_target"
        real_file.write_text("x")
        link = security.security_triaged_path(self.smm_dir)
        link.symlink_to(real_file)
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_write_marker_content(self):
        """write_security_triaged writes JSON with ts."""
        security.write_security_triaged(self.smm_dir)
        path = security.security_triaged_path(self.smm_dir)
        data = json.loads(path.read_text())
        self.assertIn("ts", data)

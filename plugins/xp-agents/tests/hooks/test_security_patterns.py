#!/usr/bin/env python3
"""Tests for security_patterns.V3_0_PATTERNS — per-pattern coverage + invariants."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from security_patterns import V3_0_PATTERNS
from security_scanner import Finding, scan_diff


def _scan(diff_lines: list[str], path: str = "scripts/cfg.py") -> list[Finding]:
    """Build a single-file diff with the added lines, then scan with V3_0_PATTERNS.

    `path` defaults to a non-test path so `skip_tests=True` patterns still
    fire — most positive-case tests rely on this. Pass an explicit test path
    when verifying the skip_tests filter.
    """
    diff = f"+++ b/{path}\n@@ -0,0 +1,{len(diff_lines)} @@\n" + "".join(
        f"+{line}\n" for line in diff_lines
    )
    return scan_diff(diff, V3_0_PATTERNS)


def _names(findings: list[Finding]) -> set[str]:
    return {f.pattern_name for f in findings}


class TestSkipTestsAllSetTrue(unittest.TestCase):
    """v3.0 invariant: every pattern is `skip_tests=True`."""

    def test_all_v30_patterns_skip_tests_true(self):
        for pat in V3_0_PATTERNS:
            self.assertTrue(
                pat.skip_tests, f"{pat.name} should be skip_tests=True for v3.0"
            )


class TestSecretPatterns(unittest.TestCase):
    """Per-pattern positive + false-positive coverage for the 4 secret patterns."""

    def test_aws_access_key_positive(self):
        findings = _scan(['key = "AKIA1234567890ABCDEF"'])
        self.assertIn("aws-access-key", _names(findings))

    def test_aws_access_key_short_string_no_match(self):
        # `AKIASmith` is only 8 chars after AKIA; regex requires exactly 16.
        findings = _scan(['name = "AKIASmith"'])
        self.assertNotIn("aws-access-key", _names(findings))

    def test_github_pat_positive(self):
        # 40 chars total: ghp_ + 36 alphanumerics
        findings = _scan(['token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"'])
        self.assertIn("github-token", _names(findings))

    def test_github_oauth_token_positive(self):
        findings = _scan(['token = "gho_abcdefghijklmnopqrstuvwxyz0123456789AB"'])
        self.assertIn("github-token", _names(findings))

    def test_github_token_short_no_match(self):
        findings = _scan(['name = "ghp_short"'])
        self.assertNotIn("github-token", _names(findings))

    def test_private_key_pem_positive(self):
        findings = _scan(["-----BEGIN RSA PRIVATE KEY-----"])
        self.assertIn("private-key-pem", _names(findings))

    def test_private_key_pem_generic_positive(self):
        findings = _scan(["-----BEGIN PRIVATE KEY-----"])
        self.assertIn("private-key-pem", _names(findings))

    def test_pem_documentation_text_no_match(self):
        # No `-----BEGIN ... PRIVATE KEY-----` shape, just prose.
        findings = _scan(["# This module handles RSA private key parsing"])
        self.assertNotIn("private-key-pem", _names(findings))

    def test_password_literal_positive(self):
        findings = _scan(['password = "supersecret123"'])
        self.assertIn("password-literal", _names(findings))

    def test_password_case_insensitive(self):
        findings = _scan(['PASSWORD = "supersecret123"'])
        self.assertIn("password-literal", _names(findings))

    def test_password_short_value_no_match(self):
        # Value is only 3 chars; regex requires {8,}.
        findings = _scan(['password = "abc"'])
        self.assertNotIn("password-literal", _names(findings))


if __name__ == "__main__":
    unittest.main()

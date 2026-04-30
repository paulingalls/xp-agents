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

    def test_password_placeholder_known_false_positive(self):
        # KNOWN LIMITATION: the regex matches any 8+ char string after
        # `password =`, so docs/examples with placeholders also fire.
        # Suppress with `# noqa: secret` on intentional placeholder
        # lines, or evolve the catalog to exclude well-known forms
        # (e.g. negative lookahead for `your_*`, `<your-...>`, `xxx*`).
        findings = _scan(['password = "your_password_here"'])
        self.assertIn("password-literal", _names(findings))


class TestShellInjectionPatterns(unittest.TestCase):
    """Per-pattern coverage for the 3 shell-injection patterns."""

    def test_subprocess_shell_true_with_fstring_canonical(self):
        # Canonical Python ordering: cmd first, kwargs last.
        findings = _scan(['subprocess.run(f"ls {x}", shell=True)'])
        self.assertIn("subprocess-shell-true", _names(findings))

    def test_subprocess_shell_true_with_concat_canonical(self):
        findings = _scan(['subprocess.call("ls " + arg, shell=True)'])
        self.assertIn("subprocess-shell-true", _names(findings))

    def test_subprocess_shell_true_with_literal_matches(self):
        # Per relaxed regex (story-002 plan revision): any shell=True fires.
        # Safe literal-string usage suppresses with `# noqa: secret`.
        findings = _scan(['subprocess.run("ls -la", shell=True)'])
        self.assertIn("subprocess-shell-true", _names(findings))

    def test_subprocess_no_shell_arg_no_match(self):
        findings = _scan(['subprocess.run(["ls", arg])'])
        self.assertNotIn("subprocess-shell-true", _names(findings))

    def test_subprocess_shell_false_no_match(self):
        findings = _scan(['subprocess.run("ls", shell=False)'])
        self.assertNotIn("subprocess-shell-true", _names(findings))

    def test_subprocess_literal_close_paren_blind_spot(self):
        # KNOWN LIMITATION: the [^)]* quantifier stops at the FIRST `)`,
        # so a `)` inside a string literal closes the regex window before
        # reaching shell=True. Pinning this so a future maintainer
        # "fixing" it considers the catastrophic-backtracking trade-off
        # of any unbounded alternative (e.g. balanced-paren regex).
        findings = _scan(['subprocess.run("echo )", shell=True)'])
        self.assertNotIn("subprocess-shell-true", _names(findings))

    def test_os_system_positive(self):
        findings = _scan(['os.system("rm -rf /tmp/scratch")'])
        self.assertIn("os-system", _names(findings))

    def test_os_system_substring_no_match(self):
        # `pos.system(` shouldn't fire — the \b anchor pins `os.system` as a whole word.
        findings = _scan(["something.pos.system(x)"])
        self.assertNotIn("os-system", _names(findings))

    def test_eval_call_positive(self):
        findings = _scan(["eval(user_input)"])
        self.assertIn("eval-exec", _names(findings))

    def test_exec_call_positive(self):
        findings = _scan(["exec(compile(code, '<string>', 'exec'))"])
        self.assertIn("eval-exec", _names(findings))

    def test_evaluator_substring_no_match(self):
        # `evaluator(` shouldn't fire — \b pins eval as a whole word.
        findings = _scan(["evaluator(x)"])
        self.assertNotIn("eval-exec", _names(findings))

    def test_executor_substring_no_match(self):
        # `executor(` shouldn't fire — \b pins exec as a whole word.
        findings = _scan(["executor(y)"])
        self.assertNotIn("eval-exec", _names(findings))


class TestUrlCredentialPatterns(unittest.TestCase):
    """Per-pattern coverage for the url-credentials pattern."""

    def test_https_user_pass_url_positive(self):
        findings = _scan(['url = "https://alice:s3cret@api.example.com/v1"'])
        self.assertIn("url-credentials", _names(findings))

    def test_http_user_pass_url_positive(self):
        findings = _scan(['url = "http://bob:hunter2@internal.example.com"'])
        self.assertIn("url-credentials", _names(findings))

    def test_url_without_credentials_no_match(self):
        findings = _scan(['url = "https://api.example.com/v1/users"'])
        self.assertNotIn("url-credentials", _names(findings))

    def test_url_credentials_docs_example_known_false_positive(self):
        # KNOWN LIMITATION: the regex matches any user:pass@host shape,
        # including doc examples like `https://user:pass@example.com`.
        # Suppress with `# noqa: secret` on intentional doc lines, or
        # evolve the catalog to exclude well-known placeholder forms.
        findings = _scan(["# Example: https://user:pass@example.com"])
        self.assertIn("url-credentials", _names(findings))


class TestV30PatternsE2E(unittest.TestCase):
    """Story-002 acceptance criterion #5 — fixture with one positive case
    per pattern class plus matching false-positives → exactly the positive
    cases are flagged."""

    def test_combined_diff_flags_exactly_positives(self):
        # 4 positive cases (one per pattern class + a 4th secret variety) and
        # 4 false-positives that resemble each shape but shouldn't fire.
        diff_lines = [
            # POSITIVES
            'aws_key = "AKIA1234567890ABCDEF"',
            'gh_token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"',
            'subprocess.run(f"ls {dir}", shell=True)',
            'db_url = "https://admin:s3cret@db.example.com/myapp"',
            # FALSE-POSITIVES
            'aws_label = "AKIASmith"',  # too short for AWS key shape
            'name = "ghp_short"',  # too short for github token shape
            'subprocess.run(["ls", path])',  # no shell=True
            'public_url = "https://api.example.com/v1"',  # no credentials
        ]
        findings = _scan(diff_lines)
        flagged_lines = {f.line_content for f in findings}
        # Exactly the 4 positives are reported, no false-positives slip through.
        self.assertEqual(len(findings), 4)
        self.assertIn('aws_key = "AKIA1234567890ABCDEF"', flagged_lines)
        self.assertIn(
            'gh_token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"',
            flagged_lines,
        )
        self.assertIn('subprocess.run(f"ls {dir}", shell=True)', flagged_lines)
        self.assertIn(
            'db_url = "https://admin:s3cret@db.example.com/myapp"',
            flagged_lines,
        )
        # None of the false-positive lines flagged
        for fp in [
            'aws_label = "AKIASmith"',
            'name = "ghp_short"',
            'subprocess.run(["ls", path])',
            'public_url = "https://api.example.com/v1"',
        ]:
            self.assertNotIn(fp, flagged_lines)

    def test_v30_patterns_count(self):
        """Pin the expected v3.0 pattern count — adding/removing a pattern
        is a deliberate decision that should fail this test until updated."""
        self.assertEqual(len(V3_0_PATTERNS), 8)


if __name__ == "__main__":
    unittest.main()

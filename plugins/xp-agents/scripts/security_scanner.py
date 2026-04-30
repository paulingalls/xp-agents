#!/usr/bin/env python3
"""Tier 1 deterministic security scanner: regex match against staged diff lines.

Scans a unified diff for occurrences of high-confidence security patterns
(secrets, shell injection, hardcoded URL credentials). Emits a Finding per
match. Pure logic — no I/O, no SMM coupling. Callers pass the diff text
and the pattern list; the scanner returns findings.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pattern:
    """A regex pattern paired with a stable name and test-file behavior.

    `name` is reported in Findings and shown in commit-block messages.
    `regex` is a compiled pattern — callers pre-compile so each pattern
    is built once at import time.
    `skip_tests` opts out of matching when the file path is recognized
    as a test file (per pre_tool_write.is_test_file).
    """

    name: str
    regex: re.Pattern
    skip_tests: bool = False


@dataclass(frozen=True, slots=True)
class Finding:
    """A pattern match found in a staged diff."""

    pattern_name: str
    file_path: str
    line_number: int
    line_content: str


def scan_diff(diff_text: str, patterns: list[Pattern]) -> list[Finding]:
    """Scan a unified diff for pattern matches.

    Walks `+++ b/<path>` headers to track the current file, then for each
    added line (prefix '+') runs every pattern's regex. Returns one
    Finding per (pattern, line) match.

    Minimal implementation: line numbers are not yet derived from hunk
    headers — every match reports line_number=1. Hunk parsing is a planned
    follow-up.
    """
    findings: list[Finding] = []
    current_file = ""
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[len("+++ b/") :].rstrip()
        elif raw.startswith(("+++", "---")) or not current_file:
            continue
        elif raw.startswith("+"):
            line_body = raw[1:]
            for pat in patterns:
                if pat.regex.search(line_body):
                    findings.append(
                        Finding(
                            pattern_name=pat.name,
                            file_path=current_file,
                            line_number=1,
                            line_content=line_body,
                        )
                    )
    return findings

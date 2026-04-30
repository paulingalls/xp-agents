#!/usr/bin/env python3
"""Tier 1 deterministic security scanner: regex match against staged diff lines.

Scans a unified diff for occurrences of high-confidence security patterns
(secrets, shell injection, hardcoded URL credentials). Emits a Finding per
match. Pure logic — no I/O, no SMM coupling. Callers pass the diff text
and the pattern list; the scanner returns findings.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pre_tool_write import is_test_file


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


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_NOQA_RE = re.compile(r"#\s*noqa:\s*secret\b", re.IGNORECASE)


def scan_diff(diff_text: str, patterns: list[Pattern]) -> list[Finding]:
    """Scan a unified diff for pattern matches.

    Walks `+++ b/<path>` headers to track the current file and `@@` hunk
    headers to track the new-file line counter, then for each added line
    (prefix '+') runs every pattern's regex. Returns one Finding per
    (pattern, line) match. Removed lines ('-') don't advance the new-file
    counter; context lines (' ') do.
    """
    findings: list[Finding] = []
    current_file = ""
    in_test = False
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[len("+++ b/") :].rstrip()
            in_test = is_test_file(current_file)
            continue
        if raw.startswith("+++"):
            # `+++ /dev/null` (deletion) — clear context so any stray '+' lines
            # before the next file header aren't misattributed to the prior file.
            current_file = ""
            in_test = False
            continue
        if raw.startswith("---") or not current_file:
            continue
        if raw.startswith("@@"):
            hunk = _HUNK_RE.match(raw)
            if hunk:
                new_line = int(hunk.group(1))
            continue
        if raw.startswith("+"):
            line_body = raw[1:]
            if not _NOQA_RE.search(line_body):
                for pat in patterns:
                    if pat.skip_tests and in_test:
                        continue
                    if pat.regex.search(line_body):
                        findings.append(
                            Finding(
                                pattern_name=pat.name,
                                file_path=current_file,
                                line_number=new_line,
                                line_content=line_body,
                            )
                        )
            new_line += 1
        elif raw.startswith(" "):
            new_line += 1
    return findings

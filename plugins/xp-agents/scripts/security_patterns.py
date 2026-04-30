#!/usr/bin/env python3
"""v3.0 deterministic security pattern catalog.

Caller-pinned list of patterns scanned by security_scanner.scan_diff() at
commit time. v3.0 set per docs/ideas/security_review_doctrine.md
§Resolved Design Calls #3 — path traversal and other classes deferred to
v3.1+ pending empirical evidence.
"""

import re

from security_scanner import Pattern

V3_0_PATTERNS: list[Pattern] = [
    # --- Secrets ---
    Pattern(
        name="aws-access-key",
        regex=re.compile(r"AKIA[0-9A-Z]{16}"),
        skip_tests=True,
    ),
    Pattern(
        name="github-token",
        regex=re.compile(r"gh[poushr]_[A-Za-z0-9]{36}"),
        skip_tests=True,
    ),
    Pattern(
        name="private-key-pem",
        regex=re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        skip_tests=True,
    ),
    Pattern(
        name="password-literal",
        regex=re.compile(
            r"""(?:password|passwd|pwd)\s*[:=]\s*["'][^"']{8,}["']""",
            re.IGNORECASE,
        ),
        skip_tests=True,
    ),
    # --- Shell injection ---
    # subprocess-shell-true: relaxed from doctrine's "with interpolation"
    # qualifier so canonical Python ordering (cmd first, kwargs last) fires.
    # Production has zero shell=True today; safe literal-string uses suppress
    # with `# noqa: secret`.
    Pattern(
        name="subprocess-shell-true",
        regex=re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True\b"),
        skip_tests=True,
    ),
    Pattern(
        name="os-system",
        regex=re.compile(r"\bos\.system\s*\("),
        skip_tests=True,
    ),
    Pattern(
        name="eval-exec",
        regex=re.compile(r"\b(?:eval|exec)\s*\("),
        skip_tests=True,
    ),
    # --- URL credentials ---
    Pattern(
        name="url-credentials",
        regex=re.compile(r"https?://[^\s/:@]+:[^\s/:@]+@"),
        skip_tests=True,
    ),
]

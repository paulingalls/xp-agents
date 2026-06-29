#!/usr/bin/env python3
"""Shared shell-glob → regex translator.

Two prior implementations (triage._glob_to_regex, sister_tests._compile_source_pattern)
shared the same intent and drifted on two cosmetic details that don't
affect behavior for project-relative paths:
  - `**/`  → triage emitted `(?:.*/)?` ; sister_tests emitted `(?:.+/)?`.
            Both have an OUTER `?` making the group optional, so both
            already allowed zero segments (i.e. `**/*.py` matched root
            `foo.py` in BOTH forms). The forms only differ for paths
            beginning with a literal `/` — never an input for
            project-relative file_domain values. The triage spelling is
            adopted here as the conventional one.
  - `/**` → triage explicitly emitted `(?:/.*)?` ; sister_tests had no
            dedicated rule and fell through to bare `**` → `.*`. Same
            tail-anything match in practice; the explicit form documents
            intent.
  - malformed `[` (no closing `]`) → both fell back to `re.escape` of the
            offending char; behavior identical, just expressed differently.

The unification is therefore a DRY refactor, not a behavior change. This
module is the single source of truth. fnmatch.translate is NOT a
substitute: its `*` crosses slashes, so `**`-recursion can't be expressed.
"""

import re

__all__ = ["glob_to_regex"]


def glob_to_regex(pattern: str) -> str:
    """Translate a shell-style glob to a regex string.

    Honors `**` as "zero or more path segments" (so `tests/**/*.py` matches
    both `tests/a.py` and `tests/sub/a.py`); `*` and `?` stop at slashes;
    bracket classes pass through; a malformed `[` is escaped as a literal.

    Returns the regex SOURCE, not a compiled pattern — callers add anchors
    (`fullmatch`, `match`) and pay for `re.compile` with their own caching
    strategy.
    """
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i):
            out.append("(?:/.*)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            j = pattern.find("]", i)
            if j == -1:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                out.append(pattern[i : j + 1])
                i = j + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)

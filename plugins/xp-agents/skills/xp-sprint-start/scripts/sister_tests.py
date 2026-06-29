#!/usr/bin/env python3
"""Pure sister-test discovery for any project layout.

Project-agnostic primitive: given a source path and a TestLayout, return the
list of project-relative sister-test paths that exist on disk. No SMM writes,
no mutation, no I/O beyond ``project_root.glob(...)``.
"""

from __future__ import annotations

import functools
import re


def _expand_braces(pattern: str) -> list[str]:
    """Expand a single top-level ``{a,b,c}`` group.

    ``'foo.{js,ts}'`` -> ``['foo.js', 'foo.ts']``. Multiple groups are handled
    by recursion. Malformed input (unclosed brace, no brace) passes through
    unchanged as a one-element list.
    """
    i = pattern.find("{")
    if i == -1:
        return [pattern]
    j = pattern.find("}", i)
    if j == -1:
        return [pattern]
    prefix = pattern[:i]
    options = pattern[i + 1 : j].split(",")
    suffix = pattern[j + 1 :]
    out: list[str] = []
    for opt in options:
        out.extend(_expand_braces(f"{prefix}{opt}{suffix}"))
    return out


@functools.lru_cache(maxsize=512)
def _compile_source_pattern(pattern: str) -> re.Pattern:
    """Translate a shell-style glob into a regex with cross-segment ``**``.

    fnmatch.translate would collapse ``**`` to ``.*`` and lose the segment
    boundary that ``**/x`` needs (match ``x``, ``a/x``, ``a/b/x``). Token-walk
    instead so ``**/`` becomes ``(?:.+/)?`` BEFORE any per-char escaping.

    Required because ``PurePosixPath.match`` does NOT honor mid-pattern ``**``
    until Python 3.13 (``full_match``); xp-agents' CI runs 3.11/3.12.
    """
    parts: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if pattern.startswith("**/", i):
            parts.append("(?:.+/)?")
            i += 3
        elif pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif ch == "*":
            parts.append("[^/]*")
            i += 1
        elif ch == "?":
            parts.append("[^/]")
            i += 1
        elif ch == "[":
            j = pattern.find("]", i)
            if j == -1:
                parts.append(re.escape(ch))
                i += 1
            else:
                parts.append(pattern[i : j + 1])
                i = j + 1
        else:
            parts.append(re.escape(ch))
            i += 1
    return re.compile("".join(parts))


def _match_any(src_str: str, pattern: str) -> bool:
    """Brace-expand ``pattern`` and return True if any branch fullmatches."""
    return any(
        _compile_source_pattern(p).fullmatch(src_str) is not None
        for p in _expand_braces(pattern)
    )

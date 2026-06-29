#!/usr/bin/env python3
"""Pure sister-test discovery for any project layout.

Project-agnostic primitive: given a source path and a TestLayout, return the
list of project-relative sister-test paths that exist on disk. No SMM writes,
no mutation, no I/O beyond ``project_root.glob(...)``.
"""

from __future__ import annotations

import functools
import posixpath
import re
from pathlib import PurePosixPath


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


def _literal_prefix(pattern: str) -> str:
    """Return the literal directory prefix of a glob.

    Everything up to and INCLUDING the trailing ``/`` before the first
    metachar. ``lib/**/*.rb`` -> ``lib/``, ``src/main/java/**/*.java``
    -> ``src/main/java/``, ``**/*.py`` -> ``""``, ``docs/intro.md`` ->
    the whole string (no metachars at all). Used to compute ``{mirror}``
    substitutions in :func:`_resolve_test_glob`.
    """
    for i, ch in enumerate(pattern):
        if ch in "*?[":
            return pattern[: pattern.rfind("/", 0, i) + 1]
    return pattern


def _resolve_test_glob(rule, stem: str, src: PurePosixPath) -> list[str]:
    """Apply ``{stem}``, ``{dir}``, ``{mirror}`` to ``rule.test_glob``.

    ``{mirror}`` is ``src.parent`` with the rule's literal source prefix
    stripped. Collapses to empty string when the source sits directly under
    the prefix; ``posixpath.normpath`` then cleans the resulting double-slash.
    The output is brace-expanded and normalized for use by ``project_root.glob``.
    """
    mirror = ""
    if "{mirror}" in rule.test_glob:
        prefix = _literal_prefix(rule.source_pattern).rstrip("/")
        parent = str(src.parent)
        if prefix and parent.startswith(prefix):
            parent = parent[len(prefix) :]
        mirror = parent.strip("/")
    # str.replace, not str.format: test_glob can contain {js,ts,...} brace
    # groups whose commas would make str.format treat the whole group as a
    # field name and raise KeyError. After substitution, _expand_braces is
    # safe to run because the only remaining { } are real alternation groups.
    substituted = (
        rule.test_glob.replace("{stem}", stem)
        .replace("{dir}", str(src.parent))
        .replace("{mirror}", mirror)
    )
    return [posixpath.normpath(p) for p in _expand_braces(substituted)]

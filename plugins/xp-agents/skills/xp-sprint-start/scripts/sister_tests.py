#!/usr/bin/env python3
"""Pure sister-test discovery for any project layout.

Project-agnostic primitive: given a source path and a TestLayout, return the
list of project-relative sister-test paths that exist on disk. No SMM writes,
no mutation, no I/O beyond ``project_root.glob(...)``.
"""

from __future__ import annotations


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

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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class TestLayoutRule:
    """One rule in a TestLayout: when a source matches, what test paths to look for.

    ``source_pattern`` is a shell-style glob (supports mid-pattern ``**``).
    ``stem_extractor`` is a key in :data:`STEM_EXTRACTORS`. ``test_glob`` is a
    template with ``{stem}``, ``{dir}``, ``{mirror}`` placeholders and optional
    ``{a,b,c}`` brace-alternation groups. ``skip_basenames`` / ``skip_suffixes``
    / ``source_excludes`` are short-circuit filters applied before pattern
    matching.
    """

    # __test__ = False keeps pytest from collecting this dataclass as a test
    # class (matches the project's `python_classes = Test*` discovery rule).
    __test__ = False

    source_pattern: str
    stem_extractor: str
    test_glob: str
    skip_basenames: tuple[str, ...] = ()
    skip_suffixes: tuple[str, ...] = ()
    source_excludes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TestLayout:
    """A named convention (rules) plus optional project-specific overrides.

    Both ``rules`` and ``overrides`` are processed in order; matches union and
    dedup at discovery time. Overrides do NOT replace rules — they concatenate.
    """

    __test__ = False

    convention: str
    rules: tuple[TestLayoutRule, ...]
    overrides: tuple[TestLayoutRule, ...] = ()


def _basename_no_ext(source_path: str) -> str | None:
    """Stem from the last path segment, or None if empty."""
    return PurePosixPath(source_path).stem or None


STEM_EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "basename_no_ext": _basename_no_ext,
}
# NOTE: a plugin-internal extractor (e.g. _skill_dir_xp_strip) is deferred per
# plan-review concern #5 (YAGNI) until story-002's analyzer actually declares
# an override that needs it. Adding a registry entry later IS a code change
# whether we land it now or then — defer until the consumer exists.


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


def _resolve_test_glob(
    rule: TestLayoutRule, stem: str, src: PurePosixPath
) -> list[str]:
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


# --- BUILTIN_LAYOUTS table (per-language entries added in subsequent commits) ---
BUILTIN_LAYOUTS: dict[str, TestLayout] = {}


def discover_sister_tests(
    source_path: str,
    layout: TestLayout,
    project_root: Path,
) -> list[str]:
    """Return sorted, deduped, project-relative POSIX paths of sister tests.

    Pure: no SMM writes, no mutation, no I/O beyond ``project_root.glob(...)``.
    Iterates every rule + override; for each matching rule, extracts a stem
    and resolves the test_glob to candidate paths, then globs the filesystem
    and unions the on-disk hits.

    Raises:
        ValueError: when ``source_path`` is absolute or a rule names a
            stem_extractor that is not in :data:`STEM_EXTRACTORS`.
    """
    if PurePosixPath(source_path).is_absolute():
        raise ValueError(f"source_path must be project-relative: {source_path!r}")
    src = PurePosixPath(source_path)
    out: set[str] = set()
    for rule in (*layout.rules, *layout.overrides):
        if rule.stem_extractor not in STEM_EXTRACTORS:
            raise ValueError(f"unknown stem_extractor: {rule.stem_extractor!r}")
        if src.name in rule.skip_basenames:
            continue
        if any(source_path.endswith(s) for s in rule.skip_suffixes):
            continue
        if any(
            _compile_source_pattern(ex).fullmatch(source_path)
            for ex in rule.source_excludes
        ):
            continue
        if not _match_any(source_path, rule.source_pattern):
            continue
        stem = STEM_EXTRACTORS[rule.stem_extractor](source_path)
        if stem is None:
            continue
        for resolved in _resolve_test_glob(rule, stem, src):
            for match in project_root.glob(resolved):
                rel = match.relative_to(project_root).as_posix()
                # Defensive: a glob hit named like a skipped basename
                # (e.g. __init__.py) should also be filtered.
                if PurePosixPath(rel).name in rule.skip_basenames:
                    continue
                out.add(rel)
    return sorted(out)

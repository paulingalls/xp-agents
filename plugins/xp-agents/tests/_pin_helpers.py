#!/usr/bin/env python3
"""Shared file-discovery infrastructure for the doctrinal/vocabulary pins.

Sister pins (`test_event_vocabulary_pin.py`,
`test_assertequal_vocabulary_pin.py`) duplicated `_files_to_scan`,
`_rel`, and the path constants. Promote here so future pins reuse the same
scan surfaces and rel-path convention. `shipped_prose_to_scan` serves the
prose-side pin (`test_shipped_prose_language_agnostic.py`), which does no AST
walking at all — the shared thing is the surface, not the walker.

Detection stays out of here because the violation shapes differ per pin
(make_event-call+dict-literal, assertEqual+type-subscript, a tool name in a
line of Markdown). Each pin owns its own pass, or — where two pins share one
rule, as the routing pins do via `_routing_detect` — a detection module beside
them. This helper owns discovery either way.
"""

import ast
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

# The shipped Python surface, relative to plugins/xp-agents/. `hooks/` is
# absent on purpose: it holds hooks.json and no Python at all.
_SHIPPED_ROOTS = ("scripts", "smm")
_SHIPPED_SKILL_SCRIPTS = "skills/*/scripts"


def files_to_scan(root: Path, exclude_self: Path) -> list[Path]:
    """Return every `.py` file at any depth under root.

    A name-shape filter (test_*.py, _*.py, conftest.py) used to gate this
    list; it silently dropped shared test-base modules with no matching
    prefix (e.g. a `sister_test_base.py`) and every `__init__.py`, both of
    which are ordinary test-tree code a pin's rule can apply to. The only
    exclusion left is the pin's own file (passed as
    `exclude_self.resolve()` — the pin asserts other files, not itself).
    """
    self_resolved = exclude_self.resolve()
    return [p for p in root.rglob("*.py") if p.resolve() != self_resolved]


def _legacy_name_shaped_files(root: Path, exclude_self: Path | None) -> list[Path]:
    """Recompute of the pre-widening test_*.py / _*.py / conftest.py rule,
    frozen here as a forward guard -- see `scan_shortfalls`."""
    self_resolved = exclude_self.resolve() if exclude_self is not None else None
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        if p.name == "__init__.py" or p.resolve() == self_resolved:
            continue
        if p.name.startswith(("test_", "_")) or p.name == "conftest.py":
            paths.append(p)
    return paths


def scan_shortfalls(
    scanned: list[Path],
    root: Path,
    min_files: int,
    exclude_self: Path | None = None,
) -> list[str]:
    """Human-readable shortfalls in *scanned*; empty when healthy.

    Two legs:
      - superset: every file the legacy name-shape predicate (test_*.py,
        _*.py, conftest.py, minus __init__.py) would select under *root*
        must still be present in *scanned*. `files_to_scan` now admits
        every .py file, so the legacy set is a subset of it by
        construction -- this leg is a tautology against the real tree.
        Its value is as a forward guard: it fires the moment a future
        change re-narrows `files_to_scan`, which the post-widening tree
        cannot itself witness.
      - floor: `len(scanned) >= min_files`.
    """
    shortfalls: list[str] = []
    scanned_resolved = {p.resolve() for p in scanned}
    missing = [
        p
        for p in _legacy_name_shaped_files(root, exclude_self)
        if p.resolve() not in scanned_resolved
    ]
    if missing:
        shown = ", ".join(sorted(str(p) for p in missing))
        shortfalls.append(
            f"{len(missing)} legacy-name-shaped file(s) missing from scan: {shown}"
        )
    if len(scanned) < min_files:
        shortfalls.append(
            f"only {len(scanned)} files scanned, expected at least {min_files}"
        )
    return shortfalls


def parse_files(
    paths: list[Path],
) -> tuple[list[tuple[Path, ast.AST]], list[tuple[Path, str]]]:
    """Parse every path in *paths*; split into successes and failures.

    A file that fails to parse is captured as `(path, str(error))` in the
    second list rather than swallowed -- callers report it as its own
    signal, distinct from "clean" (no violations found in the first list).
    """
    trees: list[tuple[Path, ast.AST]] = []
    failures: list[tuple[Path, str]] = []
    for path in paths:
        try:
            trees.append((path, ast.parse(path.read_text(encoding="utf-8"))))
        except SyntaxError as exc:
            failures.append((path, str(exc)))
    return trees, failures


_Violation = TypeVar("_Violation")


def scan_root(
    paths: list[Path],
    scan_tree: Callable[[ast.AST], list[_Violation]],
) -> tuple[dict[Path, list[_Violation]], list[tuple[Path, str]]]:
    """Run *scan_tree* over every parseable path in *paths*.

    Returns (violations keyed by path, parse-failures). A file that fails to
    parse appears ONLY in the second list -- it is never folded into the first
    as if it had been proven clean. Each pin still owns its own `scan_tree`;
    what is shared is the parse/partition step, which was identical in all
    three sister pins.
    """
    trees, parse_failures = parse_files(paths)
    violations: dict[Path, list[_Violation]] = {}
    for path, tree in trees:
        found = scan_tree(tree)
        if found:
            violations[path] = found
    return violations, parse_failures


def shipped_files_by_root(plugin_root: Path) -> dict[str, list[Path]]:
    """Every shipped Python module under *plugin_root*, grouped by the root
    it lives under: `"scripts"`, `"smm"`, or `"skills"` (each
    `skills/<name>/scripts/` directory, flattened into one group under that
    key).

    Grouped, not flattened, for the same reason as `shipped_prose_to_scan`: a
    floor over the total cannot see one group empty out.

    Nothing else is filtered out. The shipped tree carries no `__init__.py` (it
    is not a package — modules are imported off a sys.path insert), so excluding
    them would exempt a file class that does not exist while quietly narrowing
    the scan if one ever appeared.
    """
    groups: dict[str, list[Path]] = {}
    for name in _SHIPPED_ROOTS:
        root = plugin_root / name
        groups[name] = sorted(root.rglob("*.py")) if root.is_dir() else []

    skills_paths: list[Path] = []
    for root in sorted(plugin_root.glob(_SHIPPED_SKILL_SCRIPTS)):
        if root.is_dir():
            skills_paths.extend(sorted(root.rglob("*.py")))
    groups["skills"] = skills_paths

    return groups


def shipped_files_to_scan(plugin_root: Path) -> list[Path]:
    """Return every shipped Python module under *plugin_root*.

    That is `scripts/`, `smm/`, and each `skills/<name>/scripts/` — the code
    that runs in a user's project and therefore reads user-supplied paths.
    Tests are excluded: they never ship, so they are free to be Python-specific.

    The flattened concatenation of `shipped_files_by_root`, in `scripts`,
    `smm`, `skills` order, so the two agree by construction.
    """
    return [p for paths in shipped_files_by_root(plugin_root).values() for p in paths]


def shipped_prose_to_scan(plugin_root: Path) -> dict[str, list[Path]]:
    """Every shipped PROSE surface under *plugin_root*, grouped by its glob.

    The counterpart to `shipped_files_to_scan`: that one answers "which shipped
    code runs in a user's project", this one answers "which shipped text is
    injected into a user's session". Guides, agent definitions, skill bodies and
    the close-pipeline reference all reach the reader verbatim, so a Python-only
    instruction in any of them is the same assumption a Python-only predicate
    makes in code.

    Grouped, not flattened, because a floor over the total cannot see one group
    empty out: `scripts/*.md` matches exactly ONE file, so a rename would drop
    that whole surface while a tree-wide count still looked healthy. Callers
    assert per group.

    The skills glob is `skills/*/*.md`, not `skills/*/SKILL.md`: a skill's
    reference doc ships and is injected exactly like its body, so narrowing to
    the body would leave a shipped prose surface invisible the day one is added.
    Today the two globs match the same files.
    """
    return {
        "root guides": sorted(plugin_root.glob("*.md")),
        "agents": sorted((plugin_root / "agents").glob("*.md")),
        "skills": sorted(plugin_root.glob("skills/*/*.md")),
        "scripts prose": sorted((plugin_root / "scripts").glob("*.md")),
    }


def rel(path: Path, repo_root: Path) -> str:
    """Repo-relative path with forward slashes — stable across platforms."""
    return str(path.relative_to(repo_root)).replace("\\", "/")

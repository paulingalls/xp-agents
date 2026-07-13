#!/usr/bin/env python3
"""Shared infrastructure for AST-walking vocabulary pins.

Sister pins (`test_event_vocabulary_pin.py`,
`test_assertequal_vocabulary_pin.py`) duplicated `_files_to_scan`,
`_rel`, and the path constants. Promote here so future pins (a third
expected) reuse the same scan surface and rel-path convention.

Each pin keeps its own `_scan_file(path) -> list[tuple]` because the
violation shapes differ (make_event-call+dict-literal vs
assertEqual/assertNotEqual+type-subscript). The pin owns its detection
walker; this helper owns the file-discovery boilerplate.
"""

from pathlib import Path

# The shipped Python surface, relative to plugins/xp-agents/. `hooks/` is
# absent on purpose: it holds hooks.json and no Python at all.
_SHIPPED_ROOTS = ("scripts", "smm")
_SHIPPED_SKILL_SCRIPTS = "skills/*/scripts"


def files_to_scan(root: Path, exclude_self: Path) -> list[Path]:
    """Return test_*.py + _*.py + conftest.py at any depth under root.

    Excludes `__init__.py` (no event literals; package marker only) and
    the pin's own file (passed as `exclude_self.resolve()` — the pin
    asserts other files, not itself).
    """
    self_resolved = exclude_self.resolve()
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        if p.name == "__init__.py" or p.resolve() == self_resolved:
            continue
        if p.name.startswith(("test_", "_")) or p.name == "conftest.py":
            paths.append(p)
    return paths


def shipped_files_to_scan(plugin_root: Path) -> list[Path]:
    """Return every shipped Python module under *plugin_root*.

    That is `scripts/`, `smm/`, and each `skills/<name>/scripts/` — the code
    that runs in a user's project and therefore reads user-supplied paths.
    Tests are excluded: they never ship, so they are free to be Python-specific.
    Excludes `__init__.py` (package markers carry no logic).
    """
    roots = [plugin_root / r for r in _SHIPPED_ROOTS]
    roots.extend(sorted(plugin_root.glob(_SHIPPED_SKILL_SCRIPTS)))

    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        paths.extend(p for p in sorted(root.rglob("*.py")) if p.name != "__init__.py")
    return paths


def rel(path: Path, repo_root: Path) -> str:
    """Repo-relative path with forward slashes — stable across platforms."""
    return str(path.relative_to(repo_root)).replace("\\", "/")

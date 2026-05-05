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


def rel(path: Path, repo_root: Path) -> str:
    """Repo-relative path with forward slashes — stable across platforms."""
    return str(path.relative_to(repo_root)).replace("\\", "/")

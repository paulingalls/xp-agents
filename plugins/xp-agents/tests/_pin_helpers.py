#!/usr/bin/env python3
"""Shared file-discovery infrastructure for the doctrinal/vocabulary pins.

Sister pins (`test_event_vocabulary_pin.py`,
`test_assertequal_vocabulary_pin.py`) duplicated `_files_to_scan`,
`_rel`, and the path constants. Promote here so future pins reuse the same
scan surfaces and rel-path convention. `shipped_prose_to_scan` serves the
prose-side pin (`test_shipped_prose_language_agnostic.py`), which does no AST
walking at all — the shared thing is the surface, not the walker.

Each pin keeps its own detection pass because the violation shapes differ
(make_event-call+dict-literal, assertEqual+type-subscript, a tool name in a
line of Markdown). The pin owns detection; this helper owns discovery.
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

    Nothing else is filtered out. The shipped tree carries no `__init__.py` (it
    is not a package — modules are imported off a sys.path insert), so excluding
    them would exempt a file class that does not exist while quietly narrowing
    the scan if one ever appeared.
    """
    roots = [plugin_root / r for r in _SHIPPED_ROOTS]
    roots.extend(sorted(plugin_root.glob(_SHIPPED_SKILL_SCRIPTS)))

    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        paths.extend(sorted(root.rglob("*.py")))
    return paths


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

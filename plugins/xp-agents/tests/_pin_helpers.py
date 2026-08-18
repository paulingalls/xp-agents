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


def shipped_shell_to_scan(plugin_root: Path) -> list[Path]:
    """Every shipped shell script under *plugin_root*, at any depth.

    Selected by SUFFIX, not by enumerated location, and that is the whole
    design. `shipped_files_to_scan` above can enumerate roots because a Python
    module outside them is not shipped code; shell has no such invariant --
    preloads live in `skills/`, `skills/*/scripts/`, and `smm/`, and the next
    one may live somewhere none of those globs anticipated. A size gate whose
    scope is narrower than it claims is the exact defect this scan exists to
    close (docs/ideas/1-VERIFY_GATE_COVERAGE.md §5); enumerating globs here
    would reproduce it one level down, invisibly, because no floor can fire for
    a surface that never existed. Over-inclusion is the safe direction: the
    line cap is a project convention that applies to any file, so governing a
    shell script in a new location is right, not a false positive.

    `tests/` is excluded -- it never ships. Keyed on the FIRST path segment
    rather than membership, so a legitimately shipped `skills/foo/tests/x.sh`
    is still governed.

    Flat, unlike `shipped_prose_to_scan` below: that one groups because a floor
    over its total cannot see one glob empty out. There is only one selector
    here, so there is no glob left to drop and nothing for a group to protect.
    """
    return sorted(
        p
        for p in plugin_root.rglob("*.sh")
        if p.relative_to(plugin_root).parts[0] != "tests"
    )


def shipped_js_to_scan(plugin_root: Path) -> list[Path]:
    """Every shipped JavaScript file under *plugin_root*, at any depth.

    A third surface, arriving with the broad-review Workflow script. Selected by
    SUFFIX for the reason `shipped_shell_to_scan` argues above and not repeated
    here: an enumerated glob cannot fire for a location that does not exist yet,
    so it reproduces the coverage gap one level down.

    This one needed the gate MORE than shell did, not less. A `.js` in this repo
    is reached by no linter, no formatter, no type checker and no prose sweep --
    `lefthook.yml` globs `.py`, `.sh` and `.json`, and there is no JS toolchain.
    Before this the line cap and band ratchet did not see one either, while
    `test_file_size_pin`'s own docstring called itself tree-wide. That overclaim
    was paid for once already when shell was discovered to be unscanned.

    Its BEHAVIOUR is covered separately, by `test_workflow_js_suite.py` driving
    `node --test`. Size and behaviour are different questions and neither
    substitutes for the other -- a 700-line orchestrator can pass every one of
    its own tests.

    `tests/` is excluded on the first path segment, exactly as above, so the
    harness and its fixtures are not governed as shipped code -- but they ARE
    governed, by `tests_tree_js_to_scan` below rather than by widening this function,
    which answers "which shipped code runs in a user's project". The tests/ legs
    scan `.py` only, so without that sibling the four `.js` files under
    `tests/workflows/` would sit outside both the cap and the band ratchet, and
    the largest is already within ten lines of the cap.
    """
    return sorted(
        p
        for p in plugin_root.rglob("*.js")
        if p.relative_to(plugin_root).parts[0] != "tests"
    )


def tests_tree_js_to_scan(tests_root: Path) -> list[Path]:
    """Every JavaScript file at any depth under the *tests* tree.

    The counterpart to `files_to_scan` for the suffix it does not select. Tests
    are production code under this project's own constraint, so the same cap and
    the same ratchet apply -- and the `.js` under `tests/` is not a two-line
    fixture: the workflow suite is the largest JavaScript file in the tree.

    Suffix at any depth, never an enumerated location, for the reason
    `shipped_shell_to_scan` argues: `tests/workflows/` is where the JS lives
    today and a glob naming it cannot fire for wherever the next one lands.

    NOT named `test_js_to_scan`: this module is imported INTO `test_*.py`
    modules, and pytest collects a `test_`-prefixed callable out of a test
    module's namespace whatever file it was defined in -- it would be collected
    as a test and error on a missing `tests_root` fixture.
    """
    return sorted(tests_root.rglob("*.js"))


def shipped_prose_to_scan(plugin_root: Path) -> dict[str, list[Path]]:
    """Every shipped PROSE surface under *plugin_root*, grouped by its glob.

    The counterpart to `shipped_files_to_scan`: that one answers "which shipped
    code runs in a user's project", this one answers "which shipped text is
    injected into a user's session". Guides, agent definitions, skill bodies and
    the close-pipeline reference all reach the reader verbatim, so a Python-only
    instruction in any of them is the same assumption a Python-only predicate
    makes in code.

    Grouped, not flattened, because a floor over the total cannot see one group
    empty out: the smallest group is a handful of files, so a rename could drop
    a whole surface while a tree-wide count still looked healthy. Callers assert
    per group.

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

#!/usr/bin/env python3
"""The AST walker behind the event-vocabulary pin: matchers and file scanner.

Extracted from `test_event_vocabulary_pin.py` when it hit 577 lines. Sister
module to `_env_patch_walker.py`, and the same split for the same reason: the
pin asserts zero violations on the real tree, while a separate suite points this
scanner at synthetic files to prove it can actually fail.

THE RULE it implements is documented on the pin itself. This module is the
mechanism.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _pin_helpers import files_to_scan as _files_to_scan_impl
from _pin_helpers import rel as _rel_impl
from _pin_helpers import scan_root
from event_schema import VALID_TYPES

TESTS_ROOT = Path(__file__).parent.parent  # plugins/xp-agents/tests/
REPO_ROOT = TESTS_ROOT.parent.parent.parent  # repo root for stable rel paths

VALID_TYPES_SET = frozenset(VALID_TYPES)

# The PIN's own file, which `files_to_scan` excludes -- "the pin asserts other
# files, not itself". Named explicitly rather than reached via `__file__`,
# because `__file__` follows the code: with the scanner living here it would
# exclude THIS module instead, silently dropping a scanned file while the pin's
# own file quietly became scannable. Neither direction shows up as a red test.
PIN_FILE = Path(__file__).parent / "test_event_vocabulary_pin.py"


def _make_event_call_aliases(tree: ast.AST) -> set[str]:
    """Find every local name that binds to make_event via import.

    Catches `from _event_fixtures import make_event as me` so a later
    `me("concern", ...)` call is matched. Always includes the canonical
    name `make_event`.
    """
    aliases = {"make_event"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "make_event":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _fixture_module_names(tree: ast.AST) -> set[str]:
    """Find every local name bound to a fixture module via import.

    A fixture module is any module whose name ends with `_fixtures`
    (e.g., `_event_fixtures`, `_close_fixtures`). Returns the set of
    local names — the alias if used, otherwise the bare module name.

    Used to tighten Attribute matching: `h.make_event(...)` is only a
    pin violation when `h` is a fixture-module reference, not just any
    object with a `.make_event` method (e.g., mocks or self).
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                if alias.name.endswith("_fixtures"):
                    names.add(alias.asname or alias.name)
    return names


def _scan_tree(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Return (lineno, value, kind) violations for one already-parsed tree.

    Kinds: `make_event-call`, `dict-literal`. Empty list = clean.
    """
    aliases = _make_event_call_aliases(tree)
    fixture_modules = _fixture_module_names(tree)
    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name: str | None = None
            match node.func:
                case ast.Name(id=name) if name in aliases:
                    func_name = name
                case ast.Attribute(attr="make_event", value=ast.Name(id=mod)) if (
                    mod in fixture_modules
                ):
                    func_name = "make_event"
                case _:
                    pass
            if func_name:
                type_arg: ast.expr | None = None
                if node.args:
                    type_arg = node.args[0]
                else:
                    for kw in node.keywords:
                        if kw.arg == "event_type":
                            type_arg = kw.value
                            break
                if (
                    isinstance(type_arg, ast.Constant)
                    and isinstance(type_arg.value, str)
                    and type_arg.value in VALID_TYPES_SET
                ):
                    violations.append(
                        (type_arg.lineno, type_arg.value, "make_event-call")
                    )

        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "type"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and value.value in VALID_TYPES_SET
                ):
                    violations.append((value.lineno, value.value, "dict-literal"))

    return violations


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, value, kind) violations for one file. Empty = clean.

    A SyntaxError propagates -- a file this cannot parse is a different
    signal than "clean" (see `_scan_root`, which scanning-a-tree callers
    should use instead).
    """
    return _scan_tree(ast.parse(path.read_text(encoding="utf-8")))


def _scan_root(
    root: Path,
) -> tuple[dict[Path, list[tuple[int, str, str]]], list[tuple[Path, str]]]:
    """Scan every file `files_to_scan` admits under *root*.

    Returns (violations keyed by absolute path, parse-failures) -- see
    `_pin_helpers.scan_root` for the split, which the sister pins share.
    """
    return scan_root(_files_to_scan(root), _scan_tree)


def _count_event_type_sites_in_tree(tree: ast.AST) -> int:
    """Count make_event calls (any first arg) plus dict `"type"` literals
    (any string value) -- the population this pin draws from, for the
    non-vacuity floor. Broader than `_scan_tree`'s VALID_TYPES_SET filter
    on purpose: most sites here are canonical, not violations."""
    aliases = _make_event_call_aliases(tree)
    fixture_modules = _fixture_module_names(tree)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            match node.func:
                case ast.Name(id=name) if name in aliases:
                    count += 1
                case ast.Attribute(attr="make_event", value=ast.Name(id=mod)) if (
                    mod in fixture_modules
                ):
                    count += 1
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "type"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    count += 1
    return count


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _files_to_scan(root: Path) -> list[Path]:
    return _files_to_scan_impl(root, PIN_FILE)

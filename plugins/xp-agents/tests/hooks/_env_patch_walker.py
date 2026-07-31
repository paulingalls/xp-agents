#!/usr/bin/env python3
"""The AST walker behind the env-patch-cleanup pin: matchers and file scanner.

Extracted from `test_env_patch_cleanup_pin.py`, which had grown to 955 lines
holding three separable things: this scanner, the tree-wide pin that runs it,
and the shape tests that prove it fires. The scanner is the reusable part -- the
pin asserts zero violations on the real tree, and two sibling suites point it at
synthetic files to prove it can actually fail.

THE RULE it implements, and the discriminator that makes the last safe row
precise, are documented on the pin itself. This module is the mechanism.
"""

import ast
import sys
from pathlib import Path
from typing import TypeGuard, TypeVar

sys.path.insert(0, str(Path(__file__).parent.parent))

from _pin_helpers import files_to_scan as _files_to_scan_impl
from _pin_helpers import rel as _rel_impl
from _pin_helpers import scan_root

TESTS_ROOT = Path(__file__).parent.parent  # plugins/xp-agents/tests/
REPO_ROOT = TESTS_ROOT.parent.parent.parent  # repo root for stable rel paths

# The PIN's own file, which `files_to_scan` excludes -- "the pin asserts other
# files, not itself". Named explicitly rather than reached via `__file__`,
# because `__file__` follows the code: with the scanner living here it would
# exclude THIS module instead, silently dropping a scanned file while the pin's
# own file quietly became scannable. That swap is invisible to a green suite,
# which is why the constant is spelled out.
PIN_FILE = Path(__file__).parent / "test_env_patch_cleanup_pin.py"


# ---------------------------------------------------------------------------
# AST shape matchers
# ---------------------------------------------------------------------------


def _patch_name_aliases(tree: ast.AST) -> set[str]:
    """Find every local name that binds to `unittest.mock.patch` via import.

    Catches `from unittest.mock import patch as p` so a later `p.dict(...)`
    call is matched. Always includes the canonical name `patch`.
    """
    aliases = {"patch"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in (
            "unittest.mock",
            "mock",
        ):
            for alias in node.names:
                if alias.name == "patch":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _is_patch_dict_attr(func: ast.expr, patch_aliases: set[str]) -> bool:
    """True for the callee of `patch.dict(...)` (any import alias of
    `patch`) or `mock.patch.dict(...)`."""
    if not (isinstance(func, ast.Attribute) and func.attr == "dict"):
        return False
    base = func.value
    if isinstance(base, ast.Name) and base.id in patch_aliases:
        return True
    return isinstance(base, ast.Attribute) and base.attr == "patch"


def _is_os_environ(node: ast.expr) -> bool:
    """True for the `os.environ` expression, or the equivalent `"os.environ"`
    string target `patch.dict` resolves by import."""
    if isinstance(node, ast.Constant):
        return node.value == "os.environ"
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _patch_dict_target(call: ast.Call) -> ast.expr | None:
    """The mapping `patch.dict` will patch: first positional, or `in_dict=`."""
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "in_dict":
            return kw.value
    return None


def _is_env_patch_call(node: ast.AST, patch_aliases: set[str]) -> TypeGuard[ast.Call]:
    """True for `patch.dict(os.environ, ...)` / `mock.patch.dict(os.environ, ...)`,
    under any import alias of `patch` collected in *patch_aliases*."""
    if not (
        isinstance(node, ast.Call) and _is_patch_dict_attr(node.func, patch_aliases)
    ):
        return False
    target = _patch_dict_target(node)
    return target is not None and _is_os_environ(target)


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


_Node = TypeVar("_Node", bound=ast.AST)


def _enclosing(
    node: ast.AST, parents: dict[ast.AST, ast.AST], types: tuple[type[_Node], ...]
) -> _Node | None:
    """Nearest ancestor of *node* that is one of *types* — typed as that node
    class, so callers read `.body`/`.name` without an isinstance crutch."""
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, types):
            return cur
        cur = parents.get(cur)
    return None


def _self_stop_call(node: ast.AST, attr_name: str) -> bool:
    """True for a Call node matching `self.<attr_name>.stop()`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stop"
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
        and node.func.value.attr == attr_name
    )


def _single_assign_target(parent: ast.AST | None, call: ast.Call) -> ast.expr | None:
    """The lone target *call* is bound to, for `x = call` and `x: T = call`."""
    if (
        isinstance(parent, ast.Assign)
        and len(parent.targets) == 1
        and parent.value is call
    ):
        return parent.targets[0]
    if isinstance(parent, ast.AnnAssign) and parent.value is call:
        return parent.target
    return None


def _has_teardown_stop(
    node: ast.AST, parents: dict[ast.AST, ast.AST], attr_name: str
) -> bool:
    """True if the class containing *node* calls `self.<attr_name>.stop()`
    inside a method literally named `tearDown`."""
    cls = _enclosing(node, parents, (ast.ClassDef,))
    if cls is None:
        return False
    for item in cls.body:
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "tearDown"
            and any(_self_stop_call(n, attr_name) for n in ast.walk(item))
        ):
            return True
    return False


def _enclosing_cleanup_sink(
    call: ast.AST, parents: dict[ast.AST, ast.AST]
) -> str | None:
    """If *call* is passed directly as an argument to `self.enterContext(...)`
    or `self.addCleanup(...)`, return that method's name; else None."""
    parent = parents.get(call)
    if not (isinstance(parent, ast.Call) and call in parent.args):
        return None
    func = parent.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
        and func.attr in ("enterContext", "addCleanup")
    ):
        return func.attr
    return None


def _classify_call(
    call: ast.Call, parents: dict[ast.AST, ast.AST]
) -> tuple[int, str] | None:
    """Return a (lineno, reason) violation for *call*, or None if safe."""
    parent = parents.get(call)

    if isinstance(parent, ast.withitem) and parent.context_expr is call:
        return None

    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (
        call in parent.decorator_list
    ):
        return None

    if isinstance(parent, ast.Return) and parent.value is call:
        return None

    target = _single_assign_target(parent, call)
    if target is not None:
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            attr_name = target.attr
            if _has_teardown_stop(call, parents, attr_name):
                return None
            return (
                call.lineno,
                f"self.{attr_name} = patch.dict(os.environ, ...) but no "
                f"self.{attr_name}.stop() is called inside a tearDown in "
                f"the same class",
            )
        if isinstance(target, ast.Name):
            return (
                call.lineno,
                f"patch.dict(os.environ, ...) assigned to local variable "
                f"'{target.id}' -- its cleanup is not bounded by the test "
                f"method (use `with`, a decorator, `return`, or "
                f"self.<attr> plus a tearDown().stop())",
            )
        return (
            call.lineno,
            "patch.dict(os.environ, ...) assigned to a compound target "
            "whose cleanup cannot be bounded to the test method",
        )

    sink = _enclosing_cleanup_sink(call, parents)
    if sink:
        return (
            call.lineno,
            f"{sink}(patch.dict(os.environ, ...)) exits AFTER tearDown, "
            f"restoring the whole os.environ mapping and reinstating "
            f"whatever tearDown had already popped",
        )
    return (
        call.lineno,
        "patch.dict(os.environ, ...) used outside a `with`, a decorator, "
        "or a `return` -- its cleanup is not bounded by the test method",
    )


def _helper_names_returning_env_patch(
    env_patch_calls: list[ast.Call], parents: dict[ast.AST, ast.AST]
) -> set[str]:
    """Names of functions/methods whose body directly `return`s a
    `patch.dict(os.environ, ...)` call."""
    names: set[str] = set()
    for call in env_patch_calls:
        parent = parents.get(call)
        if isinstance(parent, ast.Return) and parent.value is call:
            func = _enclosing(call, parents, (ast.FunctionDef, ast.AsyncFunctionDef))
            if func is not None:
                names.add(func.name)
    return names


def _helper_indirection_violations(
    tree: ast.AST, helper_names: set[str]
) -> list[tuple[int, str]]:
    """Flag `self.enterContext(helper())` / `self.addCleanup(helper())` where
    `helper` is a name bound (by `return`) to an env patcher."""
    if not helper_names:
        return []
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
            continue
        if node.func.attr not in ("enterContext", "addCleanup"):
            continue
        for arg in node.args:
            if not isinstance(arg, ast.Call):
                continue
            callee = arg.func
            name: str | None = None
            if isinstance(callee, ast.Name):
                name = callee.id
            elif (
                isinstance(callee, ast.Attribute)
                and isinstance(callee.value, ast.Name)
                and callee.value.id == "self"
            ):
                name = callee.attr
            if name in helper_names:
                violations.append(
                    (
                        node.lineno,
                        f"{node.func.attr}({name}()) -- {name} returns a "
                        f"patch.dict(os.environ, ...) patcher whose cleanup "
                        f"escapes the test method through this indirection",
                    )
                )
    return violations


def _scan_tree(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, reason) violations for one already-parsed tree."""
    parents = _build_parent_map(tree)
    patch_aliases = _patch_name_aliases(tree)
    env_patch_calls = [
        n for n in ast.walk(tree) if _is_env_patch_call(n, patch_aliases)
    ]

    violations: list[tuple[int, str]] = []
    for call in env_patch_calls:
        result = _classify_call(call, parents)
        if result is not None:
            violations.append(result)

    helper_names = _helper_names_returning_env_patch(env_patch_calls, parents)
    violations.extend(_helper_indirection_violations(tree, helper_names))

    return sorted(violations)


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, reason) violations for one file. Empty = clean.

    A SyntaxError propagates -- a file this cannot parse is a different
    signal than "clean" and must not be reported as either (see
    `_scan_root`, which callers scanning a whole tree should use instead).
    """
    return _scan_tree(ast.parse(path.read_text(encoding="utf-8")))


def _scan_root(
    root: Path,
) -> tuple[dict[Path, list[tuple[int, str]]], list[tuple[Path, str]]]:
    """Scan every file `files_to_scan` admits under *root*.

    Returns (violations keyed by absolute path, parse-failures) -- see
    `_pin_helpers.scan_root` for the split, which the sister pins share.
    """
    return scan_root(_files_to_scan(root), _scan_tree)


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _files_to_scan(root: Path) -> list[Path]:
    return _files_to_scan_impl(root, PIN_FILE)

#!/usr/bin/env python3
"""Doctrinal pin: forbid `patch.dict(os.environ, ...)` cleanup that outlives
`tearDown` under xdist.

Debt eaf94a1afefc. `self.enterContext(patch.dict(os.environ, ...))` and the
`addCleanup`-of-a-detached-patcher shape both register cleanup that unittest
runs AFTER `tearDown` returns. On an xdist worker that reuses the process
across tests, `patch.dict`'s exit restores the *whole* `os.environ` mapping
as it stood at entry -- including `SMM_DIR`, which `tearDown` had already
popped. The next test in that worker then reads a `SMM_DIR` pointing at a
deleted temp directory.

This was fixed once with a prose warning left at the site (see the class
docstring in `test_heartbeat_writers.py`) and reintroduced 35 lines away in
the SAME file within the hour. A prose warning is the wrong guard for a
mechanically detectable AST shape; this pin is the mechanical guard.

THE RULE. A `patch.dict` call whose first argument is `os.environ` is safe
only in a position whose cleanup is bounded by the test method:

    with patch.dict(os.environ, ...):            safe -- exits in the body
    with (patch.dict(os.environ, ...), other()):  safe -- same, multi-item
    @patch.dict(os.environ, ...)                  safe -- scoped to the method
    def helper():
        return patch.dict(os.environ, ...)        safe -- caller's `with` bounds it
    self._p = patch.dict(os.environ, ...)          safe -- ONLY IF self._p.stop()
    # in setUp, self._p.start()                    is CALLED inside a tearDown
    # in tearDown, self._p.stop()                  in the same class
    anything else                                  FLAGGED

THE DISCRIMINATOR for the last safe row: `.stop()` must be *called* inside
`tearDown`, not merely hand off `.stop` to `addCleanup` (`addCleanup` fires
after `tearDown`, which is exactly the bug). Get this precise, or the pin
either misses `enterContext`/`addCleanup` reintroduced under a self-attr
disguise, or flags the legitimate `test_worktree_removal.py`-style pattern
this row exists to allow.

Fail-closed by design: anything not matching an enumerated safe row is
flagged, including shapes nobody has written yet.

HELPER INDIRECTION. A local helper that itself `return`s a safe
`patch.dict(os.environ, ...)` (safe by the `return` row above) can still be
misused by its CALLER: `self.enterContext(helper())` re-introduces the exact
bug through one layer of indirection. Catching this needs a within-module
pass: collect names of functions that `return` an env patcher, then flag any
`self.enterContext(...)`/`self.addCleanup(...)` call whose argument is a
call to one of those names. One real helper in the tree today
(`test_tdd_gate_in_place_teammate.py`'s `_in_place_env`) is consumed safely,
via `with self._in_place_env():`, in the same module -- so within-module
scope is sufficient; nothing here resolves a helper imported from elsewhere.

KNOWN GAPS (booked as debt 8dffcbf90181, not fixed here): an aliased import
(`from unittest.mock import patch as p`) evades `_is_patch_dict_attr`'s
name check, and a helper defined in one module but called from another
evades the within-module indirection pass. This pin is a floor, not total
coverage.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _pin_helpers import files_to_scan as _files_to_scan_impl
from _pin_helpers import rel as _rel_impl

TESTS_ROOT = Path(__file__).parent.parent  # plugins/xp-agents/tests/
REPO_ROOT = TESTS_ROOT.parent.parent.parent  # repo root for stable rel paths

# Files allowlisted from the pin. Each entry's value must justify why the
# unbounded patch.dict is intentional -- auditable via grep on this dict.
# Deliberately empty: the tree passes this pin outright (AC#5). Keying an
# allowlist on whole file path would exempt the entire file the debt's
# reintroduction actually happened in -- exactly the failure mode this pin
# exists to catch. If you're adding an entry here, the rule is wrong; fix
# the rule instead.
ALLOWLIST: dict[str, str] = {}


# ---------------------------------------------------------------------------
# AST shape matchers
# ---------------------------------------------------------------------------


def _is_patch_dict_attr(func: ast.expr) -> bool:
    """True for the callee of `patch.dict(...)` or `mock.patch.dict(...)`."""
    if not (isinstance(func, ast.Attribute) and func.attr == "dict"):
        return False
    base = func.value
    if isinstance(base, ast.Name) and base.id == "patch":
        return True
    return isinstance(base, ast.Attribute) and base.attr == "patch"


def _is_os_environ(node: ast.expr) -> bool:
    """True for the `os.environ` expression."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_env_patch_call(node: ast.AST) -> bool:
    """True for `patch.dict(os.environ, ...)` / `mock.patch.dict(os.environ, ...)`."""
    return (
        isinstance(node, ast.Call)
        and _is_patch_dict_attr(node.func)
        and bool(node.args)
        and _is_os_environ(node.args[0])
    )


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing(
    node: ast.AST, parents: dict[ast.AST, ast.AST], types: tuple[type, ...]
) -> ast.AST | None:
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


def _has_teardown_stop(
    assign: ast.Assign, parents: dict[ast.AST, ast.AST], attr_name: str
) -> bool:
    """True if the class containing *assign* calls `self.<attr_name>.stop()`
    inside a method literally named `tearDown`."""
    cls = _enclosing(assign, parents, (ast.ClassDef,))
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

    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
        call in parent.decorator_list
    ):
        return None

    if isinstance(parent, ast.Return) and parent.value is call:
        return None

    if (
        isinstance(parent, ast.Assign)
        and len(parent.targets) == 1
        and parent.value is call
    ):
        target = parent.targets[0]
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            attr_name = target.attr
            if _has_teardown_stop(parent, parents, attr_name):
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


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, reason) violations for one file. Empty = clean.

    Syntax errors return [] -- they're a different bug class.
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    parents = _build_parent_map(tree)
    env_patch_calls = [n for n in ast.walk(tree) if _is_env_patch_call(n)]

    violations: list[tuple[int, str]] = []
    for call in env_patch_calls:
        assert isinstance(call, ast.Call)
        result = _classify_call(call, parents)
        if result is not None:
            violations.append(result)

    helper_names = _helper_names_returning_env_patch(env_patch_calls, parents)
    violations.extend(_helper_indirection_violations(tree, helper_names))

    return sorted(violations)


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _files_to_scan(root: Path) -> list[Path]:
    return _files_to_scan_impl(root, Path(__file__))


# ---------------------------------------------------------------------------
# The pin
# ---------------------------------------------------------------------------


class TestEnvPatchCleanupPin(unittest.TestCase):
    """No unbounded patch.dict(os.environ, ...) cleanup in tests/."""

    def test_no_env_patch_cleanup_leaks_in_tests(self) -> None:
        violations: dict[str, list[tuple[int, str]]] = {}
        for py_file in _files_to_scan(TESTS_ROOT):
            rel = _rel(py_file)
            if rel in ALLOWLIST:
                continue
            file_violations = _scan_file(py_file)
            if file_violations:
                violations[rel] = file_violations

        if violations:
            lines = [
                f"  {path}:{ln}: {reason}"
                for path, vs in sorted(violations.items())
                for ln, reason in vs
            ]
            self.fail(
                f"{sum(len(v) for v in violations.values())} unbounded "
                f"patch.dict(os.environ, ...) cleanup site(s) found:\n"
                + "\n".join(lines)
            )

    def test_allowlist_entries_have_justifications(self) -> None:
        for path, justification in ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                msg=f"ALLOWLIST['{path}'] has empty justification",
            )


# ---------------------------------------------------------------------------
# Walker: detects (AC#1, AC#2, AC#6, plus shapes the AC list names by example)
# ---------------------------------------------------------------------------


class TestWalkerDetectsViolations(unittest.TestCase):
    def test_detects_entercontext_direct(self) -> None:
        """AC#1: self.enterContext(patch.dict(os.environ, ...)) flags,
        naming file and line."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(patch.dict(os.environ, {"X": "1"}))\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, reason = violations[0]
            self.assertEqual(lineno, 6)
            self.assertIn("enterContext", reason)

    def test_detects_addcleanup_of_local_var_patcher(self) -> None:
        """AC#2: patcher = patch.dict(os.environ, ...); addCleanup(patcher.stop)
        flags -- position-based: assignment to a bare local variable is
        never a safe row, regardless of downstream use."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        patcher = patch.dict(os.environ, {"X": "1"})\n'
                "        self.addCleanup(patcher.stop)\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, reason = violations[0]
            self.assertEqual(lineno, 6)
            self.assertIn("local variable", reason)

    def test_detects_bare_expression_statement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        patch.dict(os.environ, {"X": "1"})\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][0], 6)

    def test_detects_dotted_mock_patch_dict_spelling(self) -> None:
        """11 real call sites use `mock.patch.dict(os.environ, ...)`;
        missing this spelling would miss them."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "import unittest.mock as mock\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(mock.patch.dict(os.environ, {"X": "1"}))\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)

    def test_detects_entercontext_on_helper_returning_patcher(self) -> None:
        """AC#6: a helper whose returned patcher is passed to enterContext
        is flagged -- the helper's own `return` is safe on its own, but the
        caller's indirection through enterContext is not."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def _env_patch(self):\n"
                '        return patch.dict(os.environ, {"X": "1"})\n'
                "    def test_x(self):\n"
                "        self.enterContext(self._env_patch())\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, reason = violations[0]
            self.assertEqual(lineno, 8)
            self.assertIn("_env_patch", reason)

    def test_ignores_patch_dict_on_other_mapping(self) -> None:
        """patch.dict(some_other_dict, ...) is out of scope entirely."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(patch.dict({"a": "1"}, {"a": "2"}))\n'
            )
            self.assertEqual(_scan_file(tmp), [])


# ---------------------------------------------------------------------------
# Walker: ignores (AC#3, AC#4)
# ---------------------------------------------------------------------------


class TestWalkerIgnoresSafeShapes(unittest.TestCase):
    def test_ignores_with_single_item(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        with patch.dict(os.environ, {"X": "1"}):\n'
                "            pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_with_multi_item_form(self) -> None:
        """Reconstructs test_lead_gates.py:296 / test_identity.py:465's
        `with (patch.dict(os.environ, ...), other()):` shape -- a naive
        implementation that only checks `With.items[0]` breaks here."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        with (\n"
                '            patch.dict(os.environ, {"X": "1"}, clear=False),\n'
                "            self._spawned(),\n"
                "        ):\n"
                "            pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_decorator(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                '    @patch.dict(os.environ, {"X": "1"})\n'
                "    def test_x(self):\n"
                "        pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_helper_return_consumed_via_with(self) -> None:
        """Reconstructs test_tdd_gate_in_place_teammate.py's `_in_place_env`
        shape: `return patch.dict(...)` consumed via `with self._x():`."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def _env_patch(self):\n"
                '        return patch.dict(os.environ, {"X": "1"})\n'
                "    def test_x(self):\n"
                "        with self._env_patch():\n"
                "            pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_ignores_self_attr_started_in_setup_stopped_in_teardown(self) -> None:
        """AC#4: reconstructs test_worktree_removal.py:137's exact shape --
        `self._p = patch.dict(os.environ, ...)` + `.start()` in setUp,
        `.stop()` called inside tearDown in the same class."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_clean.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._smm_patch = patch.dict(os.environ, {"X": "1"})\n'
                "        self._smm_patch.start()\n"
                "    def tearDown(self):\n"
                "        self._smm_patch.stop()\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            self.assertEqual(_scan_file(tmp), [])

    def test_flags_self_attr_without_teardown_stop(self) -> None:
        """Negative control for the row above: the self.<attr> assignment
        shape alone is not enough -- .stop() must actually be CALLED inside
        tearDown, or it is exactly as unbounded as any other assignment."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._p = patch.dict(os.environ, {"X": "1"})\n'
                "        self._p.start()\n"
                "    def tearDown(self):\n"
                "        pass\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertIn("tearDown", violations[0][1])

    def test_addcleanup_handed_stop_is_still_flagged_not_confused_for_safe_row(
        self,
    ) -> None:
        """The discriminator: handing `self._p.stop` to `addCleanup` (fires
        AFTER tearDown) must not be confused with CALLING `self._p.stop()`
        inside tearDown (the actual safe row)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def setUp(self):\n"
                '        self._p = patch.dict(os.environ, {"X": "1"})\n'
                "        self._p.start()\n"
                "        self.addCleanup(self._p.stop)\n"
                "    def test_x(self):\n"
                "        pass\n"
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertIn("tearDown", violations[0][1])


# ---------------------------------------------------------------------------
# Anti-vacuity
# ---------------------------------------------------------------------------


class TestPinIsNotVacuous(unittest.TestCase):
    """A pin over an empty or near-empty population passes forever and
    proves nothing -- see CLAUDE.md's project-agnostic guardrail case study
    and this story's own debt bcbca... reintroduction history."""

    def test_scan_visits_a_nontrivial_number_of_files(self) -> None:
        scanned = _files_to_scan(TESTS_ROOT)
        self.assertGreaterEqual(
            len(scanned),
            400,
            msg=(
                f"only {len(scanned)} files scanned -- check "
                f"_pin_helpers.files_to_scan and TESTS_ROOT"
            ),
        )

    def test_scan_examines_a_nontrivial_number_of_call_sites(self) -> None:
        total = 0
        for py_file in _files_to_scan(TESTS_ROOT):
            src = py_file.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            total += sum(1 for n in ast.walk(tree) if _is_env_patch_call(n))
        self.assertGreaterEqual(
            total,
            100,
            msg=(
                f"only {total} patch.dict(os.environ, ...) call sites found "
                f"-- the detection shape may have gone blind"
            ),
        )

    def test_shipped_code_is_not_scanned(self) -> None:
        """The pin scans plugins/xp-agents/tests/ only -- it must never
        reach scripts/, smm/, or skills/*/scripts, which ship to users and
        are covered by a different, language-agnostic pin instead."""
        rels = [_rel(p) for p in _files_to_scan(TESTS_ROOT)]
        self.assertTrue(rels)
        self.assertTrue(all("/tests/" in r for r in rels))

    def test_pin_can_actually_fail(self) -> None:
        """The main pin test asserts zero violations on the real tree, which
        is indistinguishable from a scanner that never runs. Prove the
        scanner fires by pointing it at the same real-world violation shape
        pinned in TestWalkerDetectsViolations, outside TESTS_ROOT."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import os\n"
                "import unittest\n"
                "from unittest.mock import patch\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        self.enterContext(patch.dict(os.environ, {"X": "1"}))\n'
            )
            self.assertNotEqual(_scan_file(tmp), [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Doctrinal pin: forbid bare event-type literals in assertEqual/assertNotEqual.

Sister pin to `test_event_vocabulary_pin.py`. The make_event-based pin
flags `make_event("concern", ...)` and `{"type": "concern"}` dicts, but
misses the assertion-side pattern:

    self.assertEqual(event["type"], "concern")     # non-canonical
    self.assertEqual(event.get("type"), "status")  # non-canonical

These bypass the make_event pin AND a grep on `e['type']==literal`.
Canonical form uses the `EVENT_TYPE_*` constant from `event_schema`:

    self.assertEqual(event["type"], EVENT_TYPE_CONCERN)

Walks the test tree via AST, looking for assertEqual/assertNotEqual
calls where one arg is a `<x>["type"]` or `<x>.get("type")` access AND
the other arg is a bare string literal in `VALID_TYPES`.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from event_schema import VALID_TYPES

TESTS_ROOT = Path(__file__).parent.parent  # plugins/xp-agents/tests/
REPO_ROOT = TESTS_ROOT.parent.parent.parent  # repo root for stable rel paths

VALID_TYPES_SET = frozenset(VALID_TYPES)

# Files allowlisted from the pin. Each entry's value must justify why
# the bare literal is intentional — auditable via grep on this dict.
ALLOWLIST: dict[str, str] = {
    # The event vocabulary pin's own tests assert on synthetic violation
    # files containing bare event-type literals — those are test inputs,
    # not test assertions, but the AST shape can match if the synthetic
    # file's assertEqual call gets parsed by THIS pin.
    "plugins/xp-agents/tests/hooks/test_event_vocabulary_pin.py": (
        "Assertions about synthetic violation files intentionally use "
        "bare literals to assert what the OTHER pin found"
    ),
    # The assertEqual vocabulary pin's own tests — same reason.
    "plugins/xp-agents/tests/hooks/test_assertequal_vocabulary_pin.py": (
        "Self-tests for THIS pin assert on synthetic violations using bare literals"
    ),
    # SMM pillar 'type' field is governed by smm_schema.VALID_INTENT_TYPES /
    # VALID_CONSTRAINT_TYPES — a vocabulary distinct from event_schema.
    # assertEqual(smm[...][...]['type'], 'goal') is intentionally SMM-domain,
    # not event-domain. Mirrors the sister pin's allowlist for the same files.
    "plugins/xp-agents/tests/smm/test_smm_store.py": (
        "smm_schema.VALID_INTENT_TYPES is a distinct vocabulary from "
        "event_schema.VALID_TYPES; SMM pillar 'type' assertions are "
        "intentionally domain-specific"
    ),
    "plugins/xp-agents/tests/smm/test_smm_cli.py": (
        "smm_schema.VALID_INTENT_TYPES is a distinct vocabulary from "
        "event_schema.VALID_TYPES; SMM pillar 'type' assertions are "
        "intentionally domain-specific"
    ),
}


def _is_type_subscript(node: ast.expr) -> bool:
    """True for `<x>["type"]` or `<x>.get("type")` — type-field accessors."""
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "type"
    ):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "type"
    )


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, value, method) violations for one file.

    Method is `assertEqual` or `assertNotEqual`. Empty list = clean.
    Syntax errors return [] — they're a different bug class.
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    violations: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        method = node.func.attr
        if method not in ("assertEqual", "assertNotEqual"):
            continue
        if len(node.args) < 2:
            continue
        a, b = node.args[0], node.args[1]
        # One arg is a type-subscript, the other is a bare event-type literal
        lit_node: ast.Constant | None = None
        if (
            isinstance(a, ast.Constant)
            and isinstance(a.value, str)
            and a.value in VALID_TYPES_SET
            and _is_type_subscript(b)
        ):
            lit_node = a
        elif (
            isinstance(b, ast.Constant)
            and isinstance(b.value, str)
            and b.value in VALID_TYPES_SET
            and _is_type_subscript(a)
        ):
            lit_node = b
        if lit_node is not None and isinstance(lit_node.value, str):
            violations.append((lit_node.lineno, lit_node.value, method))
    return violations


def _rel(path: Path) -> str:
    """Repo-relative path with forward slashes — stable across platforms."""
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _files_to_scan(root: Path) -> list[Path]:
    """test_*.py + _*.py helpers + conftest.py (any depth), excluding self."""
    self_path = Path(__file__).resolve()
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        if p.name == "__init__.py" or p.resolve() == self_path:
            continue
        if p.name.startswith(("test_", "_")) or p.name == "conftest.py":
            paths.append(p)
    return paths


class TestAssertEqualVocabularyPin(unittest.TestCase):
    """No `assertEqual(event["type"], "literal")` regressions in tests/."""

    def test_no_bare_event_type_in_assertequal(self) -> None:
        violations: dict[str, list[tuple[int, str, str]]] = {}
        for py_file in _files_to_scan(TESTS_ROOT):
            rel = _rel(py_file)
            if rel in ALLOWLIST:
                continue
            file_violations = _scan_file(py_file)
            if file_violations:
                violations[rel] = file_violations

        if violations:
            lines = [
                f"  {path}:{ln}: bare event-type literal "
                f"'{val}' in {method}; use EVENT_TYPE_{val.upper()}"
                for path, vs in sorted(violations.items())
                for ln, val, method in vs
            ]
            self.fail(
                f"{len(violations)} file(s) contain bare event-type "
                f"literals in assertEqual/assertNotEqual:\n" + "\n".join(lines)
            )

    def test_walker_detects_subscript_form(self) -> None:
        """`assertEqual(e["type"], "concern")` flags one violation."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                '        e = {"type": "concern"}\n'
                '        self.assertEqual(e["type"], "concern")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, value, method = violations[0]
            self.assertEqual(value, "concern")
            self.assertEqual(method, "assertEqual")
            self.assertEqual(lineno, 5)

    def test_walker_detects_get_form(self) -> None:
        """`assertEqual(e.get("type"), "status")` flags one violation."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_get.py"
            tmp.write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        e = {}\n"
                '        self.assertEqual(e.get("type"), "status")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][1], "status")

    def test_walker_detects_reversed_arg_order(self) -> None:
        """`assertEqual("concern", e["type"])` (literal-first) also flags."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_rev.py"
            tmp.write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        e = {}\n"
                '        self.assertEqual("concern", e["type"])\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][1], "concern")

    def test_walker_detects_assertnotequal(self) -> None:
        """`assertNotEqual(e["type"], "status")` flags too."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_neq.py"
            tmp.write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        e = {}\n"
                '        self.assertNotEqual(e["type"], "status")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][2], "assertNotEqual")

    def test_walker_ignores_non_type_subscript(self) -> None:
        """`assertEqual(e["content"], "concern")` does NOT flag — the
        subscript key isn't 'type', so the literal is unrelated to event
        vocabulary even if it happens to match a VALID_TYPE name.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_other_key.py"
            tmp.write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        e = {}\n"
                '        self.assertEqual(e["content"], "concern")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(violations, [])

    def test_walker_ignores_non_event_type_string(self) -> None:
        """Bare strings not in VALID_TYPES are not violations even when
        paired with a type-subscript (e.g., `e["type"] == "unknown"`).
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_unrelated.py"
            tmp.write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        e = {}\n"
                '        self.assertEqual(e["type"], "not_a_real_event_type")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(violations, [])

    def test_allowlist_entries_have_justifications(self) -> None:
        """Every ALLOWLIST entry must have a non-empty justification."""
        for path, justification in ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                msg=f"ALLOWLIST['{path}'] has empty justification",
            )


if __name__ == "__main__":
    unittest.main()

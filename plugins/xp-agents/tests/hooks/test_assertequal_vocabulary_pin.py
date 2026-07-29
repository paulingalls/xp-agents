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

from _pin_helpers import files_to_scan as _files_to_scan_impl
from _pin_helpers import parse_files, scan_shortfalls
from _pin_helpers import rel as _rel_impl
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


def _scan_tree(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Return (lineno, value, method) violations for one already-parsed
    tree. Method is `assertEqual` or `assertNotEqual`. Empty list = clean.
    """
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


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, value, method) violations for one file. Empty = clean.

    A SyntaxError propagates -- a file this cannot parse is a different
    signal than "clean" (see `_scan_root`, which scanning-a-tree callers
    should use instead).
    """
    return _scan_tree(ast.parse(path.read_text(encoding="utf-8")))


def _scan_root(
    root: Path,
) -> tuple[dict[Path, list[tuple[int, str, str]]], list[tuple[Path, str]]]:
    """Scan every file `files_to_scan` admits under *root*.

    Returns (violations keyed by absolute path, parse-failures). A file
    that fails to parse appears ONLY in the second list -- it is never
    folded into the first as if it had been proven clean.
    """
    trees, parse_failures = parse_files(_files_to_scan(root))
    violations: dict[Path, list[tuple[int, str, str]]] = {}
    for path, tree in trees:
        file_violations = _scan_tree(tree)
        if file_violations:
            violations[path] = file_violations
    return violations, parse_failures


def _count_type_assertion_sites_in_tree(tree: ast.AST) -> int:
    """Count assertEqual/assertNotEqual calls where either side is a
    type-subscript accessor -- the population this pin draws from
    (canonical EVENT_TYPE_* usage included), for the non-vacuity floor."""
    count = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in ("assertEqual", "assertNotEqual"):
            continue
        if len(node.args) < 2:
            continue
        a, b = node.args[0], node.args[1]
        if _is_type_subscript(a) or _is_type_subscript(b):
            count += 1
    return count


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _files_to_scan(root: Path) -> list[Path]:
    return _files_to_scan_impl(root, Path(__file__))


class TestAssertEqualVocabularyPin(unittest.TestCase):
    """No `assertEqual(event["type"], "literal")` regressions in tests/."""

    def test_no_bare_event_type_in_assertequal(self) -> None:
        violations_by_path, parse_failures = _scan_root(TESTS_ROOT)

        if parse_failures:
            lines = [f"  {_rel(p)}: {err}" for p, err in sorted(parse_failures)]
            self.fail(
                f"{len(parse_failures)} file(s) failed to parse -- the scan "
                f"cannot prove them clean:\n" + "\n".join(lines)
            )

        violations = {
            _rel(p): vs
            for p, vs in violations_by_path.items()
            if _rel(p) not in ALLOWLIST
        }

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


class TestPinIsNotVacuous(unittest.TestCase):
    """See test_env_patch_cleanup_pin.py's TestPinIsNotVacuous -- same
    guardrail against a scan that reports clean because it could not look."""

    def test_scan_has_no_shortfalls(self) -> None:
        shortfalls = scan_shortfalls(
            _files_to_scan(TESTS_ROOT),
            TESTS_ROOT,
            min_files=400,
            exclude_self=Path(__file__),
        )
        self.assertEqual(shortfalls, [])

    def test_scan_examines_a_nontrivial_number_of_type_assertion_sites(self) -> None:
        trees, parse_failures = parse_files(_files_to_scan(TESTS_ROOT))
        self.assertEqual(
            parse_failures,
            [],
            msg=f"{len(parse_failures)} file(s) failed to parse: {parse_failures}",
        )
        total = sum(_count_type_assertion_sites_in_tree(tree) for _, tree in trees)
        self.assertGreaterEqual(
            total,
            50,
            msg=(
                f"only {total} type-assertion sites found -- the "
                f"detection shape may have gone blind"
            ),
        )

    def test_pin_fails_loudly_on_an_unparsable_file(self) -> None:
        """A file the scan cannot parse must be reported as its own
        signal -- neither a violation nor silently clean. Genuinely red
        only because `_scan_root` takes a root parameter."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_broken.py").write_text("def broken(:\n")
            violations, parse_failures = _scan_root(root)
            self.assertEqual(violations, {})
            self.assertEqual(len(parse_failures), 1)
            failed_path, _err = parse_failures[0]
            self.assertEqual(failed_path.name, "test_broken.py")


if __name__ == "__main__":
    unittest.main()

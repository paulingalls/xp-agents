#!/usr/bin/env python3
"""Doctrinal pin: forbid bare event-type literals in tests/.

After the M-6a vocabulary sweep, every `make_event(...)` call and every
`{"type": "<bare>"}` dict literal under `plugins/xp-agents/tests/` should
use the `EVENT_TYPE_*` constants from `event_schema`. This pin walks the
test tree via AST and fails on any regression — a future
`make_event("concern", ...)` call fails at test-collection time with a
file:line:value report instead of slipping past grep three sprints later.

Mirrors the `TestEventTypeMatchCompleteness` pattern in
`tests/engine/test_compact.py` (which guards production match-blocks).
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

# Files allowlisted from the pin. Each entry's value must justify why the
# bare literal is intentional — auditable via grep on this dict.
# Justification non-emptiness is enforced by test_allowlist_entries_have_justifications.
ALLOWLIST: dict[str, str] = {
    # test_event_schema.py asserts the literal strings of VALID_TYPES;
    # those tests verify the strings themselves, not behavior built on them.
    "plugins/xp-agents/tests/smm/test_event_schema.py": (
        "VALID_TYPES string assertions intentionally pin the literals"
    ),
}


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


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, value, kind) violations for one file.

    Kinds: `make_event-call`, `dict-literal`. Empty list = clean.
    Syntax errors return [] — they're a different bug class.
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

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


def _rel(path: Path) -> str:
    """Repo-relative path with forward slashes — stable across platforms."""
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _files_to_scan(root: Path) -> list[Path]:
    """Files the pin walks: `test_*.py` + `conftest.py` + `_*.py` helpers.

    Excludes `__init__.py` (no event literals; package marker only) and
    the pin file itself (it asserts other files, not itself). Helper
    modules like `_event_fixtures.py` were the sprint-060 escape route —
    glob extension closes that gap.
    """
    self_path = Path(__file__).resolve()
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        if p.name == "__init__.py" or p.resolve() == self_path:
            continue
        if p.name.startswith(("test_", "_")):
            paths.append(p)
    conftest = root / "conftest.py"
    if conftest.exists():
        paths.append(conftest)
    return paths


class TestEventVocabularyPin(unittest.TestCase):
    """No test_*.py file under tests/ may contain a bare event-type
    literal in a make_event call or `{"type": ...}` dict literal.

    A future regression fails this test at collection time with a precise
    file:line:value report.
    """

    def test_no_bare_event_type_literals_in_tests(self) -> None:
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
                f"'{val}' in {kind}; use EVENT_TYPE_{val.upper()}"
                for path, vs in sorted(violations.items())
                for ln, val, kind in vs
            ]
            self.fail(
                f"{len(violations)} file(s) contain bare event-type "
                f"literals — M-6a sweep regression:\n" + "\n".join(lines)
            )

    def test_walker_detects_synthetic_violation(self) -> None:
        """End-to-end: write a synthetic violation file to tmp_path,
        run the production walker against it, assert both kinds surface
        with correct values + line numbers.

        Exercises the same `Path.read_text() + ast.parse + walker` pipeline
        the pin uses in production. A synthetic in-memory AST node would
        bypass file I/O and parse, hiding regressions in either layer.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_violation.py"
            tmp.write_text(
                "from _event_fixtures import make_event\n"
                "\n"
                "def test_synthetic():\n"
                '    e1 = make_event("concern", content="bug")\n'
                '    e2 = {"type": "status", "id": "x"}\n'
            )
            violations = _scan_file(tmp)

            kinds = sorted({k for _, _, k in violations})
            values = sorted({v for _, v, _ in violations})
            self.assertEqual(kinds, ["dict-literal", "make_event-call"])
            self.assertEqual(values, ["concern", "status"])
            # Line numbers track the source positions of the bare strings,
            # not the enclosing Call/Dict — required so the failure
            # message points at the literal a fix would edit.
            for lineno, value, kind in violations:
                if value == "concern":
                    self.assertEqual(lineno, 4, msg=f"{kind} at wrong line")
                if value == "status":
                    self.assertEqual(lineno, 5, msg=f"{kind} at wrong line")

    def test_walker_catches_aliased_make_event(self) -> None:
        """If a future test does
        `from _event_fixtures import make_event as me`, the walker still
        catches `me("concern", ...)` via the per-file alias map.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_aliased.py"
            tmp.write_text(
                "from _event_fixtures import make_event as me\n"
                "\n"
                "def test_aliased():\n"
                '    me("decision", topic="x", content="y")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][1], "decision")
            self.assertEqual(violations[0][2], "make_event-call")

    def test_walker_catches_attribute_make_event(self) -> None:
        """`fixtures.make_event(...)` qualified calls are matched via
        ast.Attribute, even without an explicit alias import.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_attr.py"
            tmp.write_text(
                "import _event_fixtures as fixtures\n"
                "\n"
                "def test_attr():\n"
                '    fixtures.make_event("goal", content="ship it")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][1], "goal")

    def test_walker_attribute_match_only_for_fixture_modules(self) -> None:
        """`some_other_object.make_event(...)` is NOT flagged when
        `some_other_object` is not imported from a *_fixtures module —
        the bare-`Attribute(attr="make_event")` match would over-flag
        unrelated `.make_event` methods (mock.make_event, self.make_event,
        etc.) that happen to share the name.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_unrelated_attr.py"
            tmp.write_text(
                "class Helper:\n"
                "    def make_event(self, t, **kw):\n"
                "        return {}\n"
                "\n"
                "def test_unrelated():\n"
                "    h = Helper()\n"
                '    h.make_event("concern", content="x")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(violations, [])

    def test_walker_attribute_match_for_imported_fixture_module(self) -> None:
        """`_event_fixtures.make_event(...)` IS flagged when the bare
        module name is imported (no alias). The pin must recognize the
        module by name, not just by alias.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_bare_fixture_import.py"
            tmp.write_text(
                "import _event_fixtures\n"
                "\n"
                "def test_bare():\n"
                '    _event_fixtures.make_event("concern", content="bug")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][1], "concern")
            self.assertEqual(violations[0][2], "make_event-call")

    def test_walker_attribute_match_ignores_non_fixture_aliased_import(self) -> None:
        """`import some_lib as foo` does NOT add `foo` to fixture_modules
        because the source name doesn't end in `_fixtures`. A subsequent
        `foo.make_event("concern", ...)` is therefore NOT flagged —
        third-party libs with a `.make_event` method are correctly ignored.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_third_party.py"
            tmp.write_text(
                "import some_third_party_lib as foo\n"
                "\n"
                "def test_third_party():\n"
                '    foo.make_event("concern", content="x")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(violations, [])

    def test_walker_attribute_match_for_from_imported_fixture_module(self) -> None:
        """`from package import _event_fixtures` then
        `_event_fixtures.make_event(...)` is flagged — covers the
        from-import binding form.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_from_fixture.py"
            tmp.write_text(
                "from somewhere import _close_fixtures\n"
                "\n"
                "def test_from():\n"
                '    _close_fixtures.make_event("concern", content="bug")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][1], "concern")

    def test_walker_ignores_non_type_dict_keys(self) -> None:
        """A dict literal where the bare string is the value of some
        other key (not "type") is NOT a violation — false-positive guard.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_other_key.py"
            tmp.write_text(
                "def test_other_key():\n"
                '    d = {"category": "concern", "name": "status"}\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(violations, [])

    def test_allowlist_entries_have_justifications(self) -> None:
        """Every ALLOWLIST entry must have a non-empty justification string —
        prevents `"file.py": ""` slipping in and silently disabling the pin
        for that file. Read at test time so a future bare-empty entry fails
        immediately.
        """
        for path, justification in ALLOWLIST.items():
            self.assertTrue(
                justification.strip(),
                msg=f"ALLOWLIST['{path}'] has empty justification",
            )

    def test_files_to_scan_includes_underscore_helpers(self) -> None:
        """`_*.py` helper modules (e.g., `_event_fixtures.py`) must be
        scanned — they're test-tree code that imports `make_event` and
        was the escape route for pre-sweep regressions in sprint-060.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_a.py").write_text("# test\n")
            (root / "_event_fixtures.py").write_text("# helper\n")
            (root / "_close_fixtures.py").write_text("# helper\n")
            scanned = {p.name for p in _files_to_scan(root)}
            self.assertIn("_event_fixtures.py", scanned)
            self.assertIn("_close_fixtures.py", scanned)
            self.assertIn("test_a.py", scanned)

    def test_files_to_scan_excludes_dunder_init(self) -> None:
        """`__init__.py` is excluded from the `_*.py` glob — package
        markers don't carry event-type literals and would create noise.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "__init__.py").write_text("")
            (root / "_helper.py").write_text("# helper\n")
            scanned = {p.name for p in _files_to_scan(root)}
            self.assertNotIn("__init__.py", scanned)
            self.assertIn("_helper.py", scanned)

    def test_files_to_scan_includes_root_conftest(self) -> None:
        """`conftest.py` at the scan root must be included — pin
        catches bare literals there too. Nested conftests are not added
        by special-case (they'd be picked up only via test_*.py glob if
        their name matched, which it doesn't); only the root conftest
        is appended explicitly.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "conftest.py").write_text("# root conftest\n")
            (root / "test_a.py").write_text("# test\n")
            scanned = {p.name for p in _files_to_scan(root)}
            self.assertIn("conftest.py", scanned)

    def test_files_to_scan_excludes_pin_file_itself(self) -> None:
        """The pin file is in `tests/hooks/test_*.py` and would otherwise
        match the glob. Excluding it keeps the pin self-isolating —
        the pin asserts other files, not itself.
        """
        scanned = _files_to_scan(TESTS_ROOT)
        scanned_resolved = {p.resolve() for p in scanned}
        self.assertNotIn(Path(__file__).resolve(), scanned_resolved)

    def test_helper_file_violation_surfaces(self) -> None:
        """An `_event_fixtures.py`-style helper with a bare literal
        produces a `make_event-call` violation — pin coverage extends
        beyond `test_*.py` to the fixture helpers themselves.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "_event_fixtures.py"
            tmp.write_text(
                "from event_schema import EVENT_TYPE_CONCERN\n"
                "\n"
                "def make_concern():\n"
                '    return make_event("concern", content="bug")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0][1], "concern")
            self.assertEqual(violations[0][2], "make_event-call")

    def test_walker_catches_kwarg_event_type(self) -> None:
        """`make_event(event_type="concern", ...)` is a violation just like
        the positional form. The keyword spelling escaped sprint-060 because
        the walker only inspected `node.args[0]`; this pins the kwarg path.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_kwarg.py"
            tmp.write_text(
                "from _event_fixtures import make_event\n"
                "\n"
                "def test_kwarg():\n"
                '    e = make_event(event_type="concern", content="bug")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(len(violations), 1)
            lineno, value, kind = violations[0]
            self.assertEqual(value, "concern")
            self.assertEqual(kind, "make_event-call")
            self.assertEqual(lineno, 4)

    def test_walker_ignores_non_event_type_strings(self) -> None:
        """`make_event("not_an_event_type", ...)` is NOT flagged — only
        strings in VALID_TYPES qualify. Filters out unrelated argv strings.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "test_unrelated.py"
            tmp.write_text(
                "from _event_fixtures import make_event\n"
                "\n"
                "def test_unrelated():\n"
                '    e = make_event("not_a_real_type", content="x")\n'
            )
            violations = _scan_file(tmp)
            self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()

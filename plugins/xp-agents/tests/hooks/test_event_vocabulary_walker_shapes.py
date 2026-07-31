#!/usr/bin/env python3
"""What the event-vocabulary walker catches, and what it must leave alone.

Split from `test_event_vocabulary_pin.py` (577 lines). The pin asserts zero
violations on the real tree, which is indistinguishable from a scanner that never
runs; these point it at synthetic files carrying each spelling — positional,
kwarg, aliased import, attribute access through a fixture module — and at shapes
that merely LOOK like violations.

Both halves matter. A scanner that flagged every string literal would pass the
catches and fail the ignores.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from _event_vocabulary_walker import _scan_file


class TestWalkerShapes(unittest.TestCase):
    """The walker fires on each violation spelling, and only on those."""

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

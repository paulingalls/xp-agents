#!/usr/bin/env python3
"""Proofs for the prose-only guard (`tests/_ast_identity.py`).

The guard is what lets a prose pass edit comments and docstrings at scale
without anyone re-reading every hunk for a smuggled behaviour change. That
makes it exactly the kind of check that must not be able to pass by doing
nothing: a bad docstring strip, a swallowed SyntaxError, or an empty file list
would each report "clean" while checking nothing at all.

So the cases below come in pairs. Every "this is clean" case is matched by a
mutation the guard MUST catch, and the empty input set is itself a violation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _ast_identity import code_shape, shape_violations


class TestCodeChangesAreCaught(unittest.TestCase):
    """The mutation half. If any of these pass, the guard is decorative."""

    def test_a_changed_constant_is_caught(self):
        violations = shape_violations([("m.py", "x = 1\n", "x = 2\n")])

        self.assertEqual(len(violations), 1)
        self.assertIn("m.py", violations[0])

    def test_a_changed_call_argument_is_caught(self):
        violations = shape_violations([("m.py", "f(timeout=10)\n", "f(timeout=30)\n")])

        self.assertEqual(len(violations), 1)

    def test_an_inverted_condition_is_caught(self):
        violations = shape_violations(
            [("m.py", "if a and b:\n    pass\n", "if a or b:\n    pass\n")]
        )

        self.assertEqual(len(violations), 1)

    def test_a_deleted_statement_is_caught(self):
        before = "def f():\n    log()\n    return 1\n"
        violations = shape_violations([("m.py", before, "def f():\n    return 1\n")])

        self.assertEqual(len(violations), 1)

    def test_a_changed_string_constant_is_caught(self):
        """String constants are not prose. A changed message, path, or
        sentinel must read as a behaviour change."""
        violations = shape_violations([("m.py", 'x = "alpha"\n', 'x = "beta"\n')])

        self.assertEqual(len(violations), 1)

    def test_a_string_statement_below_the_docstring_is_caught(self):
        """Only `body[0]` is stripped. Widening the strip to every bare string
        statement would silently drop attribute docstrings and any other
        string a tool reads, and every other case here would still pass."""
        before = 'def f():\n    """D."""\n    "kept"\n    return 1\n'
        after = 'def f():\n    """D."""\n    return 1\n'

        self.assertEqual(len(shape_violations([("m.py", before, after)])), 1)

    def test_a_docstring_replaced_by_a_statement_is_caught(self):
        violations = shape_violations(
            [("m.py", 'def f():\n    """D."""\n', "def f():\n    pass\n")]
        )

        self.assertEqual(len(violations), 1)


class TestProseChangesAreClean(unittest.TestCase):
    """The permissive half — what the prose pass is allowed to do."""

    def test_a_reworded_docstring_is_clean(self):
        violations = shape_violations(
            [("m.py", '"""Was wrong."""\nx = 1\n', '"""Now right."""\nx = 1\n')]
        )

        self.assertEqual(violations, [])

    def test_a_deleted_docstring_is_clean(self):
        violations = shape_violations([("m.py", '"""D."""\nx = 1\n', "x = 1\n")])

        self.assertEqual(violations, [])

    def test_a_changed_comment_is_clean(self):
        violations = shape_violations([("m.py", "x = 1  # a\n", "x = 1  # b\n")])

        self.assertEqual(violations, [])

    def test_docstrings_are_stripped_at_every_level(self):
        before = (
            '"""Module."""\n'
            "class C:\n"
            '    """Class."""\n'
            "    def m(self):\n"
            '        """Method."""\n'
            "        return 1\n"
        )
        after = "class C:\n    def m(self):\n        return 1\n"

        self.assertEqual(shape_violations([("m.py", before, after)]), [])

    def test_an_async_function_docstring_is_stripped(self):
        before = 'async def f():\n    """D."""\n    return 1\n'
        after = "async def f():\n    return 1\n"

        self.assertEqual(shape_violations([("m.py", before, after)]), [])

    def test_reindentation_from_a_shorter_docstring_is_clean(self):
        """`include_attributes` must stay False -- at True the dump carries
        line numbers and every deletion below a cut would read as a change."""
        before = '"""One.\n\nTwo.\n\nThree."""\n\n\ndef f():\n    return 1\n'
        after = '"""One."""\n\n\ndef f():\n    return 1\n'

        self.assertEqual(shape_violations([("m.py", before, after)]), [])


class TestTheGuardCannotPassByCheckingNothing(unittest.TestCase):
    """Vacuity and error handling -- the ways a green result could be a lie."""

    def test_an_empty_comparison_set_is_a_violation(self):
        violations = shape_violations([])

        self.assertEqual(len(violations), 1)
        self.assertIn("nothing", violations[0].lower())

    def test_a_pair_of_blank_sources_is_a_violation(self):
        """A non-empty `pairs` of empty sources compares nothing just as
        surely -- the shape two failed reads take."""
        violations = shape_violations([("a.py", "", ""), ("b.py", "\n  \n", "")])

        self.assertEqual(len(violations), 2)
        self.assertIn("nothing", violations[0].lower())

    def test_an_unparseable_after_is_reported_not_swallowed(self):
        violations = shape_violations([("m.py", "x = 1\n", "def broken(:\n")])

        self.assertEqual(len(violations), 1)
        self.assertIn("m.py", violations[0])

    def test_an_unparseable_before_is_reported_not_swallowed(self):
        violations = shape_violations([("m.py", "def broken(:\n", "x = 1\n")])

        self.assertEqual(len(violations), 1)

    def test_several_files_each_report_their_own_violation(self):
        violations = shape_violations(
            [
                ("a.py", "x = 1\n", "x = 2\n"),
                ("b.py", "y = 1\n", "y = 1\n"),
                ("c.py", "z = 1\n", "z = 3\n"),
            ]
        )

        self.assertEqual(len(violations), 2)
        self.assertTrue(any("a.py" in v for v in violations))
        self.assertTrue(any("c.py" in v for v in violations))


class TestCodeShape(unittest.TestCase):
    """`code_shape` is the primitive the comparison rests on."""

    def test_two_sources_differing_only_in_prose_share_a_shape(self):
        self.assertEqual(
            code_shape('"""A."""\nx = 1  # one\n'),
            code_shape('"""B."""\nx = 1  # two\n'),
        )

    def test_two_sources_differing_in_code_do_not_share_a_shape(self):
        self.assertNotEqual(code_shape("x = 1\n"), code_shape("x = 2\n"))

    def test_an_unparseable_source_raises(self):
        with self.assertRaises(SyntaxError):
            code_shape("def broken(:\n")


if __name__ == "__main__":
    unittest.main()

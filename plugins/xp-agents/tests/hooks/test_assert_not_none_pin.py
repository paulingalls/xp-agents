#!/usr/bin/env python3
"""Pin: tests/hooks/ uses self._assert_not_none(x), not assertIsNotNone(x);
assert x is not None pyright crutch.

Sprint-065 story-002 (carries forward sprint-064 story-009 / sprint-063
story-010, debt 144c23eb7ffb). The two-line `assertIsNotNone(x); assert
x is not None` pattern was a per-site pyright-narrowing crutch — pyright
does not propagate `assertIsNotNone`'s narrowing to local variables, so
each call site repeated the `assert x is not None` line below it.

`_HookTestCase._assert_not_none(value)` is the typed replacement: it
returns the narrowed value with type `T` instead of `T | None`, so
callers get pyright narrowing through the return assignment without
the redundant assert line.

This pin enforces zero remaining sites of the legacy two-line pattern
in tests/hooks/. New sites added under tests/hooks/ must use the helper.
Other test directories (tests/integration/, tests/smm/, tests/engine/)
are out of scope for this story; future stories may extend the pin.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _HookTestCase

_HOOKS_DIR = Path(__file__).parent

# Two-line crutch: `self.assertIsNotNone(<expr>)` immediately followed by
# `assert <same-expr> is not None`. The captured group enforces that the
# same identifier appears on both lines so we don't false-flag legitimate
# back-to-back asserts on different names.
_CRUTCH_PATTERN = re.compile(
    r"self\.assertIsNotNone\((\w+)\)\s*\n\s*assert\s+\1\s+is\s+not\s+None"
)


class TestAssertNotNonePin(unittest.TestCase):
    def test_no_assertisnotnone_followed_by_assert_is_not_none(self):
        offenders: dict[str, int] = {}
        for path in _HOOKS_DIR.rglob("*.py"):
            if path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8")
            hits = _CRUTCH_PATTERN.findall(text)
            if hits:
                offenders[path.name] = len(hits)
        self.assertEqual(
            offenders,
            {},
            "tests/hooks/ should use self._assert_not_none(x) instead of "
            "the assertIsNotNone(x); assert x is not None crutch. "
            f"Sites still using the crutch: {offenders}",
        )


class TestAssertNotNoneBehavior(_HookTestCase):
    """Behavior contract for the new _HookTestCase._assert_not_none primitive."""

    def test_returns_value_when_not_none(self):
        self.assertEqual(self._assert_not_none(42), 42)
        self.assertEqual(self._assert_not_none("x"), "x")
        self.assertEqual(self._assert_not_none([1, 2]), [1, 2])

    def test_raises_when_none(self):
        with self.assertRaises(AssertionError):
            self._assert_not_none(None)

    def test_uses_msg_in_failure(self):
        with self.assertRaises(AssertionError) as ctx:
            self._assert_not_none(None, msg="custom failure message")
        self.assertIn("custom failure message", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Pin: callers narrow CONTENT_BUDGETS lookups via get_required_budget,
not bare `assert budget is not None` after a dict access.

Sprint-065 story-004 (debt 6db2c1f32c53). `CONTENT_BUDGETS` is typed
`dict[str, int | None]`; ~6 callers (3 production, 3 tests) repeated
the `budget = CONTENT_BUDGETS[<key>]; assert budget is not None`
pattern to narrow the Optional. The `get_required_budget(event_type)`
helper raises ValueError on None or unknown type, returning `int`
directly so callers don't need a follow-up assert.

This pin enforces zero remaining sites of the legacy pattern across
plugins/xp-agents/scripts/ + plugins/xp-agents/tests/. The schema
shape tests in `tests/smm/test_append_schema.py` iterate over
`CONTENT_BUDGETS.items()` to check the dict itself — those are NOT
narrowing patterns and not in scope.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import event_schema

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_SCAN_DIRS = [
    _PLUGIN_ROOT / "scripts",
    _PLUGIN_ROOT / "tests",
]

# Pattern: `<var> = CONTENT_BUDGETS[<key>]` immediately followed by
# `assert <var> is not None`. The captured group enforces same name.
_CRUTCH_PATTERN = re.compile(
    r"(\w+) = CONTENT_BUDGETS\[[^\]]+\]\s*\n\s*assert\s+\1\s+is\s+not\s+None"
)


class TestGetRequiredBudgetPin(unittest.TestCase):
    def test_no_bare_assert_on_content_budgets_lookup(self):
        offenders: dict[str, int] = {}
        for root in _SCAN_DIRS:
            for path in root.rglob("*.py"):
                if path == Path(__file__):
                    continue
                text = path.read_text(encoding="utf-8")
                hits = _CRUTCH_PATTERN.findall(text)
                if hits:
                    offenders[path.name] = len(hits)
        self.assertEqual(
            offenders,
            {},
            "scripts/ + tests/ should narrow CONTENT_BUDGETS lookups via "
            "get_required_budget(event_type), not bare `assert budget is "
            f"not None`. Sites still using the crutch: {offenders}",
        )


class TestGetRequiredBudgetBehavior(unittest.TestCase):
    """Behavior contract for the new event_schema.get_required_budget helper."""

    def test_returns_int_for_known_type_with_budget(self):
        # `concern` has a non-None budget; helper returns the int directly.
        result = event_schema.get_required_budget("concern")
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_raises_for_unknown_type(self):
        with self.assertRaises(ValueError) as ctx:
            event_schema.get_required_budget("definitely_not_an_event_type")
        self.assertIn("unknown", str(ctx.exception).lower())

    def test_raises_for_none_budget(self):
        # If a known type has None budget (no per-type cap), the helper
        # must raise rather than returning None — that's the whole point
        # of the _required variant.
        original = event_schema.CONTENT_BUDGETS.copy()
        try:
            event_schema.CONTENT_BUDGETS["concern"] = None
            with self.assertRaises(ValueError) as ctx:
                event_schema.get_required_budget("concern")
            self.assertIn("none", str(ctx.exception).lower())
        finally:
            event_schema.CONTENT_BUDGETS.clear()
            event_schema.CONTENT_BUDGETS.update(original)


if __name__ == "__main__":
    unittest.main()

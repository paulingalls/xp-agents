#!/usr/bin/env python3
"""Pin: tests narrow load_plan/load_sprint returns via `_required`
variants, not bare `assert x is not None` lines.

Sprint-065 story-003 (debt 6066b329f860). Each call site that knows the
file MUST exist (via setUp seeding) was repeating the pyright crutch
`<var> = load_X(smm); assert <var> is not None` to narrow the
`dict | None` return. The `_required` variants raise on None at the
boundary, returning `dict` directly.

This pin enforces zero `assert plan/sprint is not None` sites across
all tests/. Production callers that legitimately handle the None
branch (e.g. `update_milestone_status`'s "No execution plan found"
path, `retrospective.py`'s `if sizing is not None`) are NOT in tests/
and not affected.

`compute_story_analysis_required` was considered but dropped after
review: zero migration-candidate callers exist (the production
caller in retrospective.py legitimately handles None). Add the
helper back when a test or CLI subcommand actually needs to narrow
the return.

Out of scope for this pin: `assertIsNotNone(...)` and the
`_assert_not_none(...)` helper — both are story-002 territory and
caught by `tests/hooks/test_assert_not_none_pin.py`.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import execution_plan_store, sprint_store

_TESTS_DIR = Path(__file__).parent.parent

_NARROWING_VARS = ("plan", "sprint")
_PATTERNS = {
    var: re.compile(rf"\bassert\s+{var}\s+is\s+not\s+None\b") for var in _NARROWING_VARS
}


class TestRequiredLoadersPin(unittest.TestCase):
    def test_no_bare_narrowing_asserts_on_loader_returns(self):
        offenders: dict[str, dict[str, int]] = {}
        for path in _TESTS_DIR.rglob("*.py"):
            if path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8")
            per_var: dict[str, int] = {}
            for var, rx in _PATTERNS.items():
                hits = rx.findall(text)
                if hits:
                    per_var[var] = len(hits)
            if per_var:
                offenders[path.name] = per_var
        self.assertEqual(
            offenders,
            {},
            "tests/ should narrow load_plan/load_sprint returns via the "
            "`_required` variants. "
            f"Sites still using `assert <var> is not None`: {offenders}",
        )


class TestRequiredVariantsBehavior(unittest.TestCase):
    """Behavior contract for the new _required loader variants.

    Each pair (regular loader, _required variant) shares the same on-disk
    contract; the variant raises ValueError on missing data instead of
    returning None. Pinned here so a future refactor that moves error
    semantics around trips the test.
    """

    def test_load_plan_required_raises_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as ctx:
                execution_plan_store.load_plan_required(Path(td))
            self.assertIn("No execution plan", str(ctx.exception))

    def test_load_sprint_required_raises_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as ctx:
                sprint_store.load_sprint_required(Path(td))
            self.assertIn("No sprint", str(ctx.exception))

    def test_load_sprint_required_returns_dict_when_present(self):
        # Round-trip: save then load_required returns the saved dict.
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            sprint_store.save_sprint(
                smm,
                {
                    "sprint_id": "sprint-099",
                    "goal": "test",
                    "started": "2026-05-06",
                    "stories": [],
                },
                enforce_budget=False,
            )
            result = sprint_store.load_sprint_required(smm)
            self.assertEqual(result["sprint_id"], "sprint-099")

    def test_load_plan_required_returns_dict_when_present(self):
        # Mirrors the sprint round-trip: save then load_required returns
        # the saved dict. Symmetric coverage so a future regression on
        # the plan happy-path doesn't slip past unnoticed.
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            execution_plan_store.save_plan(
                smm,
                {
                    "title": "test plan",
                    "overview": "test",
                    "sources": [],
                    "milestones": [],
                },
                enforce_budget=False,
            )
            result = execution_plan_store.load_plan_required(smm)
            self.assertEqual(result["title"], "test plan")

    def test_load_sprint_fail_open_returns_none_when_missing(self):
        # The advisory/accounting variant degrades absence to None (no raise).
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(sprint_store.load_sprint_fail_open(Path(td)))

    def test_load_sprint_fail_open_returns_none_when_corrupt(self):
        # A corrupt sprint.json must collapse to None, NOT raise — the merge
        # advisory/accounting callers run after a merge commits and must never
        # crash the close chain over a SMM-state problem.
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            (smm / "sprint.json").write_text("{not valid json")
            self.assertIsNone(sprint_store.load_sprint_fail_open(smm))

    def test_load_sprint_fail_open_returns_dict_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            sprint_store.save_sprint(
                smm,
                {
                    "sprint_id": "sprint-100",
                    "goal": "test",
                    "started": "2026-05-06",
                    "stories": [],
                },
                enforce_budget=False,
            )
            result = sprint_store.load_sprint_fail_open(smm)
            # `or {}` narrows dict|None to dict for pyright; an unexpected None
            # surfaces as a KeyError on the missing sprint_id, failing the test.
            self.assertEqual((result or {})["sprint_id"], "sprint-100")


if __name__ == "__main__":
    unittest.main()

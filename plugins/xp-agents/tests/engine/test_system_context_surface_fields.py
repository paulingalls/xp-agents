#!/usr/bin/env python3
"""Tests for `acceptance_surfaces[]` entry validation — name/harness/signals
budgets, and the `command`/`paths` pair the close gate narrows on.

Split from test_system_context_schema_fields.py at the commit that pushed it
past its recorded band ceiling. These two classes and their `_surface` fixture
share nothing with the module/convention/principle/project_specific validation
left behind, so they are the cohesive group — as that file's own ceiling note
predicted.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc
from system_context_schema import (
    ACCEPTANCE_SURFACE_COMMAND_MAXLENGTH,
    ACCEPTANCE_SURFACE_PATH_MAXLENGTH,
    ACCEPTANCE_SURFACE_PATHS_MAXCOUNT,
    STACK_FIELD_MAXLENGTH,
    validate_system_context,
)


def _surface(**overrides: object) -> dict:
    s = {"name": "cli", "signals": ["pytest -n auto"], "status": "covered"}
    s.update(overrides)
    return s


class TestAcceptanceSurfaceValidation(unittest.TestCase):
    def test_acceptance_surface_name_over_budget(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(name="x" * 51)])
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e and "budget" in e for e in errors))

    def test_acceptance_surface_harness_over_budget(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(harness="x" * 51)])
        errors = validate_system_context(doc)
        self.assertTrue(any("harness" in e and "budget" in e for e in errors))

    def test_acceptance_surface_signal_item_over_budget(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(signals=["x" * 101])])
        errors = validate_system_context(doc)
        self.assertTrue(any("signals" in e and "budget" in e for e in errors))


class TestAcceptanceSurfaceCommandAndPaths(unittest.TestCase):
    """A surface may declare the command that covers it and the paths it owns.

    Both optional, so every document written before they existed stays valid.
    The assertions below pin the ENFORCEMENT, not mere acceptance: before these
    fields existed the validator ignored unrecognized keys, so a test that only
    checked a well-formed surface was accepted would pass against the old code
    and prove nothing.
    """

    def test_command_and_paths_accepted(self) -> None:
        doc = valid_doc(
            acceptance_surfaces=[
                _surface(command="pytest tests/cli", paths=["src/cli/**"])
            ]
        )
        self.assertEqual(validate_system_context(doc), [])

    def test_command_must_be_a_string(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(command=["a"], paths=["p"])])
        errors = validate_system_context(doc)
        self.assertTrue(any("command" in e for e in errors), errors)

    def test_surface_command_shares_the_stack_command_bound(self) -> None:
        """Pinned equal: a surface command is a narrowed `stack.test_command`.
        The validator cannot import this from its own importer, so the two
        literals are kept honest here rather than by hope."""
        self.assertEqual(ACCEPTANCE_SURFACE_COMMAND_MAXLENGTH, STACK_FIELD_MAXLENGTH)

    def test_command_over_budget(self) -> None:
        doc = valid_doc(
            acceptance_surfaces=[
                _surface(
                    command="x" * (ACCEPTANCE_SURFACE_COMMAND_MAXLENGTH + 1),
                    paths=["p"],
                )
            ]
        )
        errors = validate_system_context(doc)
        self.assertTrue(any("command" in e and "budget" in e for e in errors), errors)

    def test_paths_must_be_a_list(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(paths="src/**")])
        errors = validate_system_context(doc)
        self.assertTrue(any("paths" in e for e in errors), errors)

    def test_path_entry_must_be_a_string(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(paths=[3])])
        errors = validate_system_context(doc)
        self.assertTrue(any("paths" in e for e in errors), errors)

    def test_path_entry_over_budget(self) -> None:
        doc = valid_doc(
            acceptance_surfaces=[
                _surface(paths=["x" * (ACCEPTANCE_SURFACE_PATH_MAXLENGTH + 1)])
            ]
        )
        errors = validate_system_context(doc)
        self.assertTrue(any("paths" in e and "budget" in e for e in errors), errors)

    def test_too_many_path_entries_is_over_budget(self) -> None:
        """`paths` renders into system_context, which is injected into every
        agent — so the COUNT is budgeted, not just each entry's length.
        Mutation: drop the count check -> red, and 200 globs ride along on
        every injection."""
        doc = valid_doc(
            acceptance_surfaces=[
                _surface(
                    paths=[
                        f"src/{i}/**"
                        for i in range(ACCEPTANCE_SURFACE_PATHS_MAXCOUNT + 1)
                    ]
                )
            ]
        )
        errors = validate_system_context(doc)
        self.assertTrue(any("paths" in e and "budget" in e for e in errors), errors)

    def test_exactly_the_cap_is_allowed(self) -> None:
        """The refutation: an off-by-one that rejected the cap itself would
        also pass the test above."""
        doc = valid_doc(
            acceptance_surfaces=[
                _surface(
                    paths=[
                        f"src/{i}/**" for i in range(ACCEPTANCE_SURFACE_PATHS_MAXCOUNT)
                    ]
                )
            ]
        )
        self.assertEqual(validate_system_context(doc), [])

    def test_command_without_paths_is_rejected(self) -> None:
        """An unselectable command is an inert declaration, not a valid one:
        selection maps a story's file domain onto `paths`, so a pathless
        surface matches nothing and its command never runs."""
        doc = valid_doc(acceptance_surfaces=[_surface(command="pytest tests/cli")])
        errors = validate_system_context(doc)
        self.assertTrue(any("paths" in e for e in errors), errors)

    def test_command_without_paths_still_LOADS(self) -> None:
        """...but only at the WRITE boundary. `load_system_context` validates
        with `enforce_budget=False` and RAISES on any error, and
        `branching_stage._maybe_auto_promote` does a load -> mutate -> save
        round-trip from a hook without catching ValueError. A rule that fires on
        the read path therefore turns one hand-edited surface into a hook that
        crashes on every session until the file is repaired by hand — the exact
        hazard `unknown_surface_key_errors` documents. Every other new rule in
        this hunk is grandfathered; this one has to be too.

        Mutation: append the error unconditionally -> red.
        """
        doc = valid_doc(acceptance_surfaces=[_surface(command="pytest tests/cli")])
        self.assertEqual(validate_system_context(doc, enforce_budget=False), [])

    def test_paths_without_command_is_fine(self) -> None:
        """The reverse is NOT an error: paths alone still describe ownership,
        and a project may declare them before it has a narrowed command."""
        doc = valid_doc(acceptance_surfaces=[_surface(paths=["src/cli/**"])])
        self.assertEqual(validate_system_context(doc), [])

    def test_enforce_budget_false_skips_the_new_budgets(self) -> None:
        doc = valid_doc(
            acceptance_surfaces=[
                _surface(
                    command="x" * (STACK_FIELD_MAXLENGTH + 100),
                    paths=["x" * (ACCEPTANCE_SURFACE_PATH_MAXLENGTH + 100)],
                )
            ]
        )
        self.assertEqual(validate_system_context(doc, enforce_budget=False), [])


if __name__ == "__main__":
    unittest.main()

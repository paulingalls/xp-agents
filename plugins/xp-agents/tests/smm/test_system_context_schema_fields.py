#!/usr/bin/env python3
"""Tests for branching_strategy.integration_branch as a git ref.

`integration_branch` becomes `git checkout <ref>` / `git merge <ref>` argv
(branch_resolution.get_primary_branch), exactly like sprint.branch_name and
plan.branch — but unlike those two it was type-checked only. This file covers
the shared `usable_git_ref_name` predicate, the two field wrappers, and the
load-lenient / save-strict split in the store.

The store half is the load-bearing part: the check must be enforced at INPUT
without hard-failing a project whose stored config predates it.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc
from execution_plan_schema import VALID_BRANCH_NAME_RE, usable_git_ref_name
from system_context_schema import (
    SYSTEM_CONTEXT_FILENAME,
    healed_integration_branch,
    integration_branch_error,
    validate_system_context,
)
from system_context_store import load_system_context, save_system_context

# Values a caller must never be handed as a git ref. The first three fail the
# shared pattern outright; the last two PASS it (see the pin below) and are
# caught only by the leading-dash rule.
UNUSABLE_REFS = ("feature branch", "main\n", "back~tick`", "-f", "--force")


class TestUsableGitRefName(unittest.TestCase):
    def test_leading_dash_matches_the_pattern(self) -> None:
        """Why the leading-dash rule is NOT redundant with the pattern.

        `-` sits inside the pattern's character class, so `-f` and `--force`
        are well-formed by it. `get_primary_branch` returning `-f` yields
        `git checkout -f`, which discards local changes. If this pin ever
        fails because the pattern was tightened, the extra rule may go —
        until then it is the only thing standing between a stored config and
        argv.
        """
        for flag in ("-f", "--force"):
            with self.subTest(flag=flag):
                self.assertIsNotNone(VALID_BRANCH_NAME_RE.match(flag))

    def test_accepts_ordinary_branch_names(self) -> None:
        for name in ("main", "paul/story-005-x", "release/v1.2.3", "a_b.c-d"):
            with self.subTest(name=name):
                self.assertTrue(usable_git_ref_name(name))

    def test_rejects_every_unusable_ref(self) -> None:
        for value in UNUSABLE_REFS:
            with self.subTest(value=value):
                self.assertFalse(usable_git_ref_name(value))

    def test_rejects_non_strings(self) -> None:
        for value in (None, 3, ["main"], {"branch": "main"}, b"main"):
            with self.subTest(value=value):
                self.assertFalse(usable_git_ref_name(value))

    def test_rejects_empty_string(self) -> None:
        self.assertFalse(usable_git_ref_name(""))


class TestIntegrationBranchFieldWrappers(unittest.TestCase):
    def test_no_error_when_absent_or_null(self) -> None:
        for bs in ({"stage": 3}, {"stage": 3, "integration_branch": None}):
            with self.subTest(bs=bs):
                self.assertIsNone(integration_branch_error(bs))
                self.assertIsNone(healed_integration_branch(bs))

    def test_conforming_value_passes_and_heals_to_itself(self) -> None:
        bs = {"stage": 3, "integration_branch": "develop"}
        self.assertIsNone(integration_branch_error(bs))
        self.assertEqual(healed_integration_branch(bs), "develop")

    def test_unusable_value_errors_and_heals_to_none(self) -> None:
        for value in UNUSABLE_REFS:
            with self.subTest(value=value):
                bs = {"stage": 3, "integration_branch": value}
                error = integration_branch_error(bs)
                self.assertIsNotNone(error)
                self.assertIn("branching_strategy.integration_branch", str(error))
                self.assertIsNone(healed_integration_branch(bs))

    def test_non_dict_strategy_is_not_this_wrapper_s_business(self) -> None:
        """Shape errors belong to the strategy validator; these two answer only
        about the field, so a non-dict yields no field error and no value."""
        for bs in ("nope", None, 42, ["develop"]):
            with self.subTest(bs=bs):
                self.assertIsNone(integration_branch_error(bs))
                self.assertIsNone(healed_integration_branch(bs))


class TestEnforceRefFormatFlag(unittest.TestCase):
    """The flag exists so the READ path can stay lenient while the WRITE path
    stays strict — the whole grandfathering mechanism rests on it."""

    def _doc(self, value: object) -> dict:
        return valid_doc(branching_strategy={"stage": 3, "integration_branch": value})

    def test_default_rejects_an_unusable_ref(self) -> None:
        errors = validate_system_context(self._doc("-f"))
        self.assertTrue(
            any("branching_strategy.integration_branch" in e for e in errors), errors
        )

    def test_disabled_accepts_an_unusable_ref(self) -> None:
        errors = validate_system_context(self._doc("-f"), enforce_ref_format=False)
        self.assertEqual(errors, [])

    def test_disabling_it_does_not_disable_the_type_check(self) -> None:
        """Lenient about FORMAT is not lenient about SHAPE — an int was never a
        loadable value and must still be rejected on the read path."""
        errors = validate_system_context(self._doc(42), enforce_ref_format=False)
        self.assertTrue(
            any("branching_strategy.integration_branch" in e for e in errors), errors
        )


class _StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.smm_dir = Path(self._td.name)
        self.path = self.smm_dir / SYSTEM_CONTEXT_FILENAME

    def _doc(self, integration_branch: object) -> dict:
        return valid_doc(
            branching_strategy={"stage": 3, "integration_branch": integration_branch}
        )

    def _grandfather(self, integration_branch: object) -> dict:
        """Put a doc on disk WITHOUT going through save — i.e. a config written
        before this check existed."""
        doc = self._doc(integration_branch)
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        return doc

    def _stored_branch(self) -> object:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return raw["branching_strategy"]["integration_branch"]


class TestSaveRejectsNewUnusableRefs(_StoreTestCase):
    def test_new_unusable_value_is_rejected_naming_the_field(self) -> None:
        for value in UNUSABLE_REFS:
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as ctx:
                    save_system_context(self.smm_dir, self._doc(value))
                self.assertIn(
                    "branching_strategy.integration_branch", str(ctx.exception)
                )

    def test_conforming_value_round_trips_byte_identical(self) -> None:
        save_system_context(self.smm_dir, self._doc("develop"))
        self.assertEqual(self._stored_branch(), "develop")
        loaded = load_system_context(self.smm_dir)
        assert loaded is not None
        self.assertEqual(loaded["branching_strategy"]["integration_branch"], "develop")


class TestLoadIsLenient(_StoreTestCase):
    """A project whose stored config predates the check must keep starting
    sessions — and must get back what it stored, not a healed substitute.
    Healing on load would let `_maybe_auto_promote`'s load-mutate-save
    round-trip silently persist null over a branch the user configured.
    """

    def test_stored_unusable_value_loads_unchanged(self) -> None:
        for value in UNUSABLE_REFS:
            with self.subTest(value=value):
                self._grandfather(value)
                loaded = load_system_context(self.smm_dir)
                assert loaded is not None
                self.assertEqual(
                    loaded["branching_strategy"]["integration_branch"], value
                )


class TestSaveGrandfatherIsNarrow(_StoreTestCase):
    def test_resaving_the_stored_value_unchanged_succeeds(self) -> None:
        doc = self._grandfather("-f")
        save_system_context(self.smm_dir, doc)
        self.assertEqual(self._stored_branch(), "-f")

    def test_a_different_unusable_value_is_still_rejected(self) -> None:
        """The grandfather is keyed on the FIELD, not on 'this doc was already
        bad'. Storing `-f` must not license writing `--force`."""
        self._grandfather("-f")
        with self.assertRaises(ValueError) as ctx:
            save_system_context(self.smm_dir, self._doc("--force"))
        self.assertIn("branching_strategy.integration_branch", str(ctx.exception))
        self.assertEqual(self._stored_branch(), "-f", "the write must not land")

    def test_unrelated_edits_to_a_grandfathered_doc_still_save(self) -> None:
        """The `_maybe_auto_promote` shape: load, change something ELSE, save."""
        doc = self._grandfather("-f")
        doc["branching_strategy"]["stage"] = 2
        save_system_context(self.smm_dir, doc)
        self.assertEqual(self._stored_branch(), "-f")

    def test_missing_on_disk_doc_yields_rejection_not_a_bypass(self) -> None:
        """THE fail-closed pin. A grandfather that fails open is not a
        grandfather — it is an unconditional bypass reachable by deleting a
        file."""
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            save_system_context(self.smm_dir, self._doc("-f"))

    def test_corrupt_on_disk_doc_yields_rejection_not_a_bypass(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            save_system_context(self.smm_dir, self._doc("-f"))

    def test_on_disk_doc_without_the_field_yields_rejection(self) -> None:
        self.path.write_text(json.dumps(valid_doc()), encoding="utf-8")
        with self.assertRaises(ValueError):
            save_system_context(self.smm_dir, self._doc("-f"))


class TestCliValidateReportsStoredBadValues(_StoreTestCase):
    """`validate` stays strict. Because the loader no longer hides the
    violation, it now REPORTS a stored bad value instead of laundering it
    green. No hook, preload or skill gates on this command."""

    def _validate(self) -> subprocess.CompletedProcess:
        cli = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"
        return subprocess.run(
            [sys.executable, str(cli), "--smm-dir", str(self.smm_dir), "validate"],
            capture_output=True,
            text=True,
        )

    def test_stored_unusable_value_exits_1_naming_the_field(self) -> None:
        self._grandfather("-f")
        r = self._validate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("branching_strategy.integration_branch", r.stderr)

    def test_conforming_value_still_validates_clean(self) -> None:
        self._grandfather("develop")
        r = self._validate()
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()

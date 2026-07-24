#!/usr/bin/env python3
"""Tests for branching_strategy.integration_branch as a git ref.

`integration_branch` becomes `git checkout <ref>` / `git merge <ref>` argv
(branch_resolution.get_primary_branch), exactly like sprint.branch_name and
plan.branch — but unlike those two it was type-checked only. This file covers
the shared `usable_git_ref_name` predicate, the two field wrappers, and the
load-lenient / save-strict split in the store.

The store half is the load-bearing part: the check must be enforced at INPUT
without hard-failing a project whose stored config predates it.

`user_namespace` is governed by the same rule (plus a single-segment rule of its
own) and shares the grandfather — see TestSaveGrandfathersTheStoredNamespace.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import branch_resolution
import system_context_store as store_module
from _system_context_fixtures import valid_doc
from execution_plan_schema import VALID_BRANCH_NAME_RE, usable_git_ref_name
from system_context_renderer import _render_branching_strategy
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

    def test_accepts_git_legal_names_the_naming_pattern_rejects(self) -> None:
        """The question here is "can git use this?", NOT "does this match the
        names we generate?" — two different jobs that shared one regex.

        `VALID_BRANCH_NAME_RE` constrains branch names the plugin CREATES.
        Reusing it to judge a name the USER configured rejected legal git
        branches: `healed_integration_branch` then silently retargeted merges
        to the primary branch — the RELEASE branch — and dropped the branch's
        protected status, on nothing worse than a `+` or a non-ASCII letter.
        A plugin that ships to any project cannot treat non-ASCII as invalid.
        """
        for name in ("main+dev", "trunk@2", "feat(ui)", "développement", "主线"):
            with self.subTest(name=name):
                self.assertTrue(usable_git_ref_name(name))

    def test_matches_git_on_the_dot_and_HEAD_edges(self) -> None:
        """Both verified against real `git check-ref-format`, not from memory.

        `foo./bar` is VALID to git: only the ref AS A WHOLE may not end in a
        dot, so a per-component trailing-dot rule over-rejects. `HEAD` passes
        `check-ref-format` as a ref PATH but `--branch HEAD` is "not a valid
        branch name" — and an integration_branch of HEAD would detach on
        checkout and no-op merges, the same argv-hazard class the leading-dash
        refusal exists for.
        """
        self.assertTrue(usable_git_ref_name("foo./bar"))
        self.assertFalse(usable_git_ref_name("HEAD"))

    def test_still_rejects_what_git_itself_refuses(self) -> None:
        """Widening must not become "anything goes": these are the forms
        `git check-ref-format` rejects, plus the leading dash that reaches
        argv as a flag."""
        for value in (
            "-f",
            "--force",
            "has space",
            "a..b",
            "a~1",
            "a^",
            "a:b",
            "a?",
            "a*",
            "a[b",
            "a\\b",
            "a@{0}",
            "a.lock",
            "/leading",
            "trailing/",
            "trailing.",
            "ctrl\x01char",
        ):
            with self.subTest(value=value):
                self.assertFalse(usable_git_ref_name(value))

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


class TestRendererMarksARejectedValue(unittest.TestCase):
    """The SMM must not tell the agent merges target `-f` while behavior
    targets `main` — that split-brain is the thing the SMM exists to prevent.
    The stored value keeps being shown (it is what is on disk, and hiding it
    would make the config unfixable), but it is marked as not in force.
    """

    def _render(self, value: object) -> str:
        lines: list[str] = []
        _render_branching_strategy(lines, {"stage": 3, "integration_branch": value})
        return "\n".join(lines)

    def test_unusable_value_is_shown_and_marked(self) -> None:
        rendered = self._render("-f")
        self.assertIn("-f", rendered, "the stored value must still be visible")
        self.assertRegex(rendered.lower(), r"not usable|unusable")

    def test_the_marked_fallback_names_what_resolution_actually_returns(self) -> None:
        """SYNC PIN. The renderer spells the fallback branch out rather than
        importing it (smm/ must not depend on scripts/), so this is what keeps
        the two from drifting into a second split-brain."""
        self.assertIn(branch_resolution._DEFAULT_PRIMARY, self._render("-f"))

    def test_usable_value_is_rendered_plainly(self) -> None:
        rendered = self._render("develop")
        self.assertIn("develop", rendered)
        self.assertNotRegex(rendered.lower(), r"not usable|unusable")


class TestRendererMarksARejectedNamespace(unittest.TestCase):
    """Same split-brain, same treatment, for `user_namespace`.

    Now that branch naming READS this field, a stored value the use-site drops
    would otherwise be rendered as fact — the SMM telling the agent branches are
    cut under `team/paul` while every branch is really cut under the git
    identity. That is the disagreement reading the field exists to end.
    """

    def _render(self, value: object) -> str:
        lines: list[str] = []
        _render_branching_strategy(lines, {"stage": 2, "user_namespace": value})
        return "\n".join(lines)

    def test_unusable_value_is_shown_and_marked(self) -> None:
        for value in ("team/paul", "-f", "has space"):
            with self.subTest(value=value):
                rendered = self._render(value)
                self.assertIn(
                    str(value), rendered, "the stored value must still be visible"
                )
                self.assertRegex(rendered.lower(), r"not usable|unusable")

    def test_usable_value_is_rendered_plainly(self) -> None:
        rendered = self._render("paul")
        self.assertIn("paul", rendered)
        self.assertNotRegex(rendered.lower(), r"not usable|unusable")


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

    def test_a_conforming_value_never_lowers_the_strict_flag(self) -> None:
        """The grandfather fires ONLY for a value that actually violates the
        rule. ``enforce_ref_format`` is document-wide, so a conforming
        integration_branch that happens to match disk must not switch it off
        for whatever else starts consulting it."""
        doc = self._grandfather("develop")
        self.assertFalse(store_module._is_grandfathered_ref_format(self.path, doc))

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


class TestSaveGrandfathersTheStoredNamespace(_StoreTestCase):
    """`user_namespace` joined `integration_branch` under the ref-format rule,
    so it needs the same grandfather — for a sharper reason.

    `branch_resolution._maybe_auto_promote` does load -> set stage -> save and
    deliberately lets ValueError propagate ("schema/code-bug must crash loud").
    It runs from `get_branching_stage`, which nearly every gate calls. Without a
    grandfather, one stored namespace that predates the rule turns every stage
    read into a crash — the over-rejection failure `usable_git_ref_name`'s
    docstring records, reached through the other field.
    """

    def _ns_doc(self, user_namespace: object, **bs: object) -> dict:
        return valid_doc(
            branching_strategy={"stage": 1, "user_namespace": user_namespace, **bs}
        )

    def _stored_ns(self) -> object:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return raw["branching_strategy"]["user_namespace"]

    def test_auto_promote_round_trip_over_a_stored_bad_namespace_succeeds(self) -> None:
        doc = self._ns_doc("team/paul")
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        loaded = load_system_context(self.smm_dir)
        assert loaded is not None
        loaded["branching_strategy"]["stage"] = 2
        save_system_context(self.smm_dir, loaded)
        self.assertEqual(self._stored_ns(), "team/paul")

    def test_a_different_bad_namespace_is_still_rejected(self) -> None:
        self.path.write_text(json.dumps(self._ns_doc("team/paul")), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            save_system_context(self.smm_dir, self._ns_doc("--upload-pack=evil"))
        self.assertIn("branching_strategy.user_namespace", str(ctx.exception))
        self.assertEqual(self._stored_ns(), "team/paul", "the write must not land")

    def test_a_bad_namespace_cannot_ride_a_grandfathered_branch(self) -> None:
        """``enforce_ref_format`` is document-wide, so a grandfathered
        integration_branch must not license a NEW bad namespace alongside it."""
        stored = self._ns_doc("paul", integration_branch="-f")
        self.path.write_text(json.dumps(stored), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            save_system_context(
                self.smm_dir,
                self._ns_doc("--upload-pack=evil", integration_branch="-f"),
            )
        self.assertIn("branching_strategy.user_namespace", str(ctx.exception))

    def test_a_new_bad_namespace_alone_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            save_system_context(self.smm_dir, self._ns_doc("has space"))
        self.assertIn("branching_strategy.user_namespace", str(ctx.exception))


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

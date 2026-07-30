#!/usr/bin/env python3
"""Tests for identity.user_namespace — the slug that prefixes every branch.

Split from `test_identity.py` (582 lines). Two sources, in precedence order: a
recorded `branching_strategy.user_namespace` in system_context, else a slug
derived from git config. The recorded field was inert once — system_context could
say one thing while every branch was created under another — so the override and
each way it must FALL BACK are the substance here, not the slugify rules.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import identity
from _branching_fixtures import init_repo
from _sprint_fixtures import write_system_context


class TestUserNamespace(unittest.TestCase):
    """user_namespace extracts a slug from git config for branch naming."""

    def test_email_local_part_slug(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="paul@paulingalls.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul")

    def test_email_with_dots_and_plus(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="first.last+tag@example.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "first-last-tag")

    def test_uppercase_lowered(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="PAUL@example.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul")

    def test_name_fallback(self):
        email_result = subprocess.CompletedProcess([], 1, stdout="")
        name_result = subprocess.CompletedProcess([], 0, stdout="Paul Ingalls\n")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return name_result

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul-ingalls")

    def test_both_unset_returns_default(self):
        fail = subprocess.CompletedProcess([], 1, stdout="")
        with patch("identity.subprocess.run", return_value=fail):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "user")

    def test_email_without_at_falls_to_name(self):
        """Email without @ is ignored, falls back to user.name."""
        email_result = subprocess.CompletedProcess([], 0, stdout="localonly\n")
        name_result = subprocess.CompletedProcess([], 0, stdout="Fallback Name\n")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return name_result

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "fallback-name")

    def test_slugify_all_special_chars_falls_to_default(self):
        """Email local-part that slugifies to empty falls through."""
        email_result = subprocess.CompletedProcess([], 0, stdout="---@example.com\n")
        fail = subprocess.CompletedProcess([], 1, stdout="")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return fail

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "user")

    def test_real_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            # An SMM dir with no system_context.json — pins the git-derived
            # answer WITHOUT depending on whatever SMM the ambient environment
            # resolves to. Omitting it made this test read the developer's real
            # system_context (and fail under `python3 -m unittest discover`,
            # which loads no conftest and so gets no redirected plugin-data
            # root).
            result = identity.user_namespace(td, smm_dir=Path(td))
            self.assertEqual(result, "test")


class TestUserNamespaceFromSystemContext(unittest.TestCase):
    """A recorded branching_strategy.user_namespace OVERRIDES the git-derived slug.

    Before this, the recorded field was inert: system_context could say
    ``paulingalls`` while every branch was created as ``ingallsp/...`` and
    nothing reported the disagreement. The recorded value is user-editable
    (``system_context_cli edit-branching-field``), so it is an override, and an
    override that nothing reads is a lie.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write_ctx(self, **bs_extras: object) -> None:
        """Fully-valid context via the shared fixture — a schema-invalid doc
        makes the loader raise, which this code treats as "no override", so a
        hand-rolled minimal doc would make every assertion below pass
        vacuously."""
        write_system_context(self.smm_dir, 2, **bs_extras)

    def _git_says(self, email: str):
        return patch(
            "identity.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=f"{email}\n"),
        )

    def test_recorded_value_wins_over_git_email(self):
        self._write_ctx(user_namespace="paulingalls")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "paulingalls"
            )

    def test_absent_field_falls_back_to_git(self):
        self._write_ctx()
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_no_system_context_falls_back_to_git(self):
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_empty_string_falls_back_to_git(self):
        self._write_ctx(user_namespace="   ")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_leading_dash_is_refused_and_falls_back(self):
        """A namespace reaching `git branch` as argv must never start with `-`.

        Same argv-injection guard integration_branch already carries: the value
        is interpolated into a branch name handed to git, so a leading dash
        would arrive as a FLAG.
        """
        self._write_ctx(user_namespace="--upload-pack=evil")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_unusable_ref_characters_fall_back(self):
        self._write_ctx(user_namespace="has spaces")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_omitted_smm_dir_self_resolves_the_override(self):
        """The 10 existing call sites pass no smm_dir and must STILL see the
        override — branch readers (list_user_branches) and branch writers
        (create_free_branch) both go through this path, and a reader that
        disagreed with the writer would break kickoff's orphan triage.

        SMM_DIR is pinned rather than left to init.sh derivation: unpinned,
        this reads whatever SMM the ambient environment resolves to (the
        developer's own, under `python3 -m unittest discover`).
        """
        self._write_ctx(user_namespace="paulingalls")
        with (
            patch.dict(os.environ, {"SMM_DIR": str(self.smm_dir)}),
            self._git_says("ingallsp@example.com"),
        ):
            self.assertEqual(identity.user_namespace("/tmp"), "paulingalls")

    def test_multi_segment_namespace_falls_back(self):
        """A namespace is ONE segment: `team/paul` would create
        `team/paul/free-…` branches that `is_free_branch` / `extract_story_id`
        (both `^[^/]+/…`) cannot recognize, so free-close and story-close would
        refuse the plugin's own branches. Dropped here, refused at write time.
        """
        self._write_ctx(user_namespace="team/paul")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_schema_invalid_context_falls_back_instead_of_raising(self):
        """A DELIBERATE tradeoff, pinned so it is not mistaken for an accident.

        The override is read through the validating loader (which also carries
        the symlink guard), so a system_context that fails schema validation
        anywhere drops the namespace override rather than honoring just this
        field. Branch naming must never raise, and git-derived is always a
        valid answer. The cost: an unrelated invalid field silently changes the
        branch prefix — acceptable only because a schema-invalid context is
        already loudly broken everywhere else that reads it.
        """
        (self.smm_dir / "system_context.json").write_text(
            json.dumps({"product": {"name": "t", "purpose": "t"}})
        )
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_corrupt_json_falls_back_instead_of_raising(self):
        (self.smm_dir / "system_context.json").write_text("{not json")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )


if __name__ == "__main__":
    unittest.main()

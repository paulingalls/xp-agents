#!/usr/bin/env python3
"""Which SMM the branch-naming namespace is read from.

`branching_strategy.user_namespace` is an override on the git-derived prefix,
so every branch helper reads it — writers when they mint a name, readers when
they build the glob to find those names again. Both must read it from the SMM
the CALLER named. Self-resolving instead answers from whatever SMM the ambient
environment produces, which is a different tree whenever the caller was handed
one explicitly (`--smm-dir`), whenever the process cwd is not the repo, and
whenever a relocation has moved the SMM under a pinned handle. A reader that
disagrees with the writer makes kickoff's orphan triage blind to the branches
the plugin itself just created.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branch_queries
import branching

_OVERRIDE = "override"
# init_repo commits as test@example.com, so the git-derived namespace is "test".
_GIT_NS = "test"


class _NamespaceCase(unittest.TestCase):
    """A repo and an SMM that are NOT the ones this process would resolve."""

    def setUp(self) -> None:
        self.cwd = self.enterContext(tempfile.TemporaryDirectory())
        self.smm_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        _bf.init_repo(self.cwd)
        _bf.write_system_context(self.smm_dir, stage=2, user_namespace=_OVERRIDE)

    def _branch(self, name: str) -> None:
        subprocess.run(
            ["git", "branch", name],
            cwd=self.cwd,
            capture_output=True,
            check=True,
            env=_bf.GIT_ENV,
        )


class TestWritersUseTheHandedSmm(_NamespaceCase):
    def test_free_branch_is_cut_under_the_recorded_override(self):
        result = branching.create_free_branch(self.cwd, "spike", self.smm_dir)
        self.assertIsNotNone(result)
        self.assertTrue(
            str(result).startswith(f"{_OVERRIDE}/free-"),
            f"expected the recorded namespace, got {result}",
        )

    def test_plan_branch_is_cut_under_the_recorded_override(self):
        result = branching.create_plan_branch(self.cwd, "redesign", self.smm_dir)
        self.assertEqual(result, f"{_OVERRIDE}/plan-redesign")


class TestReadersUseTheHandedSmm(_NamespaceCase):
    def test_orphan_listing_finds_branches_under_the_override(self):
        self._branch(f"{_OVERRIDE}/story-001-thing")
        found = branch_queries.list_orphan_story_branches(self.cwd, self.smm_dir)
        self.assertEqual(found, [f"{_OVERRIDE}/story-001-thing"])

    def test_free_listing_finds_branches_under_the_override(self):
        self._branch(f"{_OVERRIDE}/free-2026-01-01-spike")
        found = branching.list_free_branches(self.cwd, self.smm_dir)
        self.assertIn(f"{_OVERRIDE}/free-2026-01-01-spike", found)


class TestReadersAlsoSeePreUpgradeBranches(_NamespaceCase):
    """Discovery must span BOTH namespaces while an override is in force.

    Every branch cut before the override was read by anything carries the
    GIT-derived prefix. Globbing only the override drops all of them from
    kickoff's orphan triage and from free-close discovery on the very upgrade
    that introduces the override — the user's existing work goes invisible
    exactly when they most need it listed.

    ``branch_resolution._slug_rebuilt_sprint_branches`` already dual-searches
    for the identical upgrade problem, with a written rationale; these are the
    same problem seen from the read side. Both consumers of these lists only
    PRINT, so over-listing a branch that is genuinely yours costs nothing while
    under-listing hides work.
    """

    def test_free_listing_spans_both_namespaces(self):
        self._branch(f"{_OVERRIDE}/free-2026-01-01-spike")
        self._branch(f"{_GIT_NS}/free-2026-01-01-other")
        found = branching.list_free_branches(self.cwd, self.smm_dir)
        self.assertEqual(
            sorted(found),
            sorted(
                [
                    f"{_GIT_NS}/free-2026-01-01-other",
                    f"{_OVERRIDE}/free-2026-01-01-spike",
                ]
            ),
        )

    def test_orphan_listing_spans_both_namespaces(self):
        self._branch(f"{_OVERRIDE}/story-001-thing")
        self._branch(f"{_GIT_NS}/story-002-older")
        found = branch_queries.list_orphan_story_branches(self.cwd, self.smm_dir)
        self.assertEqual(
            sorted(found),
            sorted([f"{_GIT_NS}/story-002-older", f"{_OVERRIDE}/story-001-thing"]),
        )

    def test_a_branch_matching_both_globs_is_listed_once(self):
        """With no override recorded the two namespaces collapse to one, and a
        deduped listing is the difference between one entry and two."""
        no_override = Path(self.enterContext(tempfile.TemporaryDirectory()))
        _bf.write_system_context(no_override, stage=2)
        self._branch(f"{_GIT_NS}/free-2026-01-01-solo")
        found = branching.list_free_branches(self.cwd, no_override)
        self.assertEqual(found, [f"{_GIT_NS}/free-2026-01-01-solo"])

    def test_another_users_branches_are_still_excluded(self):
        """Dual-search widens to the SAME user's older prefix, not to everyone.
        Collision-avoidance across users is the whole point of namespacing."""
        self._branch("someoneelse/free-2026-01-01-theirs")
        found = branching.list_free_branches(self.cwd, self.smm_dir)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()

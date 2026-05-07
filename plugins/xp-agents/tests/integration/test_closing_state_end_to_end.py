#!/usr/bin/env python3
"""Sprint-069 story-007 capstone: end-to-end pins for the `closing` state.

Each test method maps 1:1 to a sprint-069 story-007 acceptance criterion
plus the singleton-lock invariant from concern ca4075cf9635. The
production code under test was shipped by stories 001-006:
  - story-001: VALID + IN_MOTION extended with `closing`
  - story-002: has_closing_stories + select_closing_stories helpers
  - story-003: find_closing_teammate_worktree (status=='closing' matcher)
  - story-004: list_orphan_story_branches uses ACTIVE_STORY_STATUSES
  - story-005: pre_tool_write re-arm + sprint_stop_gate suppress closing
  - story-006: xp-accept Step 1.5 reviewing->closing wiring

Capstone is verification-only — there is no production change here. A
failure on first run signals a regression in stories 001-006.

AC2 in sprint.json wording references `find_teammate_worktree_for_story`
but the actual status-aware singleton matcher is
`find_closing_teammate_worktree` (story-003 shipped a new function;
the AC text wasn't updated). Test name aligns with the shipped reality;
the AC drift is recorded as concern d9c322da92cc for sprint retro.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "smm"))

import branch_queries
import markers
import pre_tool_write
import sprint_store
import worktree
from _branching_fixtures import seed_sprint_with_stories
from _cli_helpers import run_cli
from _worktree_fixtures import make_teammate_worktree
from conftest import _IntegrationTestCase, _make_write_input

_SPRINT_CLI = Path(__file__).resolve().parents[2] / "smm" / "sprint_cli.py"


def _run_cas(smm_dir: Path, story_id: str, expected: str, new: str):
    """Run the CAS subcommand exactly the way xp-accept Step 1.5 does.

    Thin wrapper over the shared run_cli helper so the test reads at
    the same level as the SKILL.md invocation.
    """
    return run_cli(
        _SPRINT_CLI,
        [
            "update-story-if",
            story_id,
            "--expected",
            expected,
            "--new",
            new,
        ],
        smm_dir,
    )


class TestClosingStateEndToEnd(_IntegrationTestCase):
    """Capstone for sprint-069 — pins the closing-state singleton lock.

    Story-id naming (A1=AC1, B1=AC2, C1=AC3, D1=AC4, E1/E2=invariant)
    is left as test-authored shorthand mapping each test to the
    sprint-069 acceptance criterion it pins. The earlier rationale
    that unique ids 'sidestep the worktree-registry leak' no longer
    applies — _IntegrationTestCase.tearDown prunes worktrees per test.
    """

    def test_two_reviewing_one_transitions_to_closing(self):
        # AC1: 2 stories at `reviewing`; transitioning A -> `closing`
        # via the CAS subcommand (mirroring xp-accept Step 1.5) leaves
        # B at `reviewing`. State changes are independent; the
        # transition does not cross-contaminate.
        seed_sprint_with_stories(
            self.smm_dir,
            [("story-A1", "reviewing"), ("story-A2", "reviewing")],
        )
        result = _run_cas(self.smm_dir, "story-A1", "reviewing", "closing")
        self.assertEqual(result.returncode, 0, result.stderr)
        story_a = sprint_store.get_story(self.smm_dir, "story-A1")
        story_b = sprint_store.get_story(self.smm_dir, "story-A2")
        self.assertEqual(story_a["status"], "closing")
        self.assertEqual(story_b["status"], "reviewing")

    def test_double_promote_to_closing_is_singleton_safe(self):
        # Singleton-lock CAS guard: two consecutive CAS calls with the
        # same expected→new pair must succeed once and fail once. The
        # second call sees status=='closing' and returns nonzero without
        # mutating sprint.json. Pins concern c8118872ad2b — the AC1
        # promise that the reviewing→closing transition is CAS-guarded.
        seed_sprint_with_stories(self.smm_dir, [("story-A3", "reviewing")])
        first = _run_cas(self.smm_dir, "story-A3", "reviewing", "closing")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = _run_cas(self.smm_dir, "story-A3", "reviewing", "closing")
        self.assertEqual(
            second.returncode,
            1,
            "Second CAS call must report rc=1 (race-loss) — singleton lock "
            "means only one transition wins, and rc=1 is the orchestrator's "
            "skip-this-story signal (rc=2 would mean halt-on-corruption). "
            f"Got rc={second.returncode}; sprint.json contents: "
            f"{(self.smm_dir / 'sprint.json').read_text()}",
        )
        story = sprint_store.get_story(self.smm_dir, "story-A3")
        self.assertEqual(story["status"], "closing")

    def test_find_closing_teammate_worktree_returns_worktree(self):
        # AC2: with story-A at `closing` + a live teammate worktree,
        # find_closing_teammate_worktree returns (path, branch) for A.
        # No raise — the singleton lock holds.
        seed_sprint_with_stories(self.smm_dir, [("story-B1", "closing")])
        wt_path = make_teammate_worktree(self.tmpdir, "story-B1", "u/story-B1-closing")
        result = worktree.find_closing_teammate_worktree(self.smm_dir, str(self.tmpdir))
        self.assertIsNotNone(result, "expected a closing-worktree match")
        path, branch = self._assert_not_none(result)
        self.assertEqual(Path(path).resolve(), wt_path.resolve())
        self.assertEqual(branch, "u/story-B1-closing")

    def test_list_orphan_branches_excludes_closing_story(self):
        # AC3: a closing-status story branch must NOT appear in
        # list_orphan_story_branches. story-004's ACTIVE_STORY_STATUSES
        # pivot covers all in-motion + pre-branch states; this pins
        # closing specifically since it's the new state from this sprint.
        seed_sprint_with_stories(self.smm_dir, [("story-C1", "closing")])
        sprint_store.set_story_branch(self.smm_dir, "story-C1", "u/story-C1-closing")
        make_teammate_worktree(self.tmpdir, "story-C1", "u/story-C1-closing")
        orphans = branch_queries.list_orphan_story_branches(
            str(self.tmpdir), self.smm_dir
        )
        self.assertNotIn("u/story-C1-closing", orphans)

    def test_pre_tool_write_suppresses_accept_during_closing(self):
        # AC4: pre_tool_write fires with a closing-only sprint and the
        # .accept marker is NOT re-armed. story-005's suppression
        # extension covers reviewing OR closing; this pins the closing
        # half independently from test_pre_tool_write_gates' broader
        # mixed-state coverage.
        seed_sprint_with_stories(self.smm_dir, [("story-D1", "closing")])
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))
        pre_tool_write.run(_make_write_input(), smm_dir=self.smm_dir)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT),
            ".accept must not arm while a story is in `closing`",
        )

    def test_multi_closing_worktrees_raises(self):
        # Singleton-lock invariant (concern ca4075cf9635, the inverse
        # of AC2): two stories simultaneously at `closing` with live
        # worktrees is a broken iteration model. find_closing_teammate_
        # worktree must raise ValueError naming `closing` rather than
        # silently picking one. /xp-accept Step 1.5 is the production
        # contract that prevents this in normal operation.
        seed_sprint_with_stories(
            self.smm_dir,
            [("story-E1", "closing"), ("story-E2", "closing")],
        )
        make_teammate_worktree(self.tmpdir, "story-E1", "u/story-E1-closing")
        make_teammate_worktree(self.tmpdir, "story-E2", "u/story-E2-closing")
        with self.assertRaises(ValueError) as ctx:
            worktree.find_closing_teammate_worktree(self.smm_dir, str(self.tmpdir))
        self.assertIn("closing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

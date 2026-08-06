#!/usr/bin/env python3
"""Capstone (story-003): Milestone 3's `done`, proven at subprocess level.

M3's claim, verbatim from execution_plan.json:

    Given scheduled>0 and in-progress==0, when a Write targets a path outside
    the working tree, or HEAD is a free branch, then the write proceeds — and
    EnterPlanMode too; an in-repo story-branch write still blocks at both
    doors. And a frontier with a transitive dependency edge never fans out.

story-001 and story-002 each proved their half in-process, at their own unit
seam. This drives the REAL hooks as subprocesses over a real git repo and a real
sprint fixture: no mocks, no monkeypatching anywhere in this file.

A capstone can fail open too — by passing for the wrong reason — so every
ALLOW here is paired with a positive control identical in all but one field
(the model is test_stop_gate_in_place.py). Four specific false-greens are
designed against, each of which would stay green with the M3 code deleted:

  1. `pre_tool_write`'s gate short-circuits `not is_smm_write` BEFORE
     `not _is_out_of_story_scope(...)`. The harness puts `smm_dir` in its own
     mkdtemp, already outside the repo — so an "out-of-tree" target placed there
     is exempted by the REPAIRABILITY predicate and the SCOPE predicate never
     runs. `_OUT_OF_TREE` is therefore a THIRD location: outside the repo and
     outside the SMM dir. `test_out_of_tree_write_is_allowed` asserts that.

  2. `_deps_satisfied` requires a dependency to be `done`, so the intuitive
     antichain fixture (two scheduled stories, one depending on the other) puts
     the dependent OFF the frontier — leaving a 1-story frontier whose verdict
     is False from `len(frontier) >= 2`, not from the antichain guard. The
     done-bridge fixture below is the shape that actually exercises it.

  3. Two stories built from the default fixture share one file_domain
     (`src/auth.py`), so the verdict would read False for the COLLISION reason.
     Every story here gets an explicit disjoint domain, and the test asserts
     `overlap` is empty so collision is excluded as the cause.

  4. `_is_outside_tree` is checked before the branch leg, so the two exemptions
     must CROSS-NEGATE: the free-branch test writes INSIDE the tree, and the
     out-of-tree test runs on a NON-free branch. Otherwise each leg rides the
     other and neither is proven.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branch_names
from _bases import _PLUGIN_ROOT
from _branching_fixtures import get_current_branch_at
from conftest import (
    SPRINT_SCHEDULED_ONLY,
    _IntegrationTestCase,
    _make_plan_mode_input,
    _make_write_input,
    run_cli,
)
from conftest import make_sprint_dict as _make_sprint
from conftest import make_story_dict as _make_story

_SPRINT_CLI = _PLUGIN_ROOT / "smm" / "sprint_cli.py"

# A branch that is NOT free-shaped, so the free-branch leg cannot silently carry
# the out-of-tree test. `_FREE_BRANCH_RE` wants `<ns>/free-YYYY-MM-DD-<slug>`.
_STORY_BRANCH = "paulingalls/story-001-capstone"
_FREE_BRANCH = "paulingalls/free-2026-07-14-explore"


class TestScheduleGateDoors(_IntegrationTestCase):
    """Both doors of the schedule gate, driven as real hook subprocesses.

    Branch-mutating, and deliberately its own TestCase: a branch leaked onto the
    class-shared repo would hand the frontier suite a free-branch HEAD, so the
    two concerns do not share a repo.
    """

    def setUp(self):
        super().setUp()
        # The base setUp scrubs the worktree and index but NOT the checked-out
        # branch. Start every method from a known, non-free HEAD.
        self._reset_repo_to_main()
        # The gate window: one scheduled story, nothing in motion.
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)

    # -- fixture helpers ---------------------------------------------------

    def _checkout(self, branch: str) -> None:
        """Check out `branch`, restoring `main` afterwards.

        The cleanup is registered BEFORE the repo is mutated: a checkout that
        fails partway would otherwise leave the restore unregistered and leak
        the branch into every sibling test in the class.
        """
        self.addCleanup(self._restore_main, branch)
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

    def _restore_main(self, branch: str) -> None:
        """Put the shared repo back on `main` and drop `branch`.

        The `branch -D` fails LOUD (a leaked branch would make the next
        method's `checkout -b` collide) while the reset leg is quiet by
        `_reset_repo_to_main`'s contract, which the frontier suite shares. That
        asymmetry is safe here and not a teardown mask: every method in this
        class checks out EXPLICITLY, so a leaked HEAD cannot silently rewrite
        which branch a test runs on, and a cleanup that raises is reported by
        unittest ALONGSIDE the test's own failure, never instead of it.
        """
        self._reset_repo_to_main()
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

    def _in_tree_target(self) -> str:
        return str(self.tmpdir / "src" / "app.py")

    def _write(self, target: str):
        return self._run_script(
            "pre_tool_write.py",
            _make_write_input(
                tool_input={"file_path": target, "content": "x = 1"},
                cwd=str(self.tmpdir),
            ),
        )

    def _plan(self):
        return self._run_script(
            "pre_tool_plan_mode.py", _make_plan_mode_input(cwd=str(self.tmpdir))
        )

    # -- assertions --------------------------------------------------------

    def _assert_allowed(self, result: subprocess.CompletedProcess) -> None:
        """The tool call PROCEEDS — asserted against the hook PROTOCOL, not
        against what these two hooks happen to be implemented with today.

        Exit 0 EXACTLY, not `!= 2`: a hook that dies with a traceback exits 1,
        and PreToolUse treats a non-2 exit as non-blocking — so production would
        allow the write, for a catastrophic reason, and `!= 2` would call that a
        pass.

        And stdout must carry no BLOCK. PreToolUse has TWO block channels: exit
        2 with a reason on stderr, and exit 0 with a `decision: block` /
        `permissionDecision: deny` object on stdout. An ALLOW assertion that
        reads only the exit code calls the second kind of block a pass — the
        fail-open shape this milestone exists to close, reproduced one level up
        in the test meant to catch it. Today both doors block by exit 2 and this
        leg is quiet; the day one is rewritten to the JSON form, these tests must
        not go green on a denied write.

        `stdout == ""` would be wrong in the other direction: an ALLOW may
        legitimately carry an `additionalContext` nudge (check_tdd_order's
        reminder rides this exact channel), and pinning stdout empty would make
        the allow tests hostage to an unrelated nudge.
        """
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        if result.stdout.strip():
            payload = json.loads(result.stdout)  # non-JSON on stdout is itself a bug
            self.assertNotEqual(payload.get("decision"), "block", result.stdout)
            self.assertNotEqual(
                payload.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
                result.stdout,
            )

    def _assert_blocked(self, result: subprocess.CompletedProcess) -> None:
        """Exit 2 AND the schedule gate's own reason. `pre_tool_write` raises
        BlockedError from four other places (conflict detection, the lead gates,
        the corrupt-sprint hatch); a bare `rc == 2` can be an entirely different
        gate, which would make this control prove nothing."""
        self.assertEqual(result.returncode, 2)
        self.assertIn("xp-schedule", result.stderr)
        self.assertNotIn("cannot be read", result.stderr)

    def _assert_gate_window_is_real(self) -> None:
        """Fixture precondition: the sprint really is in the gate window.

        Without this, a fixture that quietly disarmed the gate would make every
        ALLOW below vacuous — green while watching nothing.
        """
        stories = json.loads((self.smm_dir / "sprint.json").read_text())["stories"]
        self.assertTrue(any(s["status"] == "scheduled" for s in stories))
        self.assertFalse(
            any(s["status"] in ("in-progress", "reviewing", "closing") for s in stories)
        )

    # -- the control: the gate still blocks what it is for ------------------

    def test_in_repo_story_branch_write_still_blocks(self):
        """Sole-variable control for BOTH allow tests below: same sprint, same
        gate, an in-tree target on a non-free branch. If this does not block,
        every ALLOW in this class is vacuous."""
        self._assert_gate_window_is_real()
        self._checkout(_STORY_BRANCH)

        self._assert_blocked(self._write(self._in_tree_target()))

    def test_in_repo_story_branch_plan_entry_still_blocks(self):
        """The same control for the second door — sole-variable control for
        `test_free_branch_plan_entry_is_allowed`."""
        self._assert_gate_window_is_real()
        self._checkout(_STORY_BRANCH)

        self._assert_blocked(self._plan())

    # -- exemption 1: out of the working tree ------------------------------

    def test_out_of_tree_write_is_allowed(self):
        """A memory file under ~/.claude is not this sprint's implementation.

        The target is a THIRD location — outside the repo AND outside the SMM
        dir — because a target under `smm_dir` would be exempted by
        `_is_smm_write` before `_is_out_of_story_scope` is ever called, and this
        test would pass with the whole out-of-tree leg deleted. HEAD is a
        non-free branch so the branch leg cannot carry it either. With both
        excluded, `_is_outside_tree` is the only predicate that can explain the
        allow.
        """
        self._assert_gate_window_is_real()
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        target = outside / "MEMORY.md"

        # Preconditions: neither in the tree nor in the SMM dir.
        self.assertNotIn(self.tmpdir.resolve(), target.resolve().parents)
        self.assertNotIn(self.smm_dir.resolve(), target.resolve().parents)

        self._checkout(_STORY_BRANCH)
        self.assertFalse(
            branch_names.is_free_branch(get_current_branch_at(self.tmpdir))
        )

        self._assert_allowed(self._write(str(target)))

    # -- exemption 2: the free branch, at BOTH doors ------------------------

    def test_free_branch_write_is_allowed(self):
        """On a free branch the sprint is not the frame at all; /xp-free-close
        is the right path. The target is INSIDE the tree, so `_is_outside_tree`
        cannot carry this — the branch leg is the only thing left."""
        self._assert_gate_window_is_real()
        self._checkout(_FREE_BRANCH)
        self.assertTrue(branch_names.is_free_branch(get_current_branch_at(self.tmpdir)))

        target = self._in_tree_target()
        self.assertIn(self.tmpdir.resolve(), Path(target).resolve().parents)
        self.assertNotIn(self.smm_dir.resolve(), Path(target).resolve().parents)

        self._assert_allowed(self._write(target))

    def test_free_branch_plan_entry_is_allowed(self):
        """The second door, in its own method so a plan-door regression names
        the plan door.

        Together with the test above this pins the half-open hatch
        `pre_tool_plan_mode`'s docstring warns about: a session that can WRITE
        on a free branch but cannot PLAN there is worse than no exemption.
        """
        self._assert_gate_window_is_real()
        self._checkout(_FREE_BRANCH)
        self.assertTrue(branch_names.is_free_branch(get_current_branch_at(self.tmpdir)))

        self._assert_allowed(self._plan())

    # -- the two predicates stay apart, at real branch fidelity -------------

    def test_corrupt_sprint_blocks_even_on_a_free_branch(self):
        """The "TWO PREDICATES, NEVER UNIONED" constraint, proven with a REAL
        free-branch checkout rather than a mocked `get_current_branch`.

        `is_smm_write` earns the corrupt-sprint escape by REPAIRABILITY;
        `_is_out_of_story_scope` says nothing about repairability. Union them
        into one `is_exempt` and the write door opens on a free branch while
        every sprint gate is blind — the exact fail-open family this milestone
        exists to close. Here the free branch must NOT rescue the write.
        """
        (self.smm_dir / "sprint.json").write_text("{ not json")
        self._checkout(_FREE_BRANCH)
        self.assertTrue(branch_names.is_free_branch(get_current_branch_at(self.tmpdir)))

        result = self._write(self._in_tree_target())

        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be read", result.stderr)


class TestFrontierVerdictCLI(_IntegrationTestCase):
    """The ready-frontier verdict through the real CLI subprocess.

    Deliberately NOT through skills/xp-schedule/scripts/preload.sh: that wraps
    the call in `|| echo '{...,"parallelizable":false,...}'`, so a totally
    broken CLI still reads `false` and the antichain assertion would pass on a
    crash.
    """

    # The done-bridge. story-002 is `done`, which SATISFIES story-004's
    # dependency and puts it on the frontier alongside story-003 — so the
    # frontier is 2 stories that nonetheless carry an edge between them, routed
    # THROUGH a story that is not itself on the frontier. That is the transitive
    # case a direct-edge-only check misses. Domains are explicit and disjoint so
    # a collision cannot be the cause of the verdict.
    #
    # BE HONEST ABOUT THE SHAPE THIS REQUIRES. `_deps_satisfied` already gates
    # frontier membership on every dep being `done`, so a frontier member can
    # never depend DIRECTLY on another (the dependency would be `scheduled`, and
    # the dependent would fall off the frontier). A transitive edge therefore
    # needs a bridge story that is `done` while an ancestor of it is still
    # `scheduled` — story-002 `done` depending on story-003 `scheduled`, below.
    # That state contradicts the promotion invariant (story-002 could only have
    # been promoted with its deps done), so the guard this pins fires ONLY on a
    # sprint whose dependency graph is already inconsistent: a hand-edited or
    # corrupted sprint.json, not an ordinary fan-out. Exhaustively checked over
    # every 4-story acyclic graph x status assignment — the guard fires on 105
    # of them and NONE satisfies "every done story's deps are done".
    #
    # The guard is worth having (a corrupt graph must not fan out teammates onto
    # branches missing their dependency's commits) and this pins it. What it is
    # not is protection against a mistake the normal lifecycle can make. Stating
    # that here so the next reader does not infer a hazard that cannot occur —
    # and so nobody "simplifies" the guard away on noticing half of it.
    def _stories(self, *, edge: bool) -> list[dict]:
        return [
            _make_story(
                id="story-002",
                status="done",
                dependencies=["story-003"],
                file_domain=["b.py — y"],
            ),
            _make_story(
                id="story-003",
                status="scheduled",
                dependencies=[],
                file_domain=["c.py — x"],
            ),
            _make_story(
                id="story-004",
                status="scheduled",
                dependencies=["story-002"] if edge else [],
                file_domain=["d.py — z"],
            ),
        ]

    def _report(self, *, edge: bool) -> dict:
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=self._stories(edge=edge)))
        )
        # conftest's shared CLI runner, not a hand-rolled subprocess.run: it is
        # the same invocation every other CLI suite makes, and it carries a
        # timeout — a hung `ready-frontier` fails instead of wedging the suite.
        result = run_cli(_SPRINT_CLI, ["ready-frontier"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_transitive_dependency_edge_forces_solo(self):
        """A frontier with an internal dependency edge never fans out.

        The two other terms of the `parallelizable` conjunction are asserted
        POSITIVELY, so neither can be the reason for the False: the frontier is
        size 2 (not the `len >= 2` term) and the overlap is empty (not the
        collision/glob term). That leaves `_frontier_has_internal_dependency` as
        the only term that can be false — which is the claim.
        """
        report = self._report(edge=True)

        self.assertEqual(report["frontier"], ["story-003", "story-004"])
        self.assertEqual(
            report["overlap"], {"collisions": {}, "glob_forced": False, "unscoped": []}
        )
        self.assertFalse(report["parallelizable"])

    def test_control_without_the_edge_the_same_frontier_fans_out(self):
        """Positive control: the identical sprint with story-004's dependency
        removed — same stories, same statuses, same disjoint domains, same
        frontier ids. It must fan out.

        Without this, `parallelizable is False` above could pass for the wrong
        reason (an empty frontier, a collision, a crashed CLI) and would still
        be green with the antichain guard deleted. This single delta is what
        makes the False attributable to the dependency edge and nothing else.
        """
        report = self._report(edge=False)

        self.assertEqual(report["frontier"], ["story-003", "story-004"])
        self.assertEqual(
            report["overlap"], {"collisions": {}, "glob_forced": False, "unscoped": []}
        )
        self.assertTrue(report["parallelizable"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for pre_tool_write.py's schedule gate.

Split from test_pre_tool_write_gates.py, which was at 483 lines and would have
crossed the 500-line cap once the scope-exemption cases landed. The schedule
gate is one mechanism with its own trigger window (scheduled stories exist, no
story in motion) and its own exemption set, so it earns its own file; the plan
review gate, question gate and accept marker stay behind.
"""

import contextlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_write
import worktree
from conftest import (
    SPRINT_IN_PROGRESS,
    SPRINT_SCHEDULED_ONLY,
    _HookTestCase,
    _make_write_input,
)

_STORY_BRANCH = "paulingalls/story-001-schedule-gate"
_FREE_BRANCH = "paulingalls/free-2026-07-13-scratch"


class TestPreToolWriteScheduleGate(_HookTestCase):
    """PreToolUse blocks non-plan/non-SMM writes in the schedule trigger window
    (scheduled stories exist, none in-progress) — forcing /xp-schedule. State-
    derived: self-clears the instant a frontier is promoted to in-progress.
    """

    def test_scheduled_only_blocks_code_write(self):
        """Scheduled stories, none in-progress -> code write blocked."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("xp-schedule", str(ctx.exception))

    def test_in_progress_self_clears_gate(self):
        """Once a frontier is in-progress, the gate no longer fires."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        self.assertIsNone(
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        )

    def test_no_sprint_does_not_block(self):
        """Free mode / no sprint -> gate never fires."""
        self.assertIsNone(
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        )

    def test_plan_file_exempt_in_trigger_state(self):
        """Plan-file writes are exempt even in the trigger window."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan",
            },
        )
        self.assertIsNone(pre_tool_write.run(plan_input, smm_dir=self.smm_dir))

    def test_smm_write_exempt_in_trigger_state(self):
        """Writes targeting the SMM dir are exempt even in the trigger window."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        smm_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": str(self.smm_dir / "scratch.json"),
                "content": "{}",
            },
        )
        self.assertIsNone(pre_tool_write.run(smm_input, smm_dir=self.smm_dir))


class _ScheduleGateFixture(_HookTestCase):
    """A repo root on disk, plus the two git probes stubbed at their seams.

    The repo lives under `mkdtemp()`, which on macOS hands back a path through
    a symlink (`/var/folders/...` -> `/private/var/folders/...`). That is the
    point, not an accident: `git rev-parse --show-toplevel` returns the PHYSICAL
    root, while the hook builds its target from the payload's `cwd`, which comes
    through the symlink. `_root` and `_cwd` below reproduce exactly that split,
    so a containment check that resolves only one side fails these tests — the
    same trap the schedule-frontier e2e catches against a real git repo.

    The git-root cache is a module global that outlives a test under
    `pytest -n auto`, so clear it on BOTH sides of every test.
    """

    def setUp(self):
        super().setUp()
        worktree._clear_git_root_cache()
        cwd = tempfile.mkdtemp(prefix="xp-gate-repo-")
        self.addCleanup(shutil.rmtree, cwd, ignore_errors=True)
        self._cwd = cwd  # through the symlink, as a hook payload carries it
        self._root = str(Path(cwd).resolve())  # physical, as git reports it

    def tearDown(self):
        worktree._clear_git_root_cache()
        super().tearDown()

    @contextlib.contextmanager
    def _probes(self, *, root: str | None, branch: str):
        """Stub the git root and the branch probe at their late-bound seams."""
        with (
            patch.object(
                pre_tool_write.worktree, "resolve_git_root", return_value=root
            ),
            patch.object(
                pre_tool_write.identity, "get_current_branch", return_value=branch
            ) as branch_probe,
        ):
            yield branch_probe

    def _write(self, target: str) -> dict:
        return _make_write_input(
            session_id="t",
            cwd=self._cwd,
            tool_input={"file_path": target, "content": "x"},
        )


class TestScheduleGateScopeExemption(_ScheduleGateFixture):
    """The gate's blast radius: it owns story code in the working tree, and
    nothing else.

    Two recorded misfires motivate this. It blocked a write to a memory file
    OUTSIDE the repo (satisfying it would have meant promoting a story against a
    customer pause), and it blocks work on a free branch, where the sprint is not
    the frame at all and /xp-free-close is the right path. Its intent survives
    both: do not write story code before the story is promoted.

    Every leg fails CLOSED. No git root, a git failure (empty branch), a detached
    HEAD -> not exempt, still blocked. An exemption is a claim, and a claim we
    cannot substantiate is not one we make.
    """

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)

    def test_out_of_tree_write_is_exempt(self):
        """A path outside the working tree is not story code, so it is exempt.

        The misfire: writing a memory file under ~/.claude was blocked, and the
        only way to satisfy the gate was to promote a story the customer had
        paused.
        """
        with self._probes(root=self._root, branch=_STORY_BRANCH):
            result = pre_tool_write.run(
                self._write("/Users/me/.claude/memory/note.md"), smm_dir=self.smm_dir
            )
        self.assertIsNone(result)

    def test_free_branch_in_tree_write_is_exempt(self):
        """On a free branch the sprint is not the frame — even in-repo writes go.

        Keyed on branch SHAPE (`<user>/free-YYYY-MM-DD-<slug>`), never a marker:
        a marker can be `rm`'d to bypass the gate, a branch name cannot be forged
        without actually being on that branch.
        """
        with self._probes(root=self._root, branch=_FREE_BRANCH):
            result = pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_in_tree_story_branch_write_still_blocks(self):
        """The intent pin. In-repo implementation code on a story branch is
        exactly what the gate exists to stop — narrowing its scope must not
        blunt it."""
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        self.assertIn("xp-schedule", str(ctx.exception))

    def test_no_git_root_still_blocks(self):
        """Not a repo (or git is broken) -> we cannot prove the write is out of
        scope, so we do not exempt it.

        Also pins the cheap leg's ordering: with no root there is nothing to
        contain a path, and the branch probe — an uncached subprocess — must
        never be paid.
        """
        with (
            self._probes(root=None, branch=_FREE_BRANCH) as branch_probe,
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(self._write("/elsewhere/x.py"), smm_dir=self.smm_dir)
        branch_probe.assert_not_called()

    def test_git_failure_empty_branch_still_blocks(self):
        """`get_current_branch` returns "" when git fails. "" is not a free
        branch, so the gate stands."""
        with (
            self._probes(root=self._root, branch=""),
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )

    def test_detached_head_still_blocks(self):
        """A detached HEAD reports the literal "HEAD" — not a free branch."""
        with (
            self._probes(root=self._root, branch="HEAD"),
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )

    def test_relative_target_resolves_against_cwd(self):
        """A relative target is in-tree, and must be resolved against cwd to see
        it. Left unresolved it looks like nothing the tree contains, and every
        relative write would slip the gate — the shape the real hook receives."""
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH),
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(self._write("src/app.py"), smm_dir=self.smm_dir)

    def test_symlinked_repo_root_is_still_in_tree(self):
        """Both sides of the containment check must be resolved.

        git reports the PHYSICAL root while the payload's cwd comes through a
        symlink. Resolve only the target and every in-tree write reads as
        out-of-tree — the gate would fail OPEN for the case it exists to catch.
        """
        self.assertNotEqual(self._cwd, self._root, "fixture lost its symlink")
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH),
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )

    def test_smm_write_exempt_even_when_smm_dir_is_inside_the_tree(self):
        """Pins the two-predicate decision: SMM-ness is NOT out-of-tree-ness.

        $SMM_DIR is an env var, so the SMM dir can sit anywhere — including
        inside the working tree. Here it does, on a story branch, so the
        out-of-scope predicate says "in scope" and only the SMM predicate exempts
        the write. Union the two and this case is the first thing to break; keep
        them apart and a corrupt sprint.json is still repairable via Write, which
        is the whole reason the SMM exemption exists.
        """
        smm_root = str(Path(self.smm_dir).resolve().parent)
        with self._probes(root=smm_root, branch=_STORY_BRANCH):
            result = pre_tool_write.run(
                self._write(str(self.smm_dir / "scratch.json")), smm_dir=self.smm_dir
            )
        self.assertIsNone(result)


class TestScheduleGateBranchProbeCost(_ScheduleGateFixture):
    """`get_current_branch` is an uncached subprocess on the Write hot path.

    It is the last term of the gate's `and` chain, so Python's left-to-right
    short-circuit is the entire mechanism keeping it off normal writes: the gate
    window (scheduled stories, none in motion) is rare, and every other state
    exits the chain before the probe.
    """

    def test_a_normal_write_never_probes_the_branch(self):
        """The common case — a story in progress — must not pay for a subprocess."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        with self._probes(root=self._root, branch=_STORY_BRANCH) as branch_probe:
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        branch_probe.assert_not_called()

    def test_the_gate_window_does_probe_the_branch(self):
        """Positive control for the assertion above.

        Without it, "never probes" passes forever while watching nothing: a probe
        that run() no longer calls at all (renamed, inlined, routed elsewhere)
        would satisfy assert_not_called while the laziness it claims to pin has
        become vacuous. In the one window where the exemption is live, the probe
        MUST be paid — exactly once.
        """
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH) as branch_probe,
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        branch_probe.assert_called_once()


class TestCorruptSprintKeepsThePredicatesApart(_ScheduleGateFixture):
    """The corrupt-sprint escape hatch, and why the two exemptions never merge.

    When sprint.json cannot be read, every sprint gate is blind, so the write
    door fails CLOSED. The ONE exemption is an SMM write: sprint.json lives in
    the SMM dir, so an SMM write is the repair, and a gate that blocks the only
    tool that can fix the file it is choking on has no recovery path.

    `_is_out_of_story_scope` earns no such exemption. "Outside the working tree"
    and "on a free branch" say nothing about repairability, and the tempting
    simplification — hoist both exemptions into one `is_exempt` and reuse it at
    both sites — would open the write door on a free branch while every sprint
    gate is blind. Until now the only thing forbidding that was a comment, and a
    comment does not fail the build. `test_free_branch_write_still_blocks...` is
    the executable form of decision daf978f26a8f: it goes red the moment the two
    predicates are unioned.
    """

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text("{ this is not json")

    def test_corrupt_sprint_blocks_a_code_write(self):
        """A bad read is not "no sprint" — it fails closed, it does not skip."""
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        self.assertIn("cannot be read", str(ctx.exception))

    def test_corrupt_sprint_still_lets_an_smm_write_repair_it(self):
        """The recovery path: the SMM exemption survives the blind-gate state."""
        with self._probes(root=self._root, branch=_STORY_BRANCH):
            result = pre_tool_write.run(
                self._write(str(self.smm_dir / "sprint.json")), smm_dir=self.smm_dir
            )
        self.assertIsNone(result)

    def test_free_branch_write_still_blocks_when_the_sprint_is_corrupt(self):
        """Union the two predicates and this is what breaks.

        A free branch exempts a write from the SCHEDULE gate, which is a claim
        about scope. It is not a claim that sprint.json is readable, so it buys
        nothing here: the sprint is corrupt, the gates are blind, and the door
        stays shut.
        """
        with (
            self._probes(root=self._root, branch=_FREE_BRANCH),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        self.assertIn("cannot be read", str(ctx.exception))

    def test_out_of_tree_write_still_blocks_when_the_sprint_is_corrupt(self):
        """The other half of the same claim: out-of-tree is not repairability."""
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_write.run(
                self._write("/Users/me/.claude/memory/note.md"), smm_dir=self.smm_dir
            )
        self.assertIn("cannot be read", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

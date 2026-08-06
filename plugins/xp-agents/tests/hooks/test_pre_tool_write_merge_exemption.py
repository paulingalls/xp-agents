#!/usr/bin/env python3
"""The schedule gate's merge-in-progress exemption (story-016 AC-6).

Its own file, sharing `_schedule_gate_fixture` with the scope-exemption suite:
that file was at 585 lines with these cases in it, and the repo's rule is to
extract rather than ratchet.

The exemption is STRUCTURAL — it reads MERGE_HEAD — rather than an opt-in marker,
because a marker can be left behind and would silently disarm the gate for the
rest of the session, while git creates MERGE_HEAD when the merge begins and
removes it when the merge ends. The exemption cannot outlive its reason.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_write
from _schedule_gate_fixture import _STORY_BRANCH, _ScheduleGateFixture
from conftest import SPRINT_IN_PROGRESS, SPRINT_SCHEDULED_ONLY


class TestScheduleGateMergeExemption(_ScheduleGateFixture):
    """A merge in progress opens the gate — the third leg of the scope predicate.

    The recorded misfire: a v5.5.1 back-merge onto a sprint branch, with stories
    scheduled and none in motion. Resolving the conflicts meant WRITING to the
    conflicted files, the gate refused every one, and the only way through was a
    procedural workaround. The commit gate already has an escape for exactly this
    case; the write gate had none.

    STRUCTURAL, not an opt-in marker, and PER FILE rather than per repo. A
    marker can be left behind and would silently disarm the gate for the rest of
    the session — but so does MERGE_HEAD, which an abandoned merge leaves on
    disk indefinitely while exempting every write in the tree. An unmerged index
    entry names the one file whose conflict is unresolved and vanishes the
    moment that resolution is staged, so the exemption cannot outlive its
    reason.

    Every case here writes IN-TREE on a NON-free branch, so neither sibling leg
    can carry the result: the conflict probe is the only thing that can explain
    an allow, and its absence the only thing that can explain a block.
    """

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)

    def _in_tree(self) -> str:
        return str(Path(self._cwd) / "src" / "app.py")

    def test_a_conflicted_file_is_exempt_on_an_in_tree_story_branch(self):
        with self._probes(
            root=self._root, branch=_STORY_BRANCH, conflicted=("src/app.py",)
        ):
            result = pre_tool_write.run(
                self._write(self._in_tree()), smm_dir=self.smm_dir
            )
        self.assertIsNone(result)

    def test_an_unconflicted_file_is_still_blocked_while_a_merge_runs(self):
        """The blast radius MERGE_HEAD could not limit.

        A merge is in progress and a DIFFERENT file is conflicted, so the
        boolean probe answered "merge" and exempted this write too. Brand-new
        story implementation against a customer pause is not conflict
        resolution — and an abandoned merge, never committed and never aborted,
        made that exemption permanent.
        """
        with (
            self._probes(
                root=self._root, branch=_STORY_BRANCH, conflicted=("src/other.py",)
            ),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_write.run(self._write(self._in_tree()), smm_dir=self.smm_dir)
        self.assertIn("xp-schedule", str(ctx.exception))

    def test_no_conflict_still_blocks(self):
        """The paired control, identical in every field but the merge state.

        Without it the exemption test above passes just as well with the whole
        gate deleted — which is the failure this story's own instructions call
        out. One variable, opposite verdicts.
        """
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH, conflicted=()),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_write.run(self._write(self._in_tree()), smm_dir=self.smm_dir)
        self.assertIn("xp-schedule", str(ctx.exception))

    def test_the_exemption_does_not_depend_on_the_branch_shape(self):
        """A conflict is a conflict. The back-merge that motivated this landed on
        a SPRINT branch, which is neither a story branch nor free — so the leg
        must not be scoped to any branch shape."""
        sprint_branch = "paulingalls/sprint-004"
        with self._probes(
            root=self._root, branch=sprint_branch, conflicted=("src/app.py",)
        ):
            result = pre_tool_write.run(
                self._write(self._in_tree()), smm_dir=self.smm_dir
            )
        self.assertIsNone(result)

    def test_a_conflict_does_not_rescue_a_write_with_no_git_root(self):
        """Fail closed at the same place every sibling leg does. With no root
        there is nothing to contain a path, and the out-of-tree leg returns
        early — so neither subprocess is paid and nothing is exempt, conflict or
        not."""
        with (
            self._probes(
                root=None, branch=_STORY_BRANCH, conflicted=("src/app.py",)
            ) as probes,
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(self._write(self._in_tree()), smm_dir=self.smm_dir)
        probes.merge.assert_not_called()


class TestScheduleGateMergeProbeCost(_ScheduleGateFixture):
    """`unmerged_paths` is a second uncached subprocess on the Write hot path.

    Its own cost pin, paired with the branch probe's below rather than folded
    into it: two probes in one `and` chain need two claims, and a single
    assertion would go quiet the moment either was reordered.
    """

    def test_a_normal_write_never_probes_for_a_merge(self):
        """The common case — a story in progress — must not pay for it."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        with self._probes(root=self._root, branch=_STORY_BRANCH) as probes:
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        probes.merge.assert_not_called()

    def test_the_gate_window_does_probe_for_a_merge(self):
        """Positive control for the assertion above — without it, "never probes"
        stays green forever over a probe run() no longer calls at all."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        with (
            self._probes(root=self._root, branch=_STORY_BRANCH) as probes,
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_write.run(
                self._write(str(Path(self._cwd) / "src" / "app.py")),
                smm_dir=self.smm_dir,
            )
        probes.merge.assert_called_once()

    def test_an_out_of_tree_write_pays_neither_subprocess(self):
        """Path math first. The out-of-tree leg is pure `Path` work and exits the
        chain, so a memory-file write in the gate window costs no fork at all."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        with self._probes(root=self._root, branch=_STORY_BRANCH) as probes:
            pre_tool_write.run(
                self._write("/Users/me/.claude/memory/note.md"), smm_dir=self.smm_dir
            )
        probes.merge.assert_not_called()
        probes.branch.assert_not_called()


if __name__ == "__main__":
    unittest.main()

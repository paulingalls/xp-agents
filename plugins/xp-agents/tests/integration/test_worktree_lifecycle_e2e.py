#!/usr/bin/env python3
"""Milestone 6 capstone: the worktree lifecycle composes end to end.

Every leg of this lifecycle is already tested on its own — bootstrap fires on
create, teardown fires before removal, coordination clears on the key
`post_tool_use` actually registered. What no other suite does is bind the
CREATE leg and the REMOVE leg to ONE worktree in ONE flow, which is the only
place four failure modes can show up:

  1. Nothing else declares BOTH `stack.worktree_bootstrap` and
     `stack.worktree_teardown` at once. Every other suite declares one.
  2. Nothing proves teardown can SEE what bootstrap made. That is the
     milestone's literal claim -- "tear down what we created" -- and it was
     unasserted until this file.
  3. The register-key/clear-key round trip is never driven through the
     production create path, where a name flows create -> cwd ->
     resolve_agent_id -> registered key -> removal name -> cleared key.
     `clear_coordination_agent` is `if agent_id in data: del data[agent_id]`,
     so a mismatched key no-ops SILENTLY while every other assertion still
     passes.
  4. `remove_worktree` -- the branch-deleting entry point -- is never
     exercised with `smm_dir` at all; the teardown suites call
     `remove_worktree_dir` directly or go through `cleanup_teammate`.
  5. There are TWO create legs and they gate bootstrap differently:
     `spawn_teammate.create_worktree` on `smm_dir is not None`, the
     `WorktreeCreate` hook (`worktree_create.run`) on the teammate name
     prefix. Binding only the first leaves the GATED one unbound end to end,
     and the two also cut different branch names. Both are bound below.

AND THE TRAP UNDER ALL OF IT: `create_worktree` -> `cleanup_existing` ->
`remove_worktree(smm_dir=)` runs the declared TEARDOWN too, against whatever
stale tree sits at the path. So a marker observed only at the END of a test is
ambiguous about which call wrote it. Every test here pins the marker ABSENT
after create, which is what makes the final read attributable to the removal.

HOW ONE COMMAND CARRIES THE WHOLE CLAIM. The declared teardown is

    test -f provisioned.txt && echo torn > "$SMM_DIR/<marker>"

so its marker appears ONLY IF bootstrap's artifact is visible when teardown
runs. That single conjunction discharges 1, 2 and the ordering claim together:
the marker exists iff both commands were declared, bootstrap ran at create,
teardown ran at remove, teardown ran BEFORE the removal destroyed the tree, and
teardown could see what bootstrap wrote. Drop the bootstrap declaration and the
marker vanishes -- verified by mutation, not assumed.

TWO PLACEMENT RULES, both non-negotiable and both learned by sibling suites:
bootstrap's artifact goes INSIDE the worktree (teardown must find it), and
teardown's marker goes OUTSIDE it, in `$SMM_DIR` -- an artifact written inside
is destroyed by the very removal that call performs, making "ran" and "never
ran" indistinguishable. `run_teardown` injects a resolved absolute `SMM_DIR`
via `_subprocess_env.smm_child_env`, which is what makes the outside write
addressable.

The declared commands run `shell=True` through /bin/sh and are NOT covered by
the suite-wide spawn guard (it blocks `argv[0] == "claude"`), so every command
here stays an `echo`/redirect/`test -f` against the temp tree.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _IntegrationTestCase

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import coordination
import post_tool_use
import spawn_teammate
import worktree
import worktree_create
from _system_context_fixtures import valid_doc, write_doc

# Must start with the teammate prefix: `worktree.remove_worktree_dir` gates the
# coordination clear on `identity.is_teammate_agent_id(name)`, and a
# non-conforming name skips that clear with no complaint -- the test would go
# green having proved nothing about the round trip. Distinct from every sibling
# suite's name because the temp repo is class-scoped.
_WT_NAME = "worktree-story-lifecycle-capstone"

# The platform-hook leg's worktree. Same prefix requirement, for the second
# reason too: `worktree_create.run` gates its bootstrap on that prefix.
_HOOK_WT_NAME = "worktree-story-lifecycle-hooked"

# Written by bootstrap INSIDE the worktree; read by teardown.
_PROVISIONED = "provisioned.txt"

# Written by teardown OUTSIDE the worktree, into $SMM_DIR.
_TORN_MARKER = "torn-lifecycle-capstone.txt"

_BOOTSTRAP_CMD = f"echo provisioned > {_PROVISIONED}"
_TEARDOWN_CMD = f'test -f {_PROVISIONED} && echo torn > "$SMM_DIR/{_TORN_MARKER}"'


def _local_branches(cwd: str) -> list[str]:
    """Local branch names, so "the branch is gone" is asserted against git."""
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.stdout.split()


class _LifecycleTestCase(_IntegrationTestCase):
    """Declares the lifecycle pair and drives the production create path."""

    def declare(self, *, bootstrap: str | None, teardown: str | None) -> None:
        """Write a real system_context.json carrying either/both declarations.

        Passing None for one leg is how the mutation tests below prove the
        two legs are genuinely linked rather than independently green.
        """
        doc = valid_doc()
        if bootstrap is not None:
            doc["stack"]["worktree_bootstrap"] = bootstrap
        if teardown is not None:
            doc["stack"]["worktree_teardown"] = teardown
        write_doc(self.smm_dir, doc)

    def create(self, name: str = _WT_NAME) -> str:
        """Create through the PRODUCTION path, which is what runs bootstrap."""
        return spawn_teammate.create_worktree(
            name, str(self.tmpdir), smm_dir=self.smm_dir
        )

    def register_coordination(self, wt_path: str) -> None:
        """Register through the REAL hook, never a hand-typed key.

        Hand-typing `update_coordination(smm_dir, "worktree-story-...")` would
        make the later clear match by coincidence of two identical literals in
        this file, proving nothing about production's create -> cwd ->
        resolve_agent_id derivation. Driving post_tool_use is the whole point:
        the key under test is the one production computes.
        """
        post_tool_use.run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(Path(wt_path) / "touched.py")},
                "cwd": wt_path,
            },
            smm_dir=self.smm_dir,
        )

    def torn_marker(self) -> Path:
        return self.smm_dir / _TORN_MARKER


class TestLifecycleComposes(_LifecycleTestCase):
    """Create -> bootstrap -> register -> remove -> teardown -> clear.

    Deliberately ONE test. A standalone "bootstrap provisions the worktree on
    create" case lived here and was deleted: it re-asserted, through the same
    `create_worktree(name, cwd, smm_dir=...)` call, exactly what
    `hooks/test_spawn_teammate_bootstrap.TestBootstrapRuns` already owns, and
    the capstone below now pins the same artifact as a PRECONDITION, so no
    diagnostic is lost. It also cost something: a second method creating a
    worktree at the same path made the capstone's central assertion depend on
    tearDown's sweep having removed it first (see the create-time-teardown note
    in the test), which is not a dependency a capstone should carry.
    """

    def test_teardown_sees_what_bootstrap_made_and_coordination_dies_with_it(self):
        """The capstone. Every link in one flow."""
        self.declare(bootstrap=_BOOTSTRAP_CMD, teardown=_TEARDOWN_CMD)
        wt_path = self.create()

        self.assertTrue(
            (Path(wt_path) / _PROVISIONED).is_file(),
            "precondition: bootstrap must run inside the new worktree at create "
            "time -- the artifact the teardown below is contracted to see",
        )
        # THE MARKER MUST NOT EXIST YET, and this is not a formality.
        # `create_worktree` -> `cleanup_existing` -> `remove_worktree(smm_dir=)`
        # ALSO runs the declared teardown, against whatever stale tree sits at
        # this path. So a marker read at the end is ambiguous on its own: it
        # could have been written by the CREATE call rather than by the removal
        # under test, and the whole "teardown runs at removal" claim would be
        # satisfied by the wrong caller. Pinning it absent here makes the final
        # assertion attributable to `remove_worktree` alone, independently of
        # what any sibling test or a skipped cleanup left on disk.
        self.assertFalse(
            self.torn_marker().is_file(),
            "no removal has happened yet -- a marker here means create-time "
            "cleanup tore down a stale tree, and the final assertion would "
            "credit the removal for it",
        )

        # A sibling entry that must SURVIVE. Without it, a removal that simply
        # truncated .coordination.json would satisfy the final assertion.
        coordination.update_coordination(
            self.smm_dir, "worktree-story-bystander", ["x"]
        )

        self.register_coordination(wt_path)
        before = coordination.read_coordination(self.smm_dir)
        self.assertIn(
            _WT_NAME,
            before,
            "precondition: post_tool_use must have registered the worktree's own "
            "key -- without this the final assertion passes vacuously",
        )

        verdict = worktree.remove_worktree(
            _WT_NAME, str(self.tmpdir), smm_dir=self.smm_dir
        )

        self.assertTrue(
            self.torn_marker().is_file(),
            "teardown must run before removal AND see bootstrap's artifact -- "
            f"the declared command is {_TEARDOWN_CMD!r}, so a missing marker "
            "means one of those two failed",
        )
        self.assertFalse(Path(wt_path).is_dir(), "the worktree directory must be gone")

        after = coordination.read_coordination(self.smm_dir)
        self.assertNotIn(
            _WT_NAME, after, "the worktree's coordination entry must not survive"
        )
        self.assertIn(
            "worktree-story-bystander",
            after,
            "a sibling's entry must survive -- proving the clear was targeted, "
            "not a wipe of the whole file",
        )
        # The SPECIFIC verdict, not merely "some BranchRemoval" -- every return
        # path of `remove_worktree` is one, so an isinstance check is a
        # tautology that `NO_BRANCH` (nothing happened at all) would satisfy.
        # The worktree's branch was cut from `main` and carries no commits, so
        # `delete_branch` proves it merged and deletes it: the branch leg of the
        # removal really ran, not just the directory leg.
        self.assertIs(verdict, worktree.BranchRemoval.DELETED_MERGED)


class TestTheLinkIsReal(_LifecycleTestCase):
    """Mutations proving the capstone above cannot pass for the wrong reason.

    These are not extra coverage; they are the evidence that the one assertion
    carrying the milestone's claim is load-bearing. Each removes exactly one
    link and pins that the marker or the key stops behaving.
    """

    def test_without_bootstrap_the_teardown_marker_never_appears(self):
        """Drop ONLY the bootstrap declaration.

        Teardown is still declared and still runs -- `run_teardown` never
        raises -- but its `test -f` guard now fails, so no marker. If a marker
        appeared here, the capstone's central assertion would be satisfied by
        teardown alone and would prove nothing about "tear down what we
        created".
        """
        self.declare(bootstrap=None, teardown=_TEARDOWN_CMD)
        wt_path = self.create()
        self.assertFalse(
            (Path(wt_path) / _PROVISIONED).is_file(),
            "no bootstrap declared, so nothing should have provisioned",
        )
        self.assertFalse(
            self.torn_marker().is_file(),
            "nothing has been removed yet -- see the create-time teardown trap "
            "in the module docstring",
        )

        worktree.remove_worktree(_WT_NAME, str(self.tmpdir), smm_dir=self.smm_dir)

        # Positive control, same reason as the paired assertions below: a
        # marker-absent assertion is also satisfied by a removal that never
        # happened, and then this proves nothing about the `test -f` guard.
        self.assertFalse(
            Path(wt_path).is_dir(),
            "the removal must actually have run -- otherwise 'no marker' says "
            "nothing about the guard this test is pinning",
        )
        self.assertFalse(
            self.torn_marker().is_file(),
            "the marker must depend on bootstrap's artifact, not merely on "
            "teardown having been declared",
        )

    def test_a_non_matching_removal_name_leaves_the_entry_behind(self):
        """The silent-no-op trap the milestone change-zone note flags.

        `clear_coordination_agent` deletes by exact key. Remove under a name
        that is not the registered one and the entry survives with no error
        anywhere -- which is why the capstone drives the real registrar
        instead of trusting two matching literals.

        Asserted as a PAIR, and it has to be. "The entry survived" alone is a
        bare negative that any never-reached clear satisfies just as well as an
        exact-key miss: a `removed_ok` that came back False, a tightened
        `is_teammate_agent_id`, a removal that returned early -- each leaves the
        entry behind while proving nothing about key matching. Registering the
        REMOVAL name too turns the same single call into its own positive
        control: that entry must DIE. One dies, one lives, so the clear
        provably ran and provably discriminated by exact key.
        """
        self.declare(bootstrap=_BOOTSTRAP_CMD, teardown=_TEARDOWN_CMD)
        wt_path = self.create()
        self.register_coordination(wt_path)

        # A different teammate-shaped name: passes is_teammate_agent_id, so the
        # clear is attempted, and still matches the registered key not at all.
        other = "worktree-story-not-the-registered-one"
        coordination.update_coordination(self.smm_dir, other, ["y"])
        before = coordination.read_coordination(self.smm_dir)
        self.assertIn(_WT_NAME, before)
        self.assertIn(other, before)

        worktree.remove_worktree_dir(other, str(self.tmpdir), smm_dir=self.smm_dir)

        after = coordination.read_coordination(self.smm_dir)
        self.assertNotIn(
            other,
            after,
            "positive control: the removal name's OWN entry must be cleared -- "
            "without this the assertion below passes for a clear that was "
            "never reached at all",
        )
        self.assertIn(
            _WT_NAME,
            after,
            "a mismatched key must leave the entry behind -- this is the "
            "silent failure the capstone's key round trip exists to catch",
        )


class TestThePlatformHookLegComposesToo(_LifecycleTestCase):
    """The OTHER create path, bound to the same removal.

    There are two, and the capstone above drives only one.
    `spawn_teammate.create_worktree` bootstraps whenever `smm_dir` is passed —
    no name gate at all. The teammate-prefix gate on bootstrap lives HERE, in
    `worktree_create.run`, the platform `WorktreeCreate` hook leg that fires
    for every platform worktree (teammate spawn, Explore, ad-hoc alike). So the
    create path that CARRIES the gate was the one left unbound end to end.

    Deliberately narrow: the capstone owns the coordination round trip and the
    targeted-clear proof, and re-asserting them here would duplicate it without
    adding a path. What only this leg reaches is (a) bootstrap running past the
    prefix gate rather than past a `smm_dir is not None` check, and (b) a
    worktree whose BRANCH name is not its DIRECTORY name — this hook cuts
    `worktree-<name>`, spawn cuts `<name>` — which is exactly the divergence
    `remove_worktree_dir` re-derives from the tree's HEAD before the branch can
    be deleted. The verdict below is where that derivation is pinned.
    """

    def create_via_hook(self, name: str = _HOOK_WT_NAME) -> str:
        """Drive the real hook entry point, with no create-side mocking."""
        return worktree_create.run(
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": name,
            }
        )

    def test_the_hook_created_worktree_is_torn_down_and_its_branch_deleted(self):
        self.declare(bootstrap=_BOOTSTRAP_CMD, teardown=_TEARDOWN_CMD)

        wt_path = self.create_via_hook()

        self.assertTrue(
            (Path(wt_path) / _PROVISIONED).is_file(),
            "precondition: the prefix-gated bootstrap must have run -- "
            f"{_HOOK_WT_NAME!r} carries the teammate prefix the gate keys on",
        )
        self.assertFalse(
            self.torn_marker().is_file(),
            "nothing has been removed yet",
        )

        verdict = worktree.remove_worktree(
            _HOOK_WT_NAME, str(self.tmpdir), smm_dir=self.smm_dir
        )

        self.assertTrue(
            self.torn_marker().is_file(),
            "teardown must see the artifact the HOOK leg's bootstrap wrote, "
            "not only the one spawn's leg writes",
        )
        self.assertFalse(Path(wt_path).is_dir(), "the worktree directory must be gone")
        # DELETED_MERGED, not merely "a verdict": the hook checked out
        # `worktree-<name>`, so reaching this outcome means the branch was
        # re-derived from the tree's HEAD rather than assumed equal to `name`.
        # Had it been assumed, `delete_branch` would have been handed a ref that
        # does not exist and answered REFUSED_UNMERGED, leaving a live branch.
        self.assertIs(verdict, worktree.BranchRemoval.DELETED_MERGED)
        self.assertNotIn(
            f"worktree-{_HOOK_WT_NAME}",
            _local_branches(str(self.tmpdir)),
            "the branch the hook cut must not outlive the worktree",
        )


if __name__ == "__main__":
    unittest.main()

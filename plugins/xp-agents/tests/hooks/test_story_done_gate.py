#!/usr/bin/env python3
"""The mark-done gate: a story cannot be marked done past a merge that never happened.

Last session story-005 was marked `done` while it was NOT merged. `close_common`'s
merge hit a transient `.git/index.lock`, and the close pipeline carried on.

The failure was never silent at the GIT level -- `_merge_into_target` sys.exit(1)s
on a failed merge, printing git's stderr. The silence is that the caller is an LLM
following skill prose: /xp-accept Step 2 closes, Step 4 marks done, and nothing
deterministic stands between them. A louder error cannot fix that. Only a gate can.

The proof is derived from GIT, never from a recorded token: branch ABSENCE proves the
merge, because no delete path deletes an unmerged branch -- `delete_branch` proves
`is_merged_into` itself before deleting (it cannot delegate that to `git branch -d`,
which happily deletes a branch merged only to its UPSTREAM; see
test_branching_delete.TestDeleteBranchUpstreamLoophole). A token would have to be
written, and a write that fails after a successful merge would strand the story
permanently un-markable.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash
import sprint_store
from _branching_fixtures import append_commit, init_repo, write_system_context
from conftest import _HookTestCase, _make_bash_input, run_cli

_BASE = "main"
_STORY_BRANCH = "paulingalls/story-001-thing"
_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"


def _done_cmd(story_id: str = "story-001", extra: str = "") -> str:
    return (
        f"python3 /path/to/sprint_cli.py --smm-dir /tmp/smm "
        f"update-story {story_id} done{extra}"
    )


class _GateCase(_HookTestCase):
    """A real git repo plus a sprint whose story names a real branch."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        init_repo(self.repo)
        write_system_context(self.smm_dir, 2)

    # -- fixture helpers ---------------------------------------------------

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, capture_output=True, check=True)

    def _unmerged_story_branch(self) -> None:
        """A story branch holding a commit the base does not have."""
        self._git("checkout", "-b", _STORY_BRANCH)
        append_commit(self.repo, "story.txt")
        self._git("checkout", _BASE)

    def _story(
        self,
        story_id: str = "story-001",
        *,
        status: str = "closing",
        branch: str | None = _STORY_BRANCH,
    ) -> dict:
        story = {
            "id": story_id,
            "title": "Test",
            "status": status,
            "dependencies": [],
            "milestone_ref": "test",
            "design_sources": "test",
            "context": "test",
            "file_domain": [],
            "interface_contracts": [],
            "acceptance_criteria": ["test"],
        }
        if branch is not None:
            story["branch_name"] = branch
        return story

    def _seed_stories(self, *stories: dict) -> None:
        sprint_store.save_sprint(
            self.smm_dir,
            {
                "sprint_id": "sprint-001",
                "goal": "g",
                "started": "2026-04-22",
                "milestone": "test",
                "branch_name": _BASE,
                "stories": list(stories),
            },
        )

    def _seed_sprint(
        self, *, status: str = "closing", branch: str | None = _STORY_BRANCH
    ):
        self._seed_stories(self._story(status=status, branch=branch))

    def _run(self, cmd: str):
        return pre_tool_bash.run(
            _make_bash_input(command=cmd, cwd=self.repo), smm_dir=self.smm_dir
        )


class TestUnmergedStoryCannotBeMarkedDone(_GateCase):
    """The bug, reproduced: story-005's exact shape."""

    def test_unmerged_branch_blocks_mark_done(self):
        """The story's branch still exists and is NOT an ancestor of its base --
        i.e. the merge never landed. Marking it done records a lie.

        This is story-005: the merge failed on an index.lock, and mark-done ran
        anyway. Today `run` returns None here (allows), which IS the shipped bug.
        """
        self._unmerged_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd())

    def test_the_block_names_the_branch_and_the_repair(self):
        """A gate that refuses without saying how to recover is the trap this
        project keeps re-learning. Name the branch, the base, and the way out."""
        self._unmerged_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(_done_cmd())

        msg = str(caught.exception)
        self.assertIn(_STORY_BRANCH, msg)
        self.assertIn(_BASE, msg)
        self.assertIn("--force-unmerged", msg)


class TestGateMatchesInvocationsNotProse(_GateCase):
    """The gate must fire on the COMMAND, not on text that merely describes it.

    Found by dogfooding: committing this very story was BLOCKED because the commit
    MESSAGE documents the flag -- the heredoc body contains the words
    `update-story <id> done`, and the regex scanned the whole command string. A
    gate that blocks `git commit` because of what the message SAYS is a
    false-positive that teaches people to work around gates.

    Pre-existing in the ACCEPT gate; inherited the moment the merge gate reused its
    regex. Both are fixed by requiring the CLI itself to be in the command.
    """

    def test_a_commit_message_describing_the_command_is_not_blocked(self):
        """The exact shape that blocked this story's own commit.

        Asserts NOT-BLOCKED rather than returns-None: a `git commit` legitimately
        picks up advisory context from other rules (the direct-to-main nudge, say),
        and those are strings, not refusals. The claim under test is that the merge
        gate does not RAISE on prose.
        """
        self._unmerged_story_branch()
        self._seed_sprint()
        commit = (
            "git commit -F - <<'EOF'\n"
            "[story-007] The merge gate gets an escape hatch\n\n"
            'The bypass is `update-story story-001 done --force-unmerged "why"`,\n'
            "enforced by the CLI rather than by prose.\n"
            "EOF"
        )

        result = self._run(commit)  # must not raise

        self.assertNotIn("not merged", result or "")

    def test_a_real_cli_invocation_is_still_blocked(self):
        """The control. Tightening the regex must not disarm the gate -- the whole
        point is that a genuine `sprint_cli.py ... update-story X done` still
        refuses when the merge never landed."""
        self._unmerged_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd())

    def test_the_shipped_invocation_shape_is_blocked(self):
        """THE shape the pipeline actually runs -- /xp-accept Step 4, verbatim.

        The skill wraps the command with a shell line-continuation, so `sprint_cli.py`
        lands on one line and `update-story <id> done` on the next. A regex that
        requires them on the SAME line matches every hand-written single-line test
        above and NONE of production: the gate would be dead exactly where it is
        needed, and the ACCEPT gate (which shares the regex) would silently lose
        coverage it already had.
        """
        self._unmerged_story_branch()
        self._seed_sprint()
        shipped = (
            "python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir /tmp/smm \\\n"
            "  update-story story-001 done"
        )

        with self.assertRaises(_common.BlockedError):
            self._run(shipped)


class TestGateFailsClosedOnBadReads(_GateCase):
    """Unknowable == blocked. The gate never waves a mark-done through blind."""

    def test_corrupt_sprint_blocks(self):
        """A corrupt sprint.json makes "did it merge?" unknowable.

        SprintCorruptError SUBCLASSES ValueError, and the "no sprint" arm returns
        None -- so catching the parent first would read a corrupt sprint as "nothing
        to check" and PASS. That is a fail-open on exactly the unreadable state that
        must fail shut, which is why the order of those two excepts is load-bearing.
        """
        self._unmerged_story_branch()
        (self.smm_dir / "sprint.json").write_text("{ not json")

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd())

    def test_unresolvable_base_blocks(self):
        """The sprint names a base branch that does not exist in the repo, so the
        story's merge target is unknowable. `get_story_base_branch_required` raises
        rather than degrading to the primary branch -- a silent primary would check
        a sprint-branch story against `main` and wrongly block every honest close."""
        self._unmerged_story_branch()
        self._seed_sprint()
        sprint = sprint_store.load_sprint_required(self.smm_dir)
        sprint["branch_name"] = "paulingalls/sprint-999-vanished"
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd())

    def test_a_git_that_cannot_be_read_blocks(self):
        """The keystone's pass arm is reached by a FAILED git read, not just a
        deleted branch.

        `branch_exists` shells out to `git rev-parse --verify refs/heads/<b>` and
        answers False on ANY non-zero exit — branch genuinely gone, cwd not a repo,
        git broken. The gate reads that False as "deleted, therefore merged" and
        PASSES. A bad read must fail CLOSED (project convention: gates fail closed
        on a corrupt file or a failed subprocess; only annotation-only reads degrade
        quiet).
        """
        self._unmerged_story_branch()
        self._seed_sprint()
        not_a_repo = tempfile.TemporaryDirectory()
        self.addCleanup(not_a_repo.cleanup)

        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(
                _make_bash_input(command=_done_cmd(), cwd=not_a_repo.name),
                smm_dir=self.smm_dir,
            )


class TestGateDoesNotBlockLegitimateCloses(_GateCase):
    """The wrongly-fail-closed matrix.

    A gate that refuses an honest close is a WORSE bug than the one it fixes: it
    would brick the pipeline on every story. Each of these is a real path through
    /xp-accept, and each must pass.
    """

    def test_deleted_branch_passes(self):
        """THE KEYSTONE, and the normal close path. The merge deleted the story
        branch, and mark-done runs afterwards -- so by now the branch is GONE.

        Absence is not "unknown", it is PROOF: `-d` refuses an unmerged branch and
        the `-D` fallback fires only when `is_merged_into` already proved the merge.
        Nothing in the pipeline can delete an unmerged story branch.

        A naive `is_merged_into(branch, base)` here would blow up on a branch that
        no longer resolves and block EVERY closed story.
        """
        self._seed_sprint()  # branch_name names a branch that was never created

        self.assertIsNone(self._run(_done_cmd()))

    def test_merged_branch_that_still_exists_passes(self):
        """The teammate shape: the branch is merged but a worktree still holds it,
        so the delete was skipped. Absence cannot prove it -- the ancestor check
        does. This is the leg the normal close path short-circuits past."""
        self._unmerged_story_branch()
        self._git("merge", "--no-ff", _STORY_BRANCH, "-m", "Merge")
        self._seed_sprint()

        self.assertIsNone(self._run(_done_cmd()))

    def test_story_without_a_branch_passes(self):
        """Stage 0/1: no branching at all, so there is no merge to prove."""
        self._seed_sprint(branch=None)

        self.assertIsNone(self._run(_done_cmd()))

    def test_already_done_passes(self):
        """Idempotent re-mark. Re-running /xp-accept must not deadlock on a story
        it already closed."""
        self._unmerged_story_branch()
        self._seed_sprint(status="done")

        self.assertIsNone(self._run(_done_cmd()))

    def test_marking_deferred_is_not_gated(self):
        """The gate fires on `done`, never on `deferred`. A deferred story keeps
        its branch for next sprint precisely BECAUSE it did not merge."""
        self._unmerged_story_branch()
        self._seed_sprint()
        cmd = _done_cmd().replace("done", "deferred")

        self.assertIsNone(self._run(cmd))

    def test_no_sprint_passes(self):
        """No sprint at all -- nothing to verify. Fail OPEN on "nothing to check"
        is a different contract from fail CLOSED on "cannot read", and both are
        deliberate."""
        self._unmerged_story_branch()

        self.assertIsNone(self._run(_done_cmd()))

    def test_force_unmerged_overrides(self):
        """The escape hatch. A gate with no recovery path is worse than the bug --
        but the override is on the record (the CLI writes a debt event), not silent.
        """
        self._unmerged_story_branch()
        self._seed_sprint()
        cmd = _done_cmd(extra=' --force-unmerged "merged by hand upstream"')

        self.assertIsNone(self._run(cmd))


class TestTheGateReadsEveryMarkDoneInTheCommand(_GateCase):
    """One regex `search` per command was three holes wearing one bug.

    The gate read the FIRST match, took the id EXACTLY as the shell wrote it, and
    knew only one of the two subcommands that write `done`. Each hole is silent: a
    story slips past a gate that reports nothing, which is the same failure the
    gate exists to stop, one layer up.
    """

    def test_the_SECOND_mark_done_in_one_command_is_gated_too(self):
        """`... update-story story-001 done && ... update-story story-002 done` —
        `search` stops at the first match, so story-002 was marked done with no
        merge proof at all. Chaining the two is the natural shape when a close
        wraps up several stories."""
        self._unmerged_story_branch()
        self._seed_stories(
            self._story("story-001", branch=None),  # nothing to prove — passes
            self._story("story-002", branch=_STORY_BRANCH),  # unmerged — must block
        )

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(f"{_done_cmd('story-001')} && {_done_cmd('story-002')}")

        self.assertIn("story-002", str(caught.exception))

    def test_a_QUOTED_story_id_is_still_gated(self):
        """`\\S+` swallowed the shell's own quotes, so the gate looked up the story
        `'story-001'` — which does not exist — and `merged_block` read the resulting
        ValueError as "no such story", i.e. nothing to check, i.e. ALLOW. The shell
        strips the quotes before the CLI sees them, so the forged `done` lands.

        Quoting an id is not exotic: /xp-schedule quotes `"$FIRST"` two steps
        earlier in the very same pipeline.
        """
        self._unmerged_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd('"story-001"'))

        with self.assertRaises(_common.BlockedError):
            self._run(_done_cmd("'story-001'"))

    def test_update_story_if_new_done_is_gated(self):
        """The OTHER writer of `done`. `update-story-if <id> --expected X --new done`
        is a compare-and-swap onto the same field, and the gate's pattern did not
        know the subcommand existed — so the whole merge proof was one flag away."""
        self._unmerged_story_branch()
        self._seed_sprint()
        cmd = (
            "python3 /path/to/sprint_cli.py --smm-dir /tmp/smm "
            "update-story-if story-001 --expected closing --new done"
        )

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(cmd)

        self.assertIn("story-001", str(caught.exception))

    def test_an_override_waives_only_the_invocation_that_TYPED_it(self):
        """`--force-unmerged` was matched against the WHOLE command, so one override
        waived every mark-done chained after it — including stories whose bypass no
        debt event ever paid for. The flag belongs to its own invocation."""
        self._unmerged_story_branch()
        self._seed_stories(
            self._story("story-001", branch=_STORY_BRANCH),
            self._story("story-002", branch=_STORY_BRANCH),
        )
        overridden = _done_cmd("story-001", extra=' --force-unmerged "on the record"')
        cmd = overridden + " && " + _done_cmd("story-002")

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(cmd)

        self.assertIn("story-002", str(caught.exception), "the UNoverridden one")

    def test_update_story_if_to_a_non_done_status_is_not_gated(self):
        """The control — /xp-accept's real CAS is `--new closing`, and it must pass."""
        self._unmerged_story_branch()
        self._seed_sprint()
        cmd = (
            "python3 /path/to/sprint_cli.py --smm-dir /tmp/smm "
            "update-story-if story-001 --expected reviewing --new closing"
        )

        self.assertIsNone(self._run(cmd))


class TestBackstopAtEngineAltitude(_GateCase):
    """The gate, dropped BELOW the shell into the engine handlers.

    The Bash-regex gate reads the literal command text, so an id hidden in a shell
    variable (`update-story "$SID" done`) slips past every regex — the hook never
    sees the resolved value. The engine handler does: by the time `_cmd_update_story`
    runs, the shell has expanded `$SID` to the real id. Pinning the same git-derived
    proof there closes the evasion at the altitude where every writer of `status`
    converges. Same proof, one layer down; driven end-to-end through the CLI.
    """

    def _cli(self, *args: str):
        return run_cli(_CLI, [*args, "--cwd", self.repo], self.smm_dir)

    def _status(self) -> str:
        loaded = sprint_store.load_sprint_required(self.smm_dir)
        return loaded["stories"][0]["status"]

    def test_unmerged_branch_is_refused_by_the_engine_handler(self):
        """AC: the handler refuses and the status stays unchanged — the same
        refusal the Bash hook makes, now reachable when the hook is bypassed."""
        self._unmerged_story_branch()
        self._seed_sprint()

        result = self._cli("update-story", "story-001", "done")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(_STORY_BRANCH, result.stderr)
        self.assertIn(_BASE, result.stderr)
        self.assertEqual(self._status(), "closing", "status must not have moved")

    def test_shell_variable_evasion_is_closed_here(self):
        """The headline. The Bash hook cannot gate `update-story "$SID" done`: it
        sees the literal `$SID`, which is no story, so it waves the mark-done
        through. The engine handler, handed the RESOLVED id the shell produced,
        refuses. This test pairs both altitudes on one repo+sprint.
        """
        self._unmerged_story_branch()
        self._seed_sprint()

        # Shell altitude: the variable form evades the regex gate — not blocked.
        evasion = (
            'python3 /path/to/sprint_cli.py --smm-dir /tmp/smm update-story "$SID" done'
        )
        self.assertIsNone(self._run(evasion), "the shell-var form evades the hook")

        # Engine altitude: the shell resolved $SID, so the real id lands here.
        result = self._cli("update-story", "story-001", "done")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(_STORY_BRANCH, result.stderr)

    def test_update_story_if_new_done_is_refused_rc2(self):
        """The compare-and-swap writer of `done`, gated too. Its block code is
        rc=2 (bad input), distinct from the rc=1 that means it lost the CAS race."""
        self._unmerged_story_branch()
        self._seed_sprint()

        result = self._cli(
            "update-story-if", "story-001", "--expected", "closing", "--new", "done"
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(_STORY_BRANCH, result.stderr)
        self.assertEqual(self._status(), "closing")

    def test_absent_branch_marks_done_through_the_engine(self):
        """AC: a merged-and-cleaned-up story (branch gone) marks done — absence is
        proof of merge, so the backstop allows it end-to-end."""
        self._seed_sprint()  # branch_name names a branch that was never created

        result = self._cli("update-story", "story-001", "done")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "done")

    def test_non_done_transition_is_not_gated(self):
        """The backstop fires ONLY on `done`. An honest `in-progress` move on a
        story whose branch is unmerged must pass — merged_block inspects current
        merge state, so gating it unconditionally would block ordinary work."""
        self._unmerged_story_branch()
        self._seed_sprint()

        result = self._cli("update-story", "story-001", "in-progress")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "in-progress")

    def test_update_story_if_to_a_non_done_status_is_not_gated(self):
        """The CAS control: `--new closing` is not `done`, so the backstop stays
        out of the way and the swap succeeds."""
        self._seed_sprint(branch=None)  # reviewing→closing, no merge to prove

        result = self._cli(
            "update-story-if",
            "story-001",
            "--expected",
            "closing",
            "--new",
            "reviewing",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "reviewing")


if __name__ == "__main__":
    unittest.main()

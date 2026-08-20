#!/usr/bin/env python3
"""What the review gate is entitled to count, and what it is not.

The gate blocked a commit reporting "3 code files changed since last review"
whose entire staged diff was ONE markdown file, and none of the three were on
disk (concern 64c18a0a3a48). A gate that blocks on a file's ghost blocks work
it has no claim on.

The concern blamed "spike files created and deleted within the session". That
cannot be the mechanism, and measuring rather than believing it is what makes
the rule right: `{watermark}..HEAD` is a NET tree diff, so a file born and
buried inside the range never appears in it at all. What the ghosts really are
— pinned in the first class below — is paths that exist in HEAD *and* in the
index, removed from the WORKING TREE with the removal left unstaged.

So the rule is:

    exclude a path git reports as an UNSTAGED working-tree deletion
    (`git diff --diff-filter=D`), that is not in the staged set, and that the
    command about to run will not itself stage.

Emphatically NOT "exclude what is not on disk". Deleting a code file is a real
change that deserves review, and from the filesystem a staged `git rm` looks
exactly like a ghost — absent. The discriminator lives in git: every deletion a
commit actually makes is gone from the INDEX too, so it survives the filter.
The staged-set subtraction covers the other direction, `git add x.py && rm
x.py`, where git reports an unstaged deletion for content the commit really is
adding.

The third clause arrived a revision late, and its absence was a live defect
rather than an omission (concern b9509b449417): a ghost is defined by being
unstaged, so a command that stages everything has no ghosts to filter. The
first rule filtered them anyway and the gate went quiet on `rm a.py b.py &&
git add -A && git commit`. Pinned in the last two classes below.

These drive a REAL repo. Stubbing the three legs would only assert back
whatever shape we guessed, which is how the concern's own explanation survived
unchallenged.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commits
import git_commits
from _commit_repo_case import _RebuildTestCase

_SPIKES = ("spike1.py", "spike2.py", "spike3.py")


class _GhostCase(_RebuildTestCase):
    """A repo whose watermark predates everything the tests do to it."""

    def setUp(self):
        super().setUp()
        self.watermark = self.head()

    def _write(self, name: str, body: str = "x = 1\n") -> None:
        (self.repo / name).write_text(body)

    def _scope(self, command: str = "git commit -m notes") -> list[str]:
        return commits.get_code_files_for_review(
            str(self.repo), self.watermark, command
        )

    def _bury_three_spikes(self) -> None:
        """The reported state: three spikes committed, then removed from the
        working tree WITHOUT staging their removal, and one markdown file
        staged for the commit that got blocked."""
        for name in _SPIKES:
            self._write(name, "print(1)\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "spikes")
        for name in _SPIKES:
            (self.repo / name).unlink()
        self._write("notes.md", "# notes\n")
        self.git("add", "notes.md")


class TestWhichLegProducesTheGhost(_GhostCase):
    """The measurement the rule is derived from, pinned against git itself.

    These assert GIT's answers rather than the gate's, so they go on
    documenting the mechanism now that the count is fixed.
    """

    def test_the_widening_leg_names_them_on_its_own(self):
        """One markdown file staged, three code paths in `{watermark}..HEAD`,
        none on disk — the reported state. No `git add` in the command, so the
        unstaged leg never even ran: leg 2 produces this alone."""
        self._bury_three_spikes()

        self.assertEqual(commits.get_staged_files(str(self.repo)), ["notes.md"])
        self.assertEqual(
            self.git("diff", "--name-only", f"{self.watermark}..HEAD").split(),
            list(_SPIKES),
        )
        for name in _SPIKES:
            self.assertFalse((self.repo / name).exists())

    def test_git_calls_them_unstaged_deletions(self):
        """The narrow signal the fix keys on. The INDEX still holds all three,
        so their absence is a working-tree edit nobody has staged or committed
        — not a deletion this commit, or any commit, is making."""
        self._bury_three_spikes()

        self.assertEqual(
            self.git("diff", "--name-only", "--diff-filter=D").split(), list(_SPIKES)
        )
        self.assertNotEqual(self.git("ls-files", "--", "spike1.py"), "")

    def test_a_genuine_deletion_is_indistinguishable_from_disk(self):
        """Why "exclude files not on disk" is the wrong rule, stated as a pin:
        a staged `git rm` is absent from the filesystem exactly like a ghost.
        Only the index tells them apart."""
        self.git("rm", "-q", "README.md")
        self.git("commit", "-q", "-m", "drop readme")
        self._write("gone.py")
        self.git("add", "gone.py")
        self.git("commit", "-q", "-m", "add")
        self.git("rm", "-q", "gone.py")

        self.assertFalse((self.repo / "gone.py").exists())
        self.assertEqual(self.git("ls-files", "--", "gone.py"), "")
        self.assertIn("gone.py", self._scope())


class TestTheCountExcludesGhostsAndNothingElse(_GhostCase):
    """The rule, and the four ways it must not over-reach."""

    def test_the_reported_commit_counts_no_code_files(self):
        """AC1. Three ghosts and one staged markdown file: the live diff holds
        no code at all, so nothing reaches the threshold."""
        self._bury_three_spikes()

        self.assertEqual(self._scope(), [])

    def test_a_narrow_add_leaves_the_ghosts_filtered(self):
        """`git add` in the command arms leg 3, which reads working-tree-vs-
        index and names the same deletions. Filtering only leg 2 would leave
        the gate blocking on the commonest commit idiom there is — staging the
        one file you edited. A narrow pathspec stages nothing else, so the
        ghosts stay ghosts."""
        self._bury_three_spikes()

        self.assertEqual(self._scope("git add notes.md && git commit -m notes"), [])

    def test_a_changed_file_that_still_exists_is_still_counted(self):
        """AC2, the non-vacuity pin: the exclusion must not weaken the gate for
        real work sitting beside the ghosts."""
        self._bury_three_spikes()
        self._write("real.py", "y = 2\n")
        self.git("add", "real.py")
        self.git("commit", "-q", "-m", "real")

        self.assertEqual(self._scope(), ["real.py"])

    def test_a_staged_deletion_is_still_counted(self):
        """Removing a code file is a real change that deserves review. This is
        the failure mode of the naive fix, so it gets its own pin."""
        self._write("doomed.py")
        self.git("add", "doomed.py")
        self.git("commit", "-q", "-m", "add")
        self.watermark = self.head()
        self.git("rm", "-q", "doomed.py")

        self.assertEqual(self._scope(), ["doomed.py"])

    def test_a_deletion_committed_since_the_review_is_still_counted(self):
        """The other genuine shape: already in history, absent from disk AND
        from the index, squarely inside the range the review has not seen."""
        self._write("doomed.py")
        self.git("add", "doomed.py")
        self.git("commit", "-q", "-m", "add")
        self.watermark = self.head()
        self.git("rm", "-q", "doomed.py")
        self.git("commit", "-q", "-m", "drop")

        self.assertEqual(self._scope(), ["doomed.py"])

    def test_a_staged_addition_removed_from_the_worktree_is_still_counted(self):
        """Why the rule subtracts the staged set instead of trusting
        `--diff-filter=D` alone. `git add x.py && rm x.py` leaves git reporting
        an unstaged deletion — but the index holds the new content, so the
        commit really does add the file, and that is real code to review."""
        self._write("added.py", "z = 3\n")
        self.git("add", "added.py")
        (self.repo / "added.py").unlink()

        self.assertEqual(self._scope(), ["added.py"])


class TestADeletionTheCommandItselfStagesIsNoGhost(_GhostCase):
    """The half the first rule got backwards (concern b9509b449417).

    A ghost is an unstaged deletion — so whether a path IS one depends on what
    the command about to run does with it. `git add -A` stages every tracked
    deletion, which is precisely what turns these three from "a working-tree
    edit nobody staged" into "three code files this commit removes". The first
    rule filtered them anyway, and the gate went quiet on a commit deleting
    three code files: an undercount to zero, the one direction
    `get_code_files_for_review`'s own docstring forbids.

    The tell is that the two halves of that function disagreed about one set.
    Leg 3 reads unstaged changes *because* "those will be staged by the command
    itself" — and the filter then dropped them for not being staged yet.
    """

    def test_stage_all_makes_the_deletions_real(self):
        """The reported failure, inverted into a pin."""
        self._bury_three_spikes()

        self.assertEqual(
            self._scope("git add -A && git commit -m notes"), list(_SPIKES)
        )

    def test_commit_dash_a_stages_them_without_any_add(self):
        """`commit -a` stages tracked deletions on its own, so the rule cannot
        key on the word `add`."""
        self._bury_three_spikes()

        self.assertEqual(self._scope("git commit -am notes"), list(_SPIKES))

    def test_the_same_commit_content_gets_the_same_verdict(self):
        """The discriminator that shows this was a defect and not a policy.

        Two commands, byte-identical resulting commits — one stages the
        deletions with `git rm` up front, the other lets `git add -A` do it.
        A gate that counts two code files for one and zero for the other is
        not measuring the commit.
        """
        for name in _SPIKES:
            self._write(name, "print(1)\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "spikes")
        self.watermark = self.head()

        self.git("rm", "-q", "spike1.py")
        staged_up_front = self._scope("git commit -m drop")

        self.git("commit", "-q", "-m", "drop")
        self.watermark = self.head()
        (self.repo / "spike2.py").unlink()
        staged_by_the_command = self._scope("git add -A && git commit -m drop")

        self.assertEqual(staged_up_front, ["spike1.py"])
        self.assertEqual(staged_by_the_command, ["spike2.py"])

    def test_every_stage_all_form_reaches_the_unstaged_leg(self):
        """One spelling of "stages everything", not two.

        The filter above and the leg that FEEDS it were asked by two different
        rules: the leg tested `commit\\s+-a` by hand and so armed for
        `commit -am` while missing `commit -q -a` and `commit --all`. For a
        deletion older than the watermark the widening leg cannot name it
        either, so nothing read it at all and the gate measured zero code
        files on a commit removing one — the same silent undercount, one
        spelling over. Subtests, because each form must answer alone.
        """
        for command in (
            "git commit -am drop",
            "git commit -q -a -m drop",
            "git commit --all -m drop",
            "git add -A && git commit -m drop",
        ):
            with self.subTest(command=command):
                self._write("old.py", "print(1)\n")
                self.git("add", "-A")
                self.git("commit", "-q", "-m", "old")
                self.watermark = self.head()
                (self.repo / "old.py").unlink()

                self.assertEqual(self._scope(command), ["old.py"])

                self.git("checkout", "--", "old.py")
                self.git("rm", "-q", "old.py")
                self.git("commit", "-q", "-m", "cleanup")


class TestAPathspecCommitMakesItsDeletionsReal(_GhostCase):
    """`git commit <pathspec>` commits the WORKING TREE, so the index rule breaks.

    The ghost discriminator is "every deletion a commit actually makes is gone
    from the INDEX too". True of `git commit`; false of `git commit a.py b.py`,
    which commits the named paths straight out of the working tree — deletion
    included, index never touched. Measured against real git below rather than
    argued from the manual.

    So the filter subtracted two paths a commit was about to remove and the gate
    counted ZERO code files for it, where the widening leg had counted both
    before the filter existed: the undercount-to-zero
    `get_code_files_for_review`'s own docstring forbids, reached by the one
    commit form whose premise does not hold.
    """

    _DOOMED = ("a.py", "b.py")
    _PATHSPEC_COMMIT = "git commit -m 'drop both' a.py b.py"

    def _two_doomed_code_files(self) -> None:
        """Two code files inside `{watermark}..HEAD`, gone from the working tree
        with the removal unstaged — the ghost shape exactly, up to the command."""
        for name in self._DOOMED:
            self._write(name, "print(1)\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "two files")
        for name in self._DOOMED:
            (self.repo / name).unlink()

    def test_git_really_commits_them_from_the_working_tree(self):
        """The premise, asked of git and not of the docs: nothing staged, both
        paths still reported as unstaged deletions, and the commit removes them
        anyway."""
        self._two_doomed_code_files()

        self.assertEqual(commits.get_staged_files(str(self.repo)), [])
        self.assertEqual(
            self.git("diff", "--name-only", "--diff-filter=D").split(),
            list(self._DOOMED),
        )
        self.git("commit", "-q", "-m", "drop both", "a.py", "b.py")

        self.assertEqual(
            self.git("show", "--name-status", "--format=", "HEAD").split(),
            ["D", "a.py", "D", "b.py"],
        )

    def test_the_gate_counts_the_files_that_commit_deletes(self):
        """The regression, inverted into a pin. Two code files leave the tree,
        so the gate has two to count and the review threshold is met."""
        self._two_doomed_code_files()

        self.assertEqual(self._scope(self._PATHSPEC_COMMIT), list(self._DOOMED))

    def test_a_quoted_message_does_not_hide_the_pathspec(self):
        """The form every agent writes. On the quote-STRIPPED command `-m` is
        left adjacent to `a.py` and swallows it as its own value, so the paths
        vanish and the filter runs anyway — which is why the pathspec scan
        replaces a quoted argument with a filler TOKEN rather than deleting it.
        """
        self.assertTrue(
            git_commits.commit_names_a_pathspec('git commit -m "drop both" a.py')
        )


if __name__ == "__main__":
    unittest.main()

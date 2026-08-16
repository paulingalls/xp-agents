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
    (`git diff --diff-filter=D`) and that is not in the staged set.

Emphatically NOT "exclude what is not on disk". Deleting a code file is a real
change that deserves review, and from the filesystem a staged `git rm` looks
exactly like a ghost — absent. The discriminator lives in git: every deletion a
commit actually makes is gone from the INDEX too, so it survives the filter.
The staged-set subtraction covers the other direction, `git add x.py && rm
x.py`, where git reports an unstaged deletion for content the commit really is
adding.

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

    def test_the_unstaged_leg_is_filtered_too(self):
        """`git add` in the command arms leg 3, which reads working-tree-vs-
        index and names the same deletions. Filtering only leg 2 would leave
        the gate blocking on exactly the commands that stage anything."""
        self._bury_three_spikes()

        self.assertEqual(self._scope("git add -A && git commit -m notes"), [])

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


if __name__ == "__main__":
    unittest.main()

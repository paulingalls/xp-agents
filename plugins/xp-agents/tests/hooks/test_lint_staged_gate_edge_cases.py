#!/usr/bin/env python3
"""staged_lint gate edge cases: unreadable blobs, index quirks, real-ruff E2E.

Split from test_lint.py to keep files under the 500-line cap. `_StagedGitRepo`
lives in `_lint_test_helpers.py` because it is also used by
test_lint_staged_gate_branches.py — a shared base, not a duplicate.
"""

import re
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import staged_lint
from _lint_test_helpers import _StagedGitRepo

# TestMaterializeIsLanguageBlind and TestMaterializeCreatesMissingParentDir stood
# here. Both tested `_materialize_staged` directly, which no longer exists — the
# gate lints the real path, so there is no copy to key on a basename and no
# gone-parent-dir to recreate. Their INTENT survives: language-blindness is pinned
# by TestBranchALintsTheRealPath.test_the_same_branch_carries_any_language, and the
# staged-new file whose parent dir is gone is pinned end-to-end by
# TestGateHandlesMissingParentDir — which needs no dir on disk at all now, because
# the bytes arrive on stdin.


class TestGateFailsClosedOnAnUnreadableStagedBlob(_StagedGitRepo):
    """An in-index file whose staged blob cannot be read is a bad read →
    unverified → BLOCK. Never a silent skip.

    `staged_blob_bytes` survives the death of materialization: it is now the
    source of the bytes branch B pipes to the linter, so this is still the read
    that can fail, and it must still fail closed.
    """

    def test_unreadable_staged_blob_blocks(self) -> None:
        target = self.repo / "app.py"
        target.write_text("import os\n")
        self._git("add", "app.py")

        with (
            patch("staged_lint.staged_blob_bytes", return_value=None),
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            self.assertRaises(_common.BlockedError),
        ):
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))


class TestStagedDeletionSkipsOnIndexMembership(_StagedGitRepo):
    """AC3: a staged deletion is skipped via INDEX membership, not `.exists()`.

    The working-tree copy is left present AND dirty, so an `.exists()`-based
    predicate would lint the dirty working tree and block; only the index check
    (the blob is gone from `:app.py`) correctly skips it.
    """

    def test_staged_deletion_with_dirty_worktree_is_skipped(self) -> None:
        target = self.repo / "app.py"
        target.write_text("x = 1\n")
        self._git("add", "app.py")
        self._git("commit", "-q", "-m", "add app")
        self._git("rm", "--cached", "app.py")  # stage the deletion, keep the file
        target.write_text("import os\n")  # dirty, F401-violating working-tree copy

        advisories = staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertEqual(
            advisories, [], "a staged deletion must be skipped, not linted or blocked"
        )


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateSeesPastTheIndexsDoNotLookBits(_StagedGitRepo):
    """`git diff` is stat-first, and two index bits switch the stat off.

    `assume-unchanged` and `skip-worktree` both tell git to stop comparing a
    file against the working tree -- so `git diff --name-only` does not NAME a
    file whose index and disk contents genuinely differ, and the gate routes it
    to the in-place branch and lints the wrong bytes. Delegating the question to
    git is right (only git applies the project's own clean/smudge and eol
    filters, which raw bytes would read as spurious divergence); trusting a
    stat-first answer for files git has been told not to stat is not.

    `git ls-files -v` reports those bits directly, for the whole staged set in
    one process, so the cheap batched design is kept and the hole is closed.
    """

    def _stage_violation_then_clean_disk_with(self, bit: str) -> None:
        target = self.repo / "app.py"
        target.write_text("import os\n")  # F401, the bytes the commit carries
        self._git("add", "app.py")
        self._git("update-index", bit, "app.py")
        target.write_text("x = 1\n")  # disk is clean; git has been told not to look

    def test_assume_unchanged_still_lints_the_staged_bytes(self) -> None:
        self._stage_violation_then_clean_disk_with("--assume-unchanged")

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertIn("F401", str(ctx.exception))

    def test_skip_worktree_still_lints_the_staged_bytes(self) -> None:
        self._stage_violation_then_clean_disk_with("--skip-worktree")

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertIn("F401", str(ctx.exception))

    def test_an_ordinary_clean_file_is_unaffected(self) -> None:
        """The guard must not sweep every file onto the slow path."""
        (self.repo / "app.py").write_text("x = 1\n")
        self._git("add", "app.py")

        self.assertEqual(staged_lint.staged_lint_gate(["app.py"], str(self.repo)), [])


class TestGateBlocksOnRealStagedBytes(_StagedGitRepo):
    """End-to-end against the REAL ruff, the whole point of the story."""

    def test_ac1_ac5_staged_violation_fixed_on_disk_still_blocks(self) -> None:
        """Stage a violation, clean the working tree — the gate blocks on the
        bytes the commit CARRIES (the partial-add fail-open)."""
        target = self.repo / "app.py"
        target.write_text("import os\n")  # F401
        self._git("add", "app.py")
        target.write_text("x = 1\n")  # working tree is clean now

        with self.assertRaises(_common.BlockedError):
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

    def test_block_message_names_the_real_file_not_the_temp(self) -> None:
        """The finding must name `app.py` and no path but `app.py` — the agent is
        told to fix it, so the path it reads must be one that exists.

        The copy this once guarded against is gone, and the guard stays: it pins
        the PROPERTY (a block names a real path), not the mechanism. Both prior
        designs satisfied their own mechanism and broke this."""
        target = self.repo / "app.py"
        target.write_text("import os\n")  # F401
        self._git("add", "app.py")

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        message = ctx.exception.args[0]
        self.assertIn("app.py:", message, "must name the real staged file")
        # No mkstemp temp sibling (app.<random>.py) leaked into the message.
        self.assertIsNone(re.search(r"app\.[A-Za-z0-9_]+\.py", message))

    def test_ac2_staged_clean_working_tree_dirty_proceeds(self) -> None:
        """Stage clean bytes, dirty the working tree — no block: the gate does
        not judge bytes the commit is not carrying."""
        target = self.repo / "app.py"
        target.write_text("x = 1\n")  # clean
        self._git("add", "app.py")
        target.write_text("import os\n")  # working-tree violation, NOT staged

        advisories = staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertEqual(
            advisories, [], "must not block on unstaged working-tree bytes"
        )

    def test_no_temp_files_left_behind(self) -> None:
        """The gate must leave the working tree exactly as it found it.

        There is no copy to clean up any more, so this no longer guards a
        cleanup path — it guards the INVARIANT that replaced it: a gate that
        writes nothing cannot strand anything. It fails the moment someone
        reaches for a temp copy again, which is the third time this would be."""
        target = self.repo / "app.py"
        target.write_text("x = 1\n")
        self._git("add", "app.py")

        staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        strays = [
            p.name
            for p in self.repo.iterdir()
            if p.name.startswith("app.") and p.name != "app.py"
        ]
        self.assertEqual(strays, [], f"temp siblings stranded in the repo: {strays}")


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGatePreservesFilenameKeyedRules(_StagedGitRepo):
    """A linter rule keyed on the EXACT basename (ruff `per-file-ignores`,
    eslint filename globs, `__init__.py`/`conftest.py` special-cases) must match
    the file the gate lints. A random temp NAME defeats those rules and turns a
    legitimate commit into a FALSE-POSITIVE block — the inverse of the documented
    fail-open, and the reason the temp SIBLING design was abandoned.

    The basename is now exact because the path is the real one, on every branch:
    linted in place, or piped and named with `--stdin-filename`.
    """

    def test_per_file_ignore_by_exact_basename_still_applies(self) -> None:
        (self.repo / "ruff.toml").write_text(
            '[lint.per-file-ignores]\n"__init__.py" = ["F401"]\n'
        )
        pkg = self.repo / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("import os\n")  # F401, ignored for __init__.py
        self._git("add", "pkg/__init__.py")

        # A random temp name (pkg/__init__.RANDOM.py) escapes the __init__.py
        # per-file-ignore, ruff flags F401, and the gate blocks a legitimate
        # commit. Preserving the exact basename keeps the ignore matching.
        advisories = staged_lint.staged_lint_gate(["pkg/__init__.py"], str(self.repo))
        self.assertEqual(
            advisories, [], "filename-keyed per-file-ignore must still apply"
        )


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateJudgesTheFileAtItsRealDepth(_StagedGitRepo):
    """AC1/AC5 end-to-end, through a real linter subprocess: a staged file is
    judged at the path it really occupies — right basename AND right depth.

    Depth is what the previous fix traded away. Materializing to `pkg/tmpXXXX/
    app.py` keeps the basename but moves the file one level DOWN, so every
    path-relative resolution the file does (`./util`, `../lib/x`) and every
    config rule keyed on a PATH resolves somewhere else. Self-obscuring, too:
    the tmp segment was stripped from the output and the directory deleted, so
    the agent saw a finding against a real path that was provably clean.

    A literal `./util` import is NOT the probe here, and that is deliberate:
    ruff does not resolve imports, so a relative-import test exits 0 whether the
    file sits at its real depth or one level below it. It would pass against the
    OLD code too — an inert test, which is this milestone's exact scar. The
    falsifiable probe is a config rule keyed on the file's PATH, which fails
    over depth for the same reason and MEASURABLY reddens: at `pkg/app.py` real
    ruff exits 0; at `pkg/tmpXXXX/app.py` it exits 1 with F401.
    """

    def setUp(self) -> None:
        super().setUp()
        # Keyed on the PATH, not just the basename: it only matches at the real
        # depth. A per-file-ignore is ordinary config, in every language's linter.
        (self.repo / "ruff.toml").write_text(
            '[lint.per-file-ignores]\n"pkg/app.py" = ["F401"]\n'
        )
        self.pkg = self.repo / "pkg"
        self.pkg.mkdir()
        (self.pkg / "util.py").write_text("X = 1\n")

    def test_ac1_a_relative_importing_pair_does_not_block(self) -> None:
        """Both files staged and identical to the tree — branch A, real paths."""
        (self.pkg / "app.py").write_text("from .util import X\n")
        self._git("add", "pkg/app.py", "pkg/util.py")

        advisories = staged_lint.staged_lint_gate(
            ["pkg/app.py", "pkg/util.py"], str(self.repo)
        )

        self.assertEqual(advisories, [], "a file at its real path must not block")

    def test_ac3_the_same_holds_when_the_staged_bytes_diverge(self) -> None:
        """Branch B: the bytes go down stdin, but the PATH they are labelled
        with is still the real one, so the path-keyed rule still matches."""
        app = self.pkg / "app.py"
        app.write_text("from .util import X\n")
        self._git("add", "pkg/app.py", "pkg/util.py")
        app.write_text("from .util import X\nY = 2\n")  # divergent

        advisories = staged_lint.staged_lint_gate(
            ["pkg/app.py", "pkg/util.py"], str(self.repo)
        )

        self.assertEqual(advisories, [])

    def test_ac5_mangling_the_staged_bytes_DOES_block(self) -> None:
        """The other half of the proof: the gate is reading these bytes, not
        waved through. Same file, same real path, a violation the path-keyed
        ignore does not cover — and the working tree left clean, so only the
        STAGED bytes can be what blocks it."""
        app = self.pkg / "app.py"
        app.write_text("from .util import X\nprint(NO_SUCH_NAME)\n")  # F821
        self._git("add", "pkg/app.py", "pkg/util.py")
        app.write_text("from .util import X\n")  # working tree is clean

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["pkg/app.py", "pkg/util.py"], str(self.repo))

        message = ctx.exception.args[0]
        self.assertIn("F821", message, "the STAGED bytes are what is judged")
        self.assertIn("pkg/app.py", message, "and it names the real file")
        self.assertNotIn("tmp", message, "no temp path may reach the agent")


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateHandlesMissingParentDir(_StagedGitRepo):
    """A staged-new file whose parent dir is gone in the working tree (index
    still carries it) must not fail the gate closed.

    Kept, and it gets easier rather than harder: git calls the file divergent, so
    its bytes arrive on stdin and nothing needs to exist on disk at all. The old
    materialize had to RECREATE the missing dir to write its copy into, then
    remove it again to leave the tree as it found it — a whole mechanism for a
    case that stops existing once nothing is written.
    """

    def test_staged_new_file_whose_parent_dir_is_gone_is_not_blocked(self) -> None:
        import shutil as sh

        newdir = self.repo / "newdir"
        newdir.mkdir()
        (newdir / "foo.py").write_text("x = 1\n")  # clean
        self._git("add", "newdir/foo.py")
        sh.rmtree(newdir)  # index keeps the blob; the working tree loses the dir
        self.assertFalse(newdir.exists())

        advisories = staged_lint.staged_lint_gate(["newdir/foo.py"], str(self.repo))
        self.assertEqual(advisories, [], "a gone parent dir must not block the commit")
        self.assertFalse(
            newdir.exists(), "the recreated parent dir must be cleaned up after"
        )


class TestStagedBlobReadIsUnambiguous(_StagedGitRepo):
    """A staged path that itself begins `N:` collides with git's `:<stage>:<path>`
    shorthand: `:0:x.py` parses as stage 0 of `x.py`, not the file literally named
    `0:x.py`. The index read must address the stage explicitly (`:0:0:x.py`) so a
    hostile path cannot resolve to a different file's blob.
    """

    def test_colon_bearing_path_reads_its_own_staged_blob_not_a_collision(
        self,
    ) -> None:
        (self.repo / "0:x.py").write_text("A")
        (self.repo / "x.py").write_text("B")
        self._git("add", "0:x.py", "x.py")

        self.assertEqual(staged_lint.staged_blob_bytes(str(self.repo), "0:x.py"), b"A")

    def test_unreadable_blob_still_returns_none(self) -> None:
        self.assertIsNone(staged_lint.staged_blob_bytes(str(self.repo), "missing.py"))

    def test_ordinary_path_still_reads_its_own_staged_bytes(self) -> None:
        (self.repo / "app.py").write_text("x = 1\n")
        self._git("add", "app.py")

        self.assertEqual(
            staged_lint.staged_blob_bytes(str(self.repo), "app.py"), b"x = 1\n"
        )


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateBlocksOnCollisionNamedStagedBlob(_StagedGitRepo):
    """E2E: a staged file whose name collides under `:<stage>:<path>` parsing,
    carrying a real lint finding, must BLOCK the commit gate rather than
    silently linting the decoy and reporting clean."""

    def test_collision_named_file_with_lint_finding_blocks(self) -> None:
        (self.repo / "0:x.py").write_text("import os\n")  # F401, the staged bytes
        (self.repo / "x.py").write_text("y = 1\n")  # clean decoy the ambiguous ref
        # resolves to under the bug
        self._git("add", "0:x.py", "x.py")
        # Diverge the worktree copy so the gate takes the stdin branch and must
        # read the STAGED blob via `staged_blob_bytes` — the path the bug hits.
        (self.repo / "0:x.py").write_text("y = 2\n")

        with self.assertRaises(_common.BlockedError):
            staged_lint.staged_lint_gate(["0:x.py", "x.py"], str(self.repo))


if __name__ == "__main__":
    unittest.main()

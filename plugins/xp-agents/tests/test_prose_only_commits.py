#!/usr/bin/env python3
"""A commit marked `[prose-only]` must change no shipped code shape.

SHIPPED CODE SHAPE, precisely: for every `.py` this commit touches under
`scripts/` or `smm/`, the docstring-free AST is identical before and after.
The marker says nothing about `tests/` — a commit may add or change a test and
still be prose-only under this rule, because the claim is about what ships.

`_ast_identity` proves a prose edit touched only prose, but it cannot be run
over every commit: most commits change code shape on purpose, so a blanket
check would redden every ordinary branch. It has to be opt-in, and the opt-in
is a `[prose-only]` marker in the commit subject or body — the same shape as
this tree's existing `[verify-deferred]` / `[sprint-direct]` / `[release]`
markers.

So the claim this pins is narrow and the marker is what makes it falsifiable:
say `[prose-only]` and the guard holds you to it.

The live leg walks this branch's commits and finds none when nobody has
claimed prose-only, which is the ordinary case — so it SKIPS rather than
passing silently, and `_marked_commits` is exercised on synthetic log output
where the interesting states are reachable.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _ast_identity import shape_violations

_MARKER = "[prose-only]"
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SHIPPED = ("plugins/xp-agents/scripts/", "plugins/xp-agents/smm/")


def _marked_commits(log: str) -> list[str]:
    """SHAs from `git log --format=%H%x00%B%x00%x00` whose message is marked.

    NUL-delimited because a commit body contains newlines and blank lines; a
    line-oriented split would treat a wrapped body as separate records and
    attribute the marker to the wrong SHA.
    """
    shas: list[str] = []
    for record in log.split("\0\0"):
        if not record.strip():
            continue
        sha, _, message = record.partition("\0")
        if _MARKER in message:
            shas.append(sha.strip())
    return shas


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(_REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _shipped_python_in(sha: str) -> list[str]:
    changed = _git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).split()
    return [p for p in changed if p.endswith(".py") and p.startswith(_SHIPPED)]


def _show(ref: str) -> str:
    """The blob at `<sha>:<path>`, or "" when the path is not in that tree.

    A commit that ADDS a shipped .py has no `<sha>^:<path>` and one that DELETES
    it has no `<sha>:<path>`; `git show` exits non-zero for both, and a raised
    CalledProcessError is a traceback in the push gate instead of a verdict. An
    empty side is what `shape_violations` already reads as a shape change, so
    either one reports as the violation it is. Any OTHER failure to read a blob
    lands there too — loud, never silent.
    """
    try:
        return _git("show", ref)
    except subprocess.CalledProcessError:
        return ""


class TestTheMarkerScanner(unittest.TestCase):
    """Synthetic log output — the live leg cannot reach these states."""

    def test_a_marked_commit_is_found(self):
        log = "abc123\0Tidy a docstring\n\n[prose-only]\n\0\0"

        self.assertEqual(_marked_commits(log), ["abc123"])

    def test_an_unmarked_commit_is_ignored(self):
        log = "abc123\0Add a feature\n\0\0"

        self.assertEqual(_marked_commits(log), [])

    def test_a_multi_paragraph_body_is_one_record(self):
        """A wrapped body must not be split into records, or the marker gets
        attributed to a neighbouring SHA."""
        log = (
            "aaa\0Subject\n\nPara one.\n\nPara two.\n\n[prose-only]\n\0\0"
            "bbb\0Other\n\0\0"
        )

        self.assertEqual(_marked_commits(log), ["aaa"])

    def test_only_the_marked_one_of_several_is_returned(self):
        log = "aaa\0No marker\n\0\0bbb\0Has it\n\n[prose-only]\n\0\0ccc\0Nor this\n\0\0"

        self.assertEqual(_marked_commits(log), ["bbb"])

    def test_empty_log_yields_nothing(self):
        self.assertEqual(_marked_commits(""), [])


class TestReadingABlobThatIsNotThere(unittest.TestCase):
    """An added file has no pre-image and a deleted one has no post-image."""

    def test_an_absent_path_reads_as_empty_not_an_exception(self):
        self.assertEqual(_show("HEAD:plugins/xp-agents/scripts/no_such_module.py"), "")

    def test_a_present_path_still_reads_its_content(self):
        self.assertIn(
            "import ast", _show("HEAD:plugins/xp-agents/tests/_ast_identity.py")
        )

    def test_an_added_file_reports_as_a_shape_change(self):
        """The verdict the crash was hiding: prose-only cannot add code."""
        violations = shape_violations([("added.py", "", "x = 1\n")])

        self.assertEqual(len(violations), 1)


class TestProseOnlyCommitsOnThisBranch(unittest.TestCase):
    """The live leg. Skips when nothing claims prose-only — a skip is visible
    in the runner output where a silent pass would not be."""

    def test_every_marked_commit_changed_no_code(self):
        base = "origin/main"
        try:
            _git("rev-parse", "--verify", base)
        except subprocess.CalledProcessError:
            self.skipTest(f"{base} not available in this checkout")

        log = _git("log", "--format=%H%x00%B%x00%x00", f"{base}..HEAD")
        marked = _marked_commits(log)
        if not marked:
            self.skipTest("no commit on this branch claims [prose-only]")

        pairs = []
        for sha in marked:
            for path in _shipped_python_in(sha):
                pairs.append(
                    (
                        f"{sha[:8]} {path}",
                        _show(f"{sha}^:{path}"),
                        _show(f"{sha}:{path}"),
                    )
                )
        if not pairs:
            self.skipTest("marked commits touched no shipped Python")

        self.assertEqual(shape_violations(pairs), [])


if __name__ == "__main__":
    unittest.main()

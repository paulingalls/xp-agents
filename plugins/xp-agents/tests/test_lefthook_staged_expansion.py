#!/usr/bin/env python3
"""How far a staged non-test source file expands the commit gate's test run.

The gate maps a staged `.py` that is not a `test_*.py` to its containing
DIRECTORY, because a broken helper fails tests that match no `test_*` name. In
a leaf package that is exactly right and cheap. At the tests ROOT the directory
IS the whole suite, so staging four root-level helpers ran every test in the
tree at commit — 414s when the concern (377a33831d31) recorded it, and 590s
(9946 tests) re-measured here on 2026-08-16 — and then `git push` ran them
again. That double run is precisely what the commit/push split exists to
remove.

**Why the existing suite did not catch it.**
`test_lefthook_commit_gate.py::test_never_a_bare_whole_tree_pytest` asserts the
command body never NAMES the tree literally, and the body does not: it derives
the target from `${f%/*}`, so the whole-tree run is computed at runtime out of a
staged path. A text pin cannot see that. Every pin here executes the body
instead, through that file's own `_execute_gate` harness, and asserts on the
argv pytest actually receives.

**The rule, and its honest rationale.** A staged non-test `.py` sitting
directly at the tests root selects the root's OWN `test_*.py` files and stops
there. That is BOUNDED COST, not coverage. It is tempting to say "a broken root
helper still gets signal", and that is false for nearly half of them: 23 of the
51 root-level helpers have no consumer among the 33 root-level test files at
all, and `_branching_fixtures.py` has 78 consumers, every one of them in a
subdirectory. **Pre-push owns real coverage for a root-level helper.** What
this bounds is the bill at commit time, and the comment in `lefthook.yml` must
claim no more than that.

(Select-by-importer was considered and rejected: `_branching_fixtures.py`'s 78
consumers span many directories, so following imports lands back near
whole-tree cost. It solves coverage by recreating the problem.)
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_lefthook_commit_gate import _execute_gate
from test_lefthook_perf_gate import REPO_ROOT, _command_body, _hook

_TESTS_ROOT = "plugins/xp-agents/tests"
_LEAF = f"{_TESTS_ROOT}/hooks"


def _root_test_files() -> list[str]:
    """The root's own `test_*.py`, from the filesystem rather than a number.

    A hard-coded count would go stale the first time anyone adds a root-level
    test file, and it would go stale GREEN if the bound were also hard-coded.
    """
    return sorted(
        f"{_TESTS_ROOT}/{p.name}" for p in (REPO_ROOT / _TESTS_ROOT).glob("test_*.py")
    )


class _ExpansionCase(unittest.TestCase):
    def setUp(self):
        self.cmd = _command_body(_hook("pre-commit"), "staged-tests")
        self.assertTrue(self.cmd, "pre-commit must define a staged-tests command")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _targets(self, staged: list[str]) -> tuple[list[str], list[str], int]:
        """(argv, the path targets in it, rc). Flags are not targets."""
        argv, rc = _execute_gate(self.cmd, staged, self.tmp)
        return argv, [a for a in argv if a.startswith(_TESTS_ROOT)], rc

    def assertTargets(self, targets: list[str], expected: list[str]) -> None:
        """Same set, and no path twice.

        Not a list comparison: the shell's glob order is its collation order,
        which is not Python's byte order (`…pin.py` and `…pin_matchers.py` sort
        one way here and the other way there). Duplicates are the property a
        set comparison would drop, so they are asserted separately rather than
        by pretending order is the point.
        """
        self.assertEqual(sorted(set(targets)), sorted(set(expected)))
        self.assertEqual(len(targets), len(set(targets)), "duplicate pytest target")


class TestALeafPackageIsUnchanged(_ExpansionCase):
    """AC3. The cap must not reach the case the mapping exists for."""

    def test_a_helper_inside_a_leaf_package_selects_that_package(self):
        argv, targets, rc = self._targets([f"{_LEAF}/_commit_helpers.py"])

        self.assertTargets(targets, [_LEAF])
        self.assertIn("-n", argv)
        self.assertEqual(rc, 0)

    def test_a_leaf_package_is_still_one_directory_not_its_files(self):
        """Non-vacuity for the pin above: a cap applied one level too high
        would turn this into a file list too, and the pin would still be green
        on the package name alone."""
        _, targets, _ = self._targets([f"{_LEAF}/_commit_helpers.py"])

        self.assertEqual(len(targets), 1)


class TestTheRootStopsExpanding(_ExpansionCase):
    """AC4. At the tests root the directory IS the suite, so it is not taken."""

    def test_a_root_helper_does_not_select_the_tree(self):
        _, targets, _ = self._targets([f"{_TESTS_ROOT}/_prose_baseline.py"])

        self.assertNotIn(_TESTS_ROOT, targets)

    def test_a_root_helper_selects_the_roots_own_tests(self):
        _, targets, _ = self._targets([f"{_TESTS_ROOT}/_prose_baseline.py"])

        self.assertTargets(targets, _root_test_files())

    def test_the_selection_is_bounded_to_the_root(self):
        """The property that makes the cost bounded, stated directly: no target
        lies below the root. A recursive expansion satisfies the equality above
        only by accident of ordering; this cannot be satisfied by one."""
        _, targets, _ = self._targets([f"{_TESTS_ROOT}/conftest.py"])

        self.assertTrue(targets)
        self.assertNotIn(_TESTS_ROOT, targets)
        for target in targets:
            self.assertNotIn("/", target[len(_TESTS_ROOT) + 1 :])

    def test_the_root_expansion_runs_in_parallel(self):
        """`-n auto` is otherwise reserved for directory targets, where one
        staged file is cheaper sequentially. Measured on this machine
        (endpoint AV taxing every file access): the root's 33 test files take
        174s sequentially and 92s under xdist, so this selection is on the
        wrong side of that rule and has to say so."""
        argv, _, _ = self._targets([f"{_TESTS_ROOT}/_prose_baseline.py"])

        self.assertIn("-n", argv)
        self.assertIn("auto", argv)

    def test_two_root_helpers_select_the_same_set_once(self):
        """Duplicate targets make pytest collect a file twice — the defect the
        existing file-vs-directory dedup pass already guards against, which the
        new branch has to join rather than bypass."""
        _, targets, rc = self._targets(
            [f"{_TESTS_ROOT}/_prose_baseline.py", f"{_TESTS_ROOT}/_pin_ceilings.py"]
        )

        self.assertTargets(targets, _root_test_files())
        self.assertEqual(rc, 0)

    def test_a_root_test_file_staged_beside_a_root_helper_appears_once(self):
        pinned = f"{_TESTS_ROOT}/test_dev_setup.py"
        _, targets, _ = self._targets([pinned, f"{_TESTS_ROOT}/_prose_baseline.py"])

        self.assertEqual(targets.count(pinned), 1)
        self.assertTargets(targets, _root_test_files())

    def test_a_root_helper_beside_a_leaf_helper_keeps_both(self):
        """The two branches compose: capping the root must not swallow a leaf
        package staged in the same commit."""
        _, targets, _ = self._targets(
            [f"{_TESTS_ROOT}/_prose_baseline.py", f"{_LEAF}/_commit_helpers.py"]
        )

        self.assertIn(_LEAF, targets)
        self.assertNotIn(_TESTS_ROOT, targets)


class TestClassificationIsUnchanged(_ExpansionCase):
    """The rest of the body's decisions, pinned so the cap cannot disturb them."""

    def test_a_root_test_file_is_still_a_bare_file_target(self):
        argv, targets, _ = self._targets([f"{_TESTS_ROOT}/test_dev_setup.py"])

        self.assertTargets(targets, [f"{_TESTS_ROOT}/test_dev_setup.py"])
        self.assertNotIn("-n", argv)

    def test_a_nested_test_file_is_still_a_bare_file_target(self):
        _, targets, _ = self._targets([f"{_LEAF}/test_bash.py"])

        self.assertTargets(targets, [f"{_LEAF}/test_bash.py"])

    def test_a_path_outside_the_tests_tree_is_still_ignored(self):
        argv, _, rc = self._targets(["plugins/xp-agents/scripts/test_parsing.py"])

        self.assertEqual(argv, [])
        self.assertEqual(rc, 0)


class TestEveryTimingFigureIsQualified(unittest.TestCase):
    """AC5 — no bare number survives in the gate configuration.

    A bare "432s" led a reader to blame a 6m40s commit entirely on core
    contention rather than on a genuinely slow baseline (debt f428fe8cffb7).
    The number was true of some tree on some machine, and the comment said
    which of neither. This machine runs endpoint AV that taxes every file
    access, which is exactly why an unqualified figure misleads.

    The convention this enforces: a timing figure is immediately followed by a
    parenthetical giving the test count it covers and the machine it was
    measured on. A figure that measures no tests says `0 tests` and what it
    measured instead — the point is that the reader is never left guessing what
    the number is OF.
    """

    _LEFTHOOK = REPO_ROOT / "lefthook.yml"
    _FIGURE = re.compile(r"(?<![\w.])~?\d+(?:\.\d+)?s(?!\w)")
    _QUALIFIER = re.compile(r"\s*\(\d[\d,]* tests[^)]*this machine", re.DOTALL)

    # A YAML comment's line continuation is not part of its prose: without this
    # a qualifier that wraps reads as "this # machine" and the pin rejects the
    # very form it is asking for, which would push the rationale onto one
    # unreadable line.
    _CONTINUATION = re.compile(r"\n\s*#\s*")

    def _unqualified(self) -> list[str]:
        text = self._CONTINUATION.sub(" ", self._LEFTHOOK.read_text())
        return [
            text[m.start() : m.end() + 70].replace("\n", " ")
            for m in self._FIGURE.finditer(text)
            if not self._QUALIFIER.match(text, m.end())
        ]

    def test_no_timing_figure_stands_bare(self):
        self.assertEqual(
            self._unqualified(),
            [],
            "each timing figure must be followed by `(<N> tests, … this "
            "machine …)`, or be deleted",
        )

    def test_the_file_still_states_what_the_gates_cost(self):
        """Non-vacuity: deleting every number passes the pin above too, and
        would leave the gate's cost undocumented rather than honest."""
        self.assertTrue(self._FIGURE.search(self._LEFTHOOK.read_text()))

    def test_a_bare_figure_would_still_be_caught(self):
        """Non-vacuity for the CONTINUATION rewrite: joining comment lines must
        not turn an unqualified figure into a qualified one by dragging in the
        next comment's words."""
        self.assertIsNone(self._QUALIFIER.match(" 432s costs too much", 5))


if __name__ == "__main__":
    unittest.main()

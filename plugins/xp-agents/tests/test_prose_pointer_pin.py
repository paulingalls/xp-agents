#!/usr/bin/env python3
"""Every test file named in shipped prose must exist.

Milestone 3 converts a checkable claim into a test and leaves a one-line
pointer where the claim was. That trade is only honest while the pointer
resolves: rename or split the test and the shipped claim goes silently false —
the exact rot the milestone exists to stop, now with the milestone's own output
as the thing that rots.

It is not hypothetical. Two pointers were already dead when this pin was
written, both killed by file SPLITS rather than renames, which is the case a
rename-aware habit misses.

LIMITS — READ THIS BEFORE TRUSTING THE GREEN CHECK.

* It proves a named test file EXISTS. It never proves that file still asserts
  the claim pointing at it, nor that the claim is true.
* It reads file-shaped tokens only. A pointer written as a bare function or
  class name (`pinned by TestTheBootstrapPatchSeam`) is invisible here — see
  `_test_pointer_detect.is_test_shaped` for why the bare form is not safely
  matchable.
* Shell coverage is whole-line comments only. Python, shell and Markdown are
  the three surfaces read; `.json` and the manifest are not.
"""

import functools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_helpers import (
    rel,
    shipped_files_by_root,
    shipped_prose_to_scan,
    shipped_shell_to_scan,
)
from _test_pointer_detect import (
    find_test_pointers,
    index_python_files,
    is_glob,
    is_test_shaped,
    markdown_prose,
    python_prose,
    resolves,
    shell_prose,
)

_PLUGIN_ROOT = Path(__file__).parent.parent
_REPO_ROOT = _PLUGIN_ROOT.parent.parent

# Tokens that are unresolvable BY DESIGN — each illustrates a mechanism rather
# than naming a test. An entry here is an admission the rule is wrong unless it
# carries a reason, so every one states what it illustrates and where.
_PLACEHOLDERS: dict[str, str] = {
    "test_foo.py": "story_metrics: illustrates test-to-source name mapping",
    "tests/hooks/test_x.py": (
        "verify_paths, xp-plan-reviewer.md: illustrates path-prefix matching"
    ),
    "tests/a.py": "glob_translator, surface_selection: ** spanning segments",
    "tests/sub/a.py": "glob_translator: the nested half of the same example",
}


@functools.cache
def _known() -> frozenset[str]:
    """Every `.py` path in the repo, indexed once.

    Cached here rather than in `_test_pointer_detect` for the same reason
    `_pointers` is: the detection module holds matchers and finders, no state.
    Three callers, one immutable tree, and the index rglobs the whole repo.
    """
    return frozenset(index_python_files(_REPO_ROOT))


@functools.cache
def _pointers() -> tuple[tuple[str, int, str], ...]:
    """Every `(surface, line, token)` pointer in the shipped tree.

    Cached: five callers, one immutable tree, and the scan re-reads and
    re-parses every shipped file each time.
    """
    hits: list[tuple[str, int, str]] = []
    for paths in shipped_files_by_root(_PLUGIN_ROOT).values():
        for path in paths:
            surface = rel(path, _REPO_ROOT)
            hits += find_test_pointers(python_prose(path.read_text()), surface)
    for path in shipped_shell_to_scan(_PLUGIN_ROOT):
        surface = rel(path, _REPO_ROOT)
        hits += find_test_pointers(shell_prose(path.read_text()), surface)
    for paths in shipped_prose_to_scan(_PLUGIN_ROOT).values():
        for path in paths:
            surface = rel(path, _REPO_ROOT)
            hits += find_test_pointers(markdown_prose(path.read_text()), surface)
    return tuple(hits)


class TestEveryShippedPointerResolves(unittest.TestCase):
    def test_no_pointer_names_a_missing_test_file(self):
        known = _known()
        dead = [
            f"{surface}:{lineno} points at {token}, which does not exist"
            for surface, lineno, token in _pointers()
            if token not in _PLACEHOLDERS and not resolves(token, known)
        ]

        self.assertEqual(
            sorted(dead),
            [],
            "a shipped comment names a test file that is gone — restore the "
            "name, or repoint the comment at the module that inherited it",
        )

    def test_every_placeholder_is_still_unresolvable(self):
        """A placeholder that starts resolving is no longer a placeholder, and
        its entry would then exempt a real pointer from the check above."""
        known = _known()
        resolving = sorted(t for t in _PLACEHOLDERS if resolves(t, known))

        self.assertEqual(resolving, [])

    def test_every_placeholder_is_actually_present_in_the_tree(self):
        """A stale entry silently widens the exemption for a token nobody
        writes any more."""
        found = {token for _, _, token in _pointers()}

        self.assertEqual(sorted(set(_PLACEHOLDERS) - found), [])

    def test_every_placeholder_states_a_reason(self):
        for token, reason in _PLACEHOLDERS.items():
            self.assertTrue(reason.strip(), f"{token} has no stated reason")


class TestTheScanIsNotVacuous(unittest.TestCase):
    def test_the_scan_finds_a_substantial_number_of_pointers(self):
        self.assertGreaterEqual(
            len(_pointers()),
            20,
            "expected the shipped tree's test pointers — a scan matching "
            "nothing would make the check above certify nothing",
        )

    def test_every_surface_contributes(self):
        """A total floor cannot see one surface empty out, and the shell and
        Markdown legs are the ones with least to lose before they stop covering
        anything — Markdown carries a single live pointer today."""
        surfaces = {surface for surface, _, _ in _pointers()}

        for suffix in (".py", ".sh", ".md"):
            self.assertTrue(
                any(s.endswith(suffix) for s in surfaces), f"no {suffix} pointers"
            )


class TestTheMatchersThemselves(unittest.TestCase):
    """Per-leg proofs, driven directly rather than through the corpus."""

    def test_punctuation_around_a_token_is_stripped(self):
        """Real pointers carry trailing punctuation, a possessive, or a
        `::Class` / `:_SYMBOL` tail. Each must yield the bare path."""
        cases = {
            "Pinned in test_x.py.": "test_x.py",
            "see test_x.py's fixture": "test_x.py",
            "`test_x.py`": "test_x.py",
            "tests/hooks/test_x.py::TestThing": "tests/hooks/test_x.py",
            "tests/hooks/test_x.py:_SYMBOL": "tests/hooks/test_x.py",
        }
        for text, expected in cases.items():
            tokens = [t for _, _, t in find_test_pointers([(1, text)], "s")]

            self.assertEqual(tokens, [expected], text)

    def test_a_compiled_or_stub_suffix_is_not_a_python_file(self):
        self.assertEqual(find_test_pointers([(1, "test_x.pyc test_y.pyi")], "s"), [])

    def test_a_non_test_module_name_is_not_a_pointer(self):
        text = "see cli.py and src/app.py"

        self.assertEqual(find_test_pointers([(1, text)], "s"), [])

    def test_a_bare_identifier_is_not_a_pointer(self):
        """The false-positive corpus: shipped field names and domain types."""
        text = "test_passed, test_count, TestLayout and TestLayoutRule"

        self.assertEqual(find_test_pointers([(1, text)], "s"), [])

    def test_a_glob_is_excluded_structurally(self):
        self.assertTrue(is_glob("tests/**/*.py"))
        self.assertTrue(is_glob("test_*.py"))
        self.assertEqual(find_test_pointers([(1, "tests/**/*.py")], "s"), [])

    def test_a_shipped_script_named_test_still_counts_as_test_shaped(self):
        """scripts/test_parsing.py is shipped code, and prose names it — the
        resolver searches the whole repo so it is not reported dead."""
        self.assertTrue(is_test_shaped("test_parsing.py"))
        self.assertTrue(resolves("test_parsing.py", _known()))

    def test_a_comment_inside_a_string_literal_is_not_read_as_prose(self):
        source = 'X = "# see test_ghost.py"\n# see test_real.py\n'

        tokens = [t for _, _, t in find_test_pointers(python_prose(source), "s")]
        self.assertEqual(tokens, ["test_real.py"])

    def test_shell_reads_whole_line_comments(self):
        tokens = [
            t
            for _, _, t in find_test_pointers(
                shell_prose("echo hi\n# see test_real.py\n"), "s"
            )
        ]

        self.assertEqual(tokens, ["test_real.py"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Every shipped line that routes content by checkability states the WHOLE rule.

Naming a test as a destination is one leg of a three-leg rule, so a line could
satisfy that alone while still telling a reader that history belongs in a
comment. This module owns the whole-rule verdict; the sibling
`test_prose_routing_pin.py` owns the two guards it cannot make (each known
surface still states the rule, and no shipped prose names one language's
comment construct).

    A checkable claim goes to a test. History goes to git. A comment carries
    only the why/constraint the code cannot express.

Milestone 1 shipped five such lines and only one stated all three legs. Each
surface was pinned individually, so nothing compared them and the tree read as
four different rules. This module closes that: the rule is pinned by its BODY,
not by any heading or file.

GRANULARITY IS PER LINE, and that is a deliberate choice with a cost. A routing
clause split across two source lines escapes the selector entirely (the same
limit `test_prose_routing_pin.py` records for its vacuity leg). Per-FILE
granularity was the alternative and is worse: any file mentioning git anywhere
would pass vacuously, which is the fail-silent shape this milestone exists to
kill.

THREE LEGS, one selector.

* **Selector.** A line "states the rule" when it carries the comment-routing
  phrase — `_routing_detect.COMMENT_DEST_RE`. Both pins read that one
  definition, so they cannot drift into disagreeing about what a routing line
  is.
* **Assertion, corpus-wide.** Every selected line must name all three
  destinations. Corpus-wide, so a new routing line added anywhere later is held
  to the whole rule and not just to its test leg.
* **No vacuity guard here.** A corpus-wide assertion goes green when the last
  routing line is deleted or a file is renamed away, and reports nothing — but
  the sibling's guard already covers that over the same corpus and the same
  selector, and covers it more strictly (it also fails when a surface resolves
  to no file or to more than one). A second copy here would be the weaker half
  of a check that already exists, which is the duplication this sprint spent a
  story removing.

LIMITS — READ BEFORE TRUSTING THE GREEN CHECK.

* This proves three destinations are NAMED on the line. It never proves the
  advice is right, that the named test exists, or that any comment in the tree
  actually carries a why.
* The two reviewer agents carry the rule as a multi-line lens block, so
  `COMMENT_DEST_RE` does not select them and this module says nothing about
  them. `tests/agents/test_close_reviewer_prose_lens.py` and
  `tests/agents/test_xp_code_reviewer.py` own those surfaces.
* `GIT_DEST_RE` accepts any standalone "git" on the line. A line mentioning git
  incidentally reads as compliant — an under-flag, matching the tradeoff
  `TEST_DEST_RE` already makes for its own leg.
* The selector OVER-flags. It is a phrase match on "code comment(s)" and cannot
  tell a destination from a mention, so a line that merely discusses code
  comments is held to all three legs and can only be cleared by appending
  destinations to a sentence that routes nothing. Both directions are pinned as
  cases in `test_prose_routing_pin_matchers.py`; narrowing it is open debt,
  because every narrowing tried so far under-flags one of the comma- or
  "else"-joined forms the tree actually ships.

Each leg carries a synthetic mutation proof below: a line missing that leg must
be reported. Without them a matcher that never fires would pass on the whole
tree and look like coverage. The matchers themselves live in `_routing_detect`;
this module owns the assertions over the real tree plus those per-leg proofs,
which stay here rather than in the sibling pin's matcher suite because the legs
are this module's rule, not that one's.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_helpers import rel as _rel_impl
from _pin_helpers import shipped_prose_to_scan
from _routing_detect import (
    find_comment_routing_lines,
    find_incomplete_rule_lines,
)

PLUGIN_ROOT = Path(__file__).parent.parent
REPO_ROOT = PLUGIN_ROOT.parent.parent


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _all_shipped_prose() -> list[Path]:
    return [p for paths in shipped_prose_to_scan(PLUGIN_ROOT).values() for p in paths]


class TestRuleIsStatedWhole(unittest.TestCase):
    def test_no_shipped_routing_line_states_a_partial_rule(self):
        offenders: list[str] = []
        for path in _all_shipped_prose():
            text = path.read_text(encoding="utf-8")
            for surface, lineno, missing in find_incomplete_rule_lines(
                text, _rel(path)
            ):
                offenders.append(f"{surface}:{lineno} omits: {missing}")
        self.assertEqual(
            offenders,
            [],
            "shipped routing lines state only part of the rule "
            "(claim->test, history->git, comment->why the code cannot "
            "express):\n" + "\n".join(offenders),
        )


class TestTheLegMatchersCanFail(unittest.TestCase):
    """Synthetic mutation proofs — one per leg. A matcher that never fires
    would pass the whole tree and read as coverage."""

    _WHOLE = (
        "Checkable claims go to a test; history to git; a code comment carries "
        "only the why the code cannot express."
    )

    def test_the_whole_rule_is_accepted(self):
        self.assertEqual(find_incomplete_rule_lines(self._WHOLE, "synthetic"), [])

    def test_a_line_missing_the_test_leg_is_reported(self):
        mutant = "History to git; a code comment carries the why it cannot express."
        self.assertEqual(
            find_incomplete_rule_lines(mutant, "synthetic"),
            [("synthetic", 1, "test")],
        )

    def test_a_line_missing_the_git_leg_is_reported(self):
        mutant = (
            "Checkable claims go to a test; a code comment carries only the why "
            "the code cannot express."
        )
        self.assertEqual(
            find_incomplete_rule_lines(mutant, "synthetic"),
            [("synthetic", 1, "git")],
        )

    def test_a_line_missing_the_why_leg_is_reported(self):
        mutant = "Checkable claims go to a test; history to git; else a code comment."
        self.assertEqual(
            find_incomplete_rule_lines(mutant, "synthetic"),
            [("synthetic", 1, "why")],
        )

    def test_a_line_that_routes_nowhere_is_not_selected(self):
        """The selector gates the assertion: prose naming a comment as a review
        subject is not a destination, and must not be flagged."""
        self.assertEqual(
            find_incomplete_rule_lines("Flag self-evident comments.", "synthetic"),
            [],
        )

    def test_the_selector_picks_up_only_routing_lines(self):
        self.assertEqual(find_comment_routing_lines("no routing here", "synthetic"), [])
        self.assertEqual(
            find_comment_routing_lines("route it to a code comment", "synthetic"),
            [("synthetic", 1)],
        )


if __name__ == "__main__":
    unittest.main()

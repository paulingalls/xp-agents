#!/usr/bin/env python3
"""Mutation proof for the matchers in `test_prose_routing_pin`.

Split from that module (which owns the tree-wide assertions) mirroring
`test_shipped_prose_language_agnostic_matchers.py`'s seam: this file exercises
the matchers on SYNTHETIC text, the sibling asserts the real tree complies. A
matcher that only ever runs against a tree already fixed by this same story
cannot prove it would have caught the ORIGINAL offenders, or that it stays
quiet on lines that merely mention "comment" without routing anything there.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_prose_routing_pin import (
    find_comment_routing_lines,
    find_single_language_tokens,
    find_unqualified_comment_routing,
)

# The five ORIGINAL unqualified strings this story amends, verbatim (see
# execution_plan.json / the story body's Step 2). Feeding these proves the
# matcher would have caught every one of them before the fix landed.
_ORIGINAL_OFFENDERS = {
    "PROCESS_GUIDE.md constraints bullet": (
        "- **Constraints** — architectural/process bounds. Implementation "
        "details belong in code comments. Cap 15-20."
    ),
    "xp-housekeeper.md bad-example bullet": (
        "- Bad: tooling-specific troubleshooting (belongs as code comments)"
    ),
    "xp-system-analyzer.md durability clause": (
        "transient content (changelogs, status, implementation details that "
        "turn over with each refactor) belongs in git history or code "
        "comments instead."
    ),
    "xp-system-analyzer.md discriminator-test clause": (
        "Before filling each capped list, apply its discriminator test. The "
        "test is the *keep* rule — anything that doesn't pass goes to a "
        "code comment, a convention, an SMM Constraint event, or `docs/` "
        "instead."
    ),
    "xp-system-analyzer.md not-in-system_context clause": (
        "Not in system_context at all: implementation details (dimensions, "
        "indexes, ID format), current phase or status, bug-fix / refactor / "
        "race-condition narratives — those live in code comments, git "
        "history, or sprint.json."
    ),
}


class TestCommentRoutingMatcherDetectsOriginalOffenders(unittest.TestCase):
    """Each of the five ORIGINAL unqualified lines is reported, by name."""

    def test_every_original_offender_is_flagged(self) -> None:
        for label, line in _ORIGINAL_OFFENDERS.items():
            with self.subTest(site=label):
                hits = find_unqualified_comment_routing(line, surface=label)
                self.assertEqual(
                    len(hits),
                    1,
                    f"{label!r} was not flagged as unqualified comment "
                    f"routing: {line!r}",
                )
                self.assertEqual(hits[0][0], label)


class TestCommentRoutingMatcherStaysQuietOnNonOffenders(unittest.TestCase):
    def test_review_target_language_is_not_flagged(self) -> None:
        """`xp-code-reviewer.md`'s 'what-not-why comments' is a review
        target, not a routing instruction — the shape this pin must not
        confuse with a destination clause."""
        line = (
            "- **Quality** — redundant state, parameter sprawl, copy-paste "
            "variations, leaky abstractions, stringly-typed code, "
            "what-not-why comments, mixed responsibilities."
        )
        self.assertEqual(find_unqualified_comment_routing(line, surface="x"), [])

    def test_story_002_bucket_phrasing_is_not_flagged(self) -> None:
        """A reviewer bucket that names a comment as something to KEEP (not
        route new content to) must not be confused with a routing clause."""
        line = (
            "a comment carrying a rejected design decision and the reason "
            "it was rejected is NOT flagged"
        )
        self.assertEqual(find_unqualified_comment_routing(line, surface="x"), [])

    def test_each_fixed_wording_is_no_longer_flagged(self) -> None:
        fixed_lines = [
            "- **Constraints** — architectural/process bounds. Checkable "
            "claims→tests; history→git; comments→why the code can't "
            "express. Cap 15-20.",
            "- Bad: tooling-specific troubleshooting (checkable → a test, "
            "else a code comment)",
            "belongs in a test when checkable, git history when historical, "
            "a code comment when neither.",
            "goes to a test when checkable, else a code comment, a "
            "convention, an SMM Constraint event, or `docs/` instead.",
            "those live in a test when checkable, otherwise a code comment, "
            "git history, or sprint.json.",
        ]
        for line in fixed_lines:
            with self.subTest(line=line):
                self.assertEqual(
                    find_unqualified_comment_routing(line, surface="x"), []
                )


class TestKnownMatcherBlindSpots(unittest.TestCase):
    """The under-match LIMITS bullet, made checkable instead of merely
    claimed — a limit stated only in prose is the same unverified claim this
    milestone exists to route into a test.

    These assert the CURRENT, documented misses. Broadening a matcher to
    catch one is an improvement, not a regression: delete the case and its
    LIMITS bullet together, so the two can never disagree.
    """

    def test_a_comment_destination_in_other_words_is_missed(self) -> None:
        for line in (
            "leftover detail belongs in an inline comment",
            "anything else lives as a comment in the source",
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    find_unqualified_comment_routing(line, surface="x"),
                    [],
                    "matcher grew to catch this phrasing — update the LIMITS "
                    "under-match bullet in test_prose_routing_pin",
                )

    def test_an_incidental_mention_of_a_test_reads_as_compliant(self) -> None:
        line = "implementation detail belongs in code comments, not in a test"
        self.assertEqual(
            find_unqualified_comment_routing(line, surface="x"),
            [],
            "matcher grew to discriminate an incidental 'a test' — update the "
            "LIMITS under-match bullet in test_prose_routing_pin",
        )


class TestCommentRoutingShapeMatcherBacksVacuityGuard(unittest.TestCase):
    """Leg 2's vacuity guard reads `find_comment_routing_lines`, which must
    stay non-empty on a compliant (fixed) line and empty out only when the
    routing content is genuinely gone — this is the rename/deletion case."""

    def test_a_compliant_fixed_line_still_counts_as_routing(self) -> None:
        line = (
            "belongs in a test when checkable, git history when historical, "
            "a code comment when neither."
        )
        hits = find_comment_routing_lines(line, surface="x")
        self.assertEqual(hits, [("x", 1)])

    def test_an_original_offending_line_also_counts_as_routing(self) -> None:
        line = "- Bad: tooling-specific troubleshooting (belongs as code comments)"
        hits = find_comment_routing_lines(line, surface="x")
        self.assertEqual(hits, [("x", 1)])

    def test_a_review_target_does_not_count_as_routing(self) -> None:
        line = "stringly-typed code, what-not-why comments, mixed responsibilities."
        self.assertEqual(find_comment_routing_lines(line, surface="x"), [])

    def test_a_file_with_no_routing_line_reports_no_hits(self) -> None:
        """The rename/deletion case: content with no comment-routing shape
        at all makes `find_comment_routing_lines` empty out, which is exactly
        what should fail leg 2's per-file vacuity guard."""
        text = "Nothing here routes to a comment at all.\nJust prose.\n"
        self.assertEqual(find_comment_routing_lines(text, surface="x"), [])


class TestLanguageTokenMatcher(unittest.TestCase):
    def test_docstring_word_is_flagged(self) -> None:
        hits = find_single_language_tokens("write a docstring here", surface="x")
        self.assertEqual(hits, [("x", "docstring")])

    def test_triple_quote_is_flagged(self) -> None:
        hits = find_single_language_tokens('use """ to open one', surface="x")
        self.assertEqual(hits, [("x", '"""')])

    def test_clean_prose_is_not_flagged(self) -> None:
        self.assertEqual(
            find_single_language_tokens("a comment carrying a why", surface="x"), []
        )


if __name__ == "__main__":
    unittest.main()

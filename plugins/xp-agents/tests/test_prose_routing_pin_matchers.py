#!/usr/bin/env python3
"""Mutation proof for the matchers `test_prose_routing_pin` reads.

Those matchers live in `_routing_detect`; this file is the synthetic half of the
pin's seam, mirroring `test_shipped_prose_language_agnostic_matchers.py`: this
file exercises them on SYNTHETIC text, the pin asserts the real tree complies. A
matcher that only ever runs against a tree already fixed by this same story
cannot prove it would have caught the ORIGINAL offenders, or that it stays
quiet on lines that merely mention "comment" without routing anything there.

No COMPLIANCE assertion belongs here — one added over the tree would be a second
copy of one the pin already makes, failing in lockstep and adding no detection.
Asserting that a FIXTURE below still matches what ships is a different claim and
would belong here, with the fixture; nothing does that yet.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _md_helpers import CORPUS_WIDE_FORBIDDEN, PROJECT_AGNOSTIC_FORBIDDEN_VOCAB
from _routing_detect import (
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
        """The five wordings the tree ships in place of `_ORIGINAL_OFFENDERS`.
        Kept in step with the real lines: a fixture pinning a wording no
        surface carries any more proves nothing about what ships."""
        fixed_lines = [
            "- **Constraints** — architectural/process bounds. Checkable "
            "claims→tests; history→git; comments→why the code can't "
            "express. Cap 15-20.",
            "- Bad: tooling-specific troubleshooting (checkable → a test, "
            "history → git, else a code comment for what the code cannot "
            "express)",
            "belongs in a test when checkable, git history when historical, "
            "a code comment only for what the code cannot express.",
            "goes to a test when checkable, git history when historical, "
            "else a code comment for what the code cannot express, a "
            "convention, an SMM Constraint event, or `docs/` instead.",
            "those live in a test when checkable, git history when "
            "historical, a code comment for what the code cannot express, "
            "or sprint.json.",
        ]
        for line in fixed_lines:
            with self.subTest(line=line):
                self.assertEqual(
                    find_unqualified_comment_routing(line, surface="x"), []
                )


class TestSentenceInitialCapitalizationIsMatched(unittest.TestCase):
    """Neither matcher may be fooled by a capital letter. A Markdown bullet
    that opens with "Code comments ..." or names "A test" mid-sentence is the
    same routing clause as its lowercase form."""

    def test_a_capitalized_comment_destination_is_still_selected(self) -> None:
        line = "Code comments hold anything left over."
        self.assertEqual(
            len(find_comment_routing_lines(line, surface="x")),
            1,
            "the selector missed a sentence-initial comment destination — "
            "such a line escapes every leg that gates on it",
        )
        self.assertEqual(len(find_unqualified_comment_routing(line, surface="x")), 1)

    def test_a_capitalized_test_destination_reads_as_compliant(self) -> None:
        line = (
            "A test holds the checkable claim; history to git; a code comment "
            "carries only the why the code cannot express."
        )
        self.assertEqual(
            find_unqualified_comment_routing(line, surface="x"),
            [],
            "a compliant line naming 'A test' was flagged — a false positive "
            "on correct prose is what gets a pin disabled",
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

    def test_capitalized_docstring_is_flagged(self) -> None:
        """The derivation proof: the matcher reads the central registry.

        No token list can be injected (see the matcher's docstring), so this
        exercises the real one: it carries both casings, and the local
        case-sensitive tuple this story deletes did not flag `Docstring`.
        """
        hits = find_single_language_tokens("a Docstring here", surface="x")
        self.assertEqual(hits, [("x", "Docstring")])


class TestTheCorpusWideCategoryJoinsTheUnion(unittest.TestCase):
    """The section-scoped guard must apply the corpus-wide category too.

    The scope property that justified the split — no member of
    `CORPUS_WIDE_FORBIDDEN` has a legitimate use in shipped prose — is asserted
    by the pin's leg 3 over the real tree, not here: leg 3 scans the same corpus
    for the same tokens, so a copy of it in this file would fail in lockstep and
    add no detection. Only the union relation is this file's business, since it
    is a property of the tuples and needs no tree read.
    """

    def test_the_corpus_wide_category_is_part_of_the_union(self) -> None:
        """Regression guard, not a red proof: the union is built by
        concatenation, so this can only fail if someone hand-edits it apart."""
        for token in CORPUS_WIDE_FORBIDDEN:
            self.assertIn(token, PROJECT_AGNOSTIC_FORBIDDEN_VOCAB)


if __name__ == "__main__":
    unittest.main()

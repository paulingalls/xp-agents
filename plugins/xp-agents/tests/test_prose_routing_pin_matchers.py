#!/usr/bin/env python3
"""Mutation proof for the matchers the two routing pins read.

Those matchers live in `_routing_detect`; this file is the synthetic half of the
pins' seam, mirroring `test_shipped_prose_language_agnostic_matchers.py`: this
file exercises them on SYNTHETIC text, the pins assert the real tree complies. A
matcher that only ever runs against a tree already fixed by this same story
cannot prove it would have caught the ORIGINAL offenders, or that it stays
quiet on lines that merely mention "comment" without routing anything there.

No COMPLIANCE assertion belongs here — one added over the tree would be a second
copy of one a pin already makes, failing in lockstep and adding no detection.
Asserting that a FIXTURE below still matches what ships is a different claim and
would belong here, with the fixture; nothing does that yet.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _md_helpers import (
    CORPUS_WIDE_FORBIDDEN,
    OCCUPANCY_EXEMPT,
    PROJECT_AGNOSTIC_FORBIDDEN_VOCAB,
    SECTION_SCOPED_FORBIDDEN,
)
from _routing_detect import (
    find_comment_routing_lines,
    find_incomplete_rule_lines,
    find_section_scoped_tokens,
    find_single_language_tokens,
    zero_use_members,
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
                hits = find_incomplete_rule_lines(line, surface=label)
                self.assertEqual(
                    len(hits),
                    1,
                    f"{label!r} was not flagged as a partial routing rule: {line!r}",
                )
                self.assertEqual(hits[0][0], label)
                self.assertIn(
                    "test",
                    hits[0][2],
                    f"{label!r} named no test destination, so its missing legs "
                    "must include the test leg",
                )


class TestCommentRoutingMatcherStaysQuietOnNonOffenders(unittest.TestCase):
    def test_a_review_target_is_not_selected(self) -> None:
        """A comment named as a review SUBJECT is not a routing destination —
        the shape the selector must not confuse with a destination clause."""
        line = (
            "- **Quality** — redundant state, parameter sprawl, copy-paste "
            "variations, leaky abstractions, stringly-typed code, "
            "self-evident comments, mixed responsibilities."
        )
        self.assertEqual(find_incomplete_rule_lines(line, surface="x"), [])

    def test_story_002_bucket_phrasing_is_not_flagged(self) -> None:
        """A reviewer bucket that names a comment as something to KEEP (not
        route new content to) must not be confused with a routing clause."""
        line = (
            "a comment carrying a rejected design decision and the reason "
            "it was rejected is NOT flagged"
        )
        self.assertEqual(find_incomplete_rule_lines(line, surface="x"), [])


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
        self.assertEqual(
            find_incomplete_rule_lines(line, surface="x"),
            [("x", 1, "test,git,why")],
        )

    def test_a_capitalized_test_destination_reads_as_compliant(self) -> None:
        line = (
            "A test holds the checkable claim; history to git; a code comment "
            "carries only the why the code cannot express."
        )
        self.assertEqual(
            find_incomplete_rule_lines(line, surface="x"),
            [],
            "a compliant line naming 'A test' was flagged — a false positive "
            "on correct prose is what gets a pin disabled",
        )


class TestKnownMatcherBlindSpots(unittest.TestCase):
    """The under- and over-match LIMITS bullets, made checkable instead of
    merely claimed — a limit stated only in prose is the same unverified claim
    this milestone exists to route into a test.

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
                    find_comment_routing_lines(line, surface="x"),
                    [],
                    "selector grew to catch this phrasing — update the "
                    "under-match LIMITS bullets in both routing pins",
                )

    def test_an_incidental_mention_of_a_test_satisfies_the_test_leg(self) -> None:
        line = "implementation detail belongs in code comments, not in a test"
        self.assertEqual(
            find_incomplete_rule_lines(line, surface="x"),
            [("x", 1, "git,why")],
            "TEST_DEST_RE accepts any 'a test' on the line, so this line's "
            "test leg reads as satisfied — if it no longer does, the matcher "
            "grew to discriminate an incidental mention and the under-match "
            "LIMITS bullet needs updating",
        )

    def test_prose_that_merely_discusses_code_comments_is_over_selected(self) -> None:
        """The over-match limit: the selector is a phrase match, so prose that
        routes nothing is still held to the three-leg rule.

        An author who writes either of these gets a red pin whose only escape
        is appending destinations to a sentence that routes nothing. Recorded
        rather than fixed: every narrowing tried under-flags one of the comma-
        or "else"-joined forms the tree actually ships.
        """
        for line in (
            "Flag code comments that restate the code.",
            "Never rely on code comments for API contracts.",
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    find_incomplete_rule_lines(line, surface="x"),
                    [("x", 1, "test,git,why")],
                    "the selector learned to tell a destination from a "
                    "mention — delete this case and the over-match LIMITS "
                    "bullets with it",
                )


class TestCommentRoutingShapeMatcherBacksVacuityGuard(unittest.TestCase):
    """The vacuity guard reads `find_comment_routing_lines`, which must
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
        line = "stringly-typed code, self-evident comments, mixed responsibilities."
        self.assertEqual(find_comment_routing_lines(line, surface="x"), [])

    def test_a_file_with_no_routing_line_reports_no_hits(self) -> None:
        """The rename/deletion case: content with no comment-routing shape
        at all makes `find_comment_routing_lines` empty out, which is exactly
        what should fail the per-file vacuity guard."""
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


class TestSectionScopedTokenMirrorFinder(unittest.TestCase):
    """`find_section_scoped_tokens` is the reverse leg's finder: the forward
    leg asks "did a banned token leak", this asks "does a filed-section-scoped
    token still have the use that justified filing it there"."""

    def test_a_section_scoped_member_is_detected(self) -> None:
        hits = find_section_scoped_tokens("written in .py", surface="x")
        self.assertEqual(hits, [("x", ".py")])

    def test_clean_prose_is_not_flagged(self) -> None:
        self.assertEqual(
            find_section_scoped_tokens("a comment carrying a why", surface="x"), []
        )


class TestZeroUseMembersReddens(unittest.TestCase):
    """`zero_use_members` is the arithmetic the reverse leg's assertion runs.
    A finder proof alone says nothing about whether the leg would ever fire —
    this is the piece that proves it can."""

    def test_a_member_absent_from_every_text_is_returned(self) -> None:
        result = zero_use_members(
            ("present", "absent"), ["text carrying present", "another text"]
        )
        self.assertEqual(result, ["absent"])

    def test_a_member_present_in_any_text_is_not_returned(self) -> None:
        result = zero_use_members(("present",), ["text carrying present"])
        self.assertEqual(result, [])


class TestSectionScopedOccupancyLegIsNotVacuous(unittest.TestCase):
    """The reverse leg cannot pass by having nothing left to check: at least
    one SECTION_SCOPED_FORBIDDEN member must fall outside OCCUPANCY_EXEMPT."""

    def test_non_exempt_members_remain(self) -> None:
        checked = [t for t in SECTION_SCOPED_FORBIDDEN if t not in OCCUPANCY_EXEMPT]
        self.assertTrue(checked)


class TestTheCorpusWideCategoryJoinsTheUnion(unittest.TestCase):
    """The section-scoped guard must apply the corpus-wide category too.

    The scope property that justified the split — no member of
    `CORPUS_WIDE_FORBIDDEN` has a legitimate use in shipped prose — is asserted
    by the pin's vocabulary leg over the real tree, not here: that leg scans
    the same corpus for the same tokens, so a copy of it here would fail in
    lockstep and
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

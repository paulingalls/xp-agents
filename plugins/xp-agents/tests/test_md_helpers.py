#!/usr/bin/env python3
"""Contract pins for the shared prose-scanning helpers in `_md_helpers.py`.

These sit beside the helper rather than inside any one prose suite: four
suites across two agents route their forbidden-vocabulary scan through
`assert_project_agnostic`, so a regression in the helper degrades all of them
at once. A pin that lives inside one consumer reads as that consumer's
business; this file exists so the contract is discoverable from the helper.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _md_helpers import (
    MIXED_CASE_VOCAB_MEMBERS,
    PROJECT_AGNOSTIC_FORBIDDEN_VOCAB,
    assert_project_agnostic,
)


class TestProjectAgnosticAssertHelper(unittest.TestCase):
    """Pin the shared vocab-scan helper's own contract: scan RAW.

    Four prose suites across two agents route their forbidden-vocabulary scan
    through `assert_project_agnostic`. Centralizing the loop is the point of
    the extraction, but it also concentrates the blast radius: a helper that
    lowercased its input would degrade all four guards at once, silently. So
    the "scan RAW, never lowercase" contract is pinned here, at the helper,
    rather than restated as a comment at each call site.
    """

    # Merely asserting "it raises" would leave `ACCEPT_IN_FLIGHT` inert: the
    # tuple lists that name in BOTH casings, so a lowercasing helper still
    # raises — on the lowercase twin. The assertion therefore pins WHICH member
    # the failure names, in its raw casing, so a lowercasing helper goes red on
    # both members rather than only on ` LOC` (the one member with no twin to
    # cover for it). That the message names the offending token at all is part
    # of the helper's contract too — a scan that fails without saying what
    # leaked sends the reader back to the tuple.

    def test_mixed_case_members_still_fail_through_the_helper(self):
        for member in MIXED_CASE_VOCAB_MEMBERS:
            with self.subTest(member=member):
                self.assertIn(member, PROJECT_AGNOSTIC_FORBIDDEN_VOCAB)
                with self.assertRaisesRegex(
                    AssertionError, re.escape(f"token: {member!r}")
                ):
                    assert_project_agnostic(
                        self,
                        f"a prose section mentioning {member} verbatim",
                        "fixture section",
                    )

    def test_the_triple_quote_token_is_caught_section_scoped_too(self):
        """story-004: the corpus-wide category joins the union, so the
        section-scoped guard gains the triple-quote token it never carried.

        Pins WHICH token the failure names, per the contract above: a bare
        "it raised" would also pass on a hit from any other union member.
        """
        with self.assertRaisesRegex(AssertionError, re.escape('token: \'"""\'')):
            assert_project_agnostic(
                self,
                'a prose section telling the reader to use """ to open one',
                "fixture section",
            )

    def test_helper_passes_clean_prose(self):
        """A guard that fails on everything is as useless as one that fails on
        nothing — pin the negative case too."""
        assert_project_agnostic(
            self,
            "a prose section using only generic terms: state field, marker, gate.",
            "fixture section",
        )

    def test_a_longer_word_sharing_a_members_prefix_does_not_false_positive(self):
        """Boundary-aware proof: ` LOC` is a substring of ` LOCAL`, so a
        substring-matching helper raises on this clean sentence. Genuine-use
        matching must not."""
        assert_project_agnostic(
            self,
            "a LOCAL variable holds no cross-request state.",
            "fixture section",
        )

    def test_the_new_plural_members_are_caught_through_the_helper(self):
        """story-008: boundary matching stops `docstring`/`Docstring`/` LOC`
        covering their plural forms, so each plural gets its own registry
        entry — pinned here with its own fails-before proof."""
        fixtures = {
            "docstrings": "restate the file in prose instead of trusting docstrings",
            "Docstrings": "Docstrings are not a substitute for tests.",
            " LOCs": "keep files under 500 LOCs total",
        }
        for member, section in fixtures.items():
            with (
                self.subTest(member=member),
                self.assertRaisesRegex(AssertionError, re.escape(f"token: {member!r}")),
            ):
                assert_project_agnostic(self, section, "fixture section")


if __name__ == "__main__":
    unittest.main()

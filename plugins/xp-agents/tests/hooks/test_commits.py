#!/usr/bin/env python3
"""Tests for scripts/commits.py: commit-message-body parsing (Resolves-Event
trailer and implicit event-id extraction).

Issue-matching and file-listing tests live in test_commits_issues.py.
Git subprocess helpers (staged/committed files, diffs, hashes, merge bodies)
live in test_commits_git_helpers.py.
Command-string parsing (extract_commit_message, escape-hatch classification,
effective cwd) lives in test_commits_escape_hatch.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commits

# ---------------------------------------------------------------------------
# parse_commit_message
# ---------------------------------------------------------------------------


class TestParseCommitMessage(unittest.TestCase):
    """Test commit message extraction from git output."""

    def test_standard_output(self):
        out = "[main abc1234] Fix the bug\n 1 file changed"
        self.assertEqual(commits.parse_commit_message(out), "Fix the bug")

    def test_branch_with_slash(self):
        out = "[feature/foo abc1234] Add feature"
        self.assertEqual(commits.parse_commit_message(out), "Add feature")

    def test_no_match(self):
        self.assertIsNone(commits.parse_commit_message("not a commit"))

    def test_empty(self):
        self.assertIsNone(commits.parse_commit_message(""))


# ---------------------------------------------------------------------------
# extract_resolves_trailer
# ---------------------------------------------------------------------------


class TestExtractResolvesTrailer(unittest.TestCase):
    """Test extraction of Resolves-Event: trailer from commit body."""

    def test_single_id(self):
        body = "Fix the bug\n\nRationale.\n\nResolves-Event: 4eb35ddcd24e"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_comma_separated_ids(self):
        body = "Title\n\nResolves-Event: 4eb35ddcd24e, a55290ae79b9"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e", "a55290ae79b9"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_multiple_trailer_lines(self):
        body = (
            "Title\n\nbody.\n\n"
            "Resolves-Event: 4eb35ddcd24e\n"
            "Resolves-Event: a55290ae79b9"
        )
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e", "a55290ae79b9"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_case_insensitive_key(self):
        body = "Title\n\nresolves-event: 4eb35ddcd24e"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e"])
        self.assertNotIn("resolves-event", cleaned.lower())

    def test_deduplicates_preserving_order(self):
        body = (
            "Title\n\n"
            "Resolves-Event: abc123abc123\n"
            "Resolves-Event: def456def456, abc123abc123"
        )
        ids, *_ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["abc123abc123", "def456def456"])

    def test_ignores_inline_mentions(self):
        """Trailer must start at line beginning, not in prose."""
        body = "Fix the thing that Resolves-Event: 4eb35ddcd24e in passing"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, body)

    def test_rejects_non_hex_ids(self):
        body = "Title\n\nResolves-Event: not-a-hex-id"
        ids, *_ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])

    def test_rejects_wrong_length_ids(self):
        body = "Title\n\nResolves-Event: abc123, 1234567890123456"
        ids, *_ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])

    def test_no_trailer(self):
        body = "Fix the bug\n\nSome rationale."
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, body)

    def test_empty_body(self):
        ids, cleaned, _ = commits.extract_resolves_trailer("")
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, "")

    def test_none_body(self):
        ids, cleaned, has = commits.extract_resolves_trailer(None)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, "")
        self.assertFalse(has)

    def test_has_trailer_true_with_valid_id(self):
        body = "Fix bug\n\nResolves-Event: 4eb35ddcd24e"
        _, _, has = commits.extract_resolves_trailer(body)
        self.assertTrue(has)

    def test_has_trailer_true_with_none(self):
        """Resolves-Event: none is valid discipline — trailer is present."""
        body = "Fix bug\n\nResolves-Event: none"
        ids, _, has = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertTrue(has)

    def test_has_trailer_false_when_absent(self):
        body = "Fix bug\n\nSome rationale."
        _, _, has = commits.extract_resolves_trailer(body)
        self.assertFalse(has)


class TestExtractResolvesTrailerBlankLineShapes(unittest.TestCase):
    """Regression pins for story-008 leg (a).

    The debt (1713b96b9bb7) blamed a blank line separating the
    `Resolves-Event:` trailer from `Co-Authored-By` for the trailer "falling
    out of git's final trailer block". That is FALSE for this parser:
    `extract_resolves_trailer` is a line-anchored regex over the full `%B`
    body, not git's trailer-block parser, so a blank line anywhere is
    irrelevant. These all PASS today — they lock the correct behavior
    against a future accidental switch to a trailer-block parser, not a
    red->green fix.
    """

    def test_trailer_separated_from_co_authored_by_a_blank_line(self):
        body = (
            "fix: something\n\n"
            "Resolves-Event: c460a9b512a7\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
        )
        ids, _, has = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["c460a9b512a7"])
        self.assertTrue(has)

    def test_trailer_followed_by_a_trailing_blank_line(self):
        body = "fix: something\n\nResolves-Event: c460a9b512a7\n\n"
        ids, _, has = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["c460a9b512a7"])
        self.assertTrue(has)

    def test_trailer_as_last_line_after_co_authored_by(self):
        body = (
            "fix: something\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            "Resolves-Event: c460a9b512a7"
        )
        ids, _, has = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["c460a9b512a7"])
        self.assertTrue(has)


# ---------------------------------------------------------------------------
# extract_implicit_event_ids
# ---------------------------------------------------------------------------


class TestExtractImplicitEventIds(unittest.TestCase):
    """Test extraction of bare 12-hex event IDs from commit body."""

    def test_single_bare_id_matched(self):
        body = "fixes a1b2c3d4e5f6"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            ["a1b2c3d4e5f6"],
        )

    def test_empty_known_ids_returns_empty(self):
        body = "fixes a1b2c3d4e5f6"
        self.assertEqual(commits.extract_implicit_event_ids(body, set()), [])

    def test_id_not_in_known_ids_ignored(self):
        body = "closes concern a1b2c3d4e5f6"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"ffffffffffff"}),
            [],
        )

    def test_eleven_char_hex_rejected(self):
        body = "see a1b2c3d4e5f"  # 11 chars
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_thirteen_char_hex_rejected(self):
        body = "see a1b2c3d4e5f6a"  # 13 chars
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_uppercase_hex_rejected(self):
        body = "see A1B2C3D4E5F6"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_non_hex_chars_rejected(self):
        body = "see g1b2c3d4e5f6"  # 'g' is not hex
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_deduplicates_preserving_first_seen_order(self):
        body = "fixes a1b2c3d4e5f6 and again a1b2c3d4e5f6"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            ["a1b2c3d4e5f6"],
        )

    def test_multiple_distinct_ids_first_seen_order(self):
        body = "closes b222222222b2, then a111111111a1"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a111111111a1", "b222222222b2"}),
            ["b222222222b2", "a111111111a1"],
        )

    def test_id_embedded_in_longer_hex_not_matched(self):
        body = "see commit a1b2c3d4e5f6deadbeef01234567890abcdef1234"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_empty_body_returns_empty(self):
        self.assertEqual(
            commits.extract_implicit_event_ids("", {"a1b2c3d4e5f6"}),
            [],
        )

    def test_none_body_returns_empty(self):
        self.assertEqual(
            commits.extract_implicit_event_ids(None, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_punctuation_around_id_still_matches(self):
        body = "fixes (a1b2c3d4e5f6)."
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            ["a1b2c3d4e5f6"],
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — pattern 5 non-adjacent supersedes.

Pattern 5 (concern_conflicts.py) previously checked only decs[-2] against
the newest decision's metadata.supersedes/resolves, so a link naming a
non-adjacent same-topic decision still flagged. These tests pin the fix:
any earlier same-topic decision explicitly superseded/resolved by the
newest one suppresses the flag.

Sibling file test_common_conflicts_superseded.py covers the 2-decision
(adjacent) case exhaustively and must stay unedited — its decs[:-1] is
always exactly [decs[-2]], so it is the purity proof that the narrowing
does not change adjacent-pair behavior.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import concerns
from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_DECISION,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_SUPERSEDES,
)


class TestDecisionSupersedesNonAdjacent(_HookTestCase):
    def _superseded(self, found):
        return [c for c in found if "superseded" in c["content"].lower()]

    def test_non_adjacent_supersedes_suppresses(self):
        """Newest decision supersedes the FIRST of 3+ same-topic decisions —
        must still suppress even though it isn't the immediately-prior one."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Back to Postgres",
            metadata={METADATA_KEY_SUPERSEDES: [d1["id"]]},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 0)

    def test_no_link_still_flags_with_three_decisions(self):
        """Bypass guard: 3+ decisions, newest supersedes nothing — still flags."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use SQLite")
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 1)

    def test_supersedes_unknown_id_still_flags(self):
        """Newest decision supersedes an id that is no decision on the topic."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use SQLite",
            metadata={METADATA_KEY_SUPERSEDES: ["deadbeef12345678"]},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 1)

    def test_real_data_shape_names_immediately_prior(self):
        """Two prior decisions plus a third naming only the immediately-prior
        one — clean. This is the real story-data shape."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use SQLite",
            metadata={METADATA_KEY_SUPERSEDES: [d2["id"]]},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 0)

    def test_empty_supersedes_array_still_flags(self):
        """Empty supersedes array on newest of 3+ decisions — still flags."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use SQLite",
            metadata={METADATA_KEY_SUPERSEDES: []},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 1)

    def test_blank_string_supersedes_still_flags(self):
        """['' ] supersedes on newest of 3+ decisions — still flags."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use SQLite",
            metadata={METADATA_KEY_SUPERSEDES: [""]},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 1)

    def test_empty_id_on_earlier_decision_does_not_fail_open(self):
        """Load-bearing guard: an earlier same-topic decision with an empty/
        absent id must NOT be treated as superseded just because
        `_declares_supersession(meta, "")` is vacuously true (s.startswith("")
        is always True). Widening from one target to decs[:-1] must guard on
        the earlier decision's own id being non-empty, else this fails open.
        """
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d1["id"] = ""  # simulate missing/empty id on an earlier decision
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use SQLite",
            metadata={METADATA_KEY_SUPERSEDES: ["some-unrelated-id"]},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 1)

    def test_short_prefix_ambiguity_still_suppresses_intended_case(self):
        """_declares_supersession is bidirectionally prefix-tolerant with no
        ambiguity guard (unlike resolution.resolve_prefix, which returns None
        on 2+ matches). Iterating decs[:-1] gives an over-short declared
        prefix N chances to match instead of 1 — pin the intended-suppression
        behavior so the blast radius is on record: a short prefix that
        uniquely matches one earlier decision's id still suppresses."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d1["id"] = "abc123def456"
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Back to Postgres",
            metadata={METADATA_KEY_SUPERSEDES: ["abc123"]},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 0)

    def test_resolves_leg_at_non_adjacent_distance_suppresses(self):
        """_declares_supersession ORs supersedes and resolves — the widening
        also silences a topic when the newest decision `resolves` an earlier
        (non-adjacent) same-topic decision. This is the path the story's
        real appends actually exercise."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        d3 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Back to Postgres",
            metadata={METADATA_KEY_RESOLVES: [d1["id"]]},
        )
        found = concerns.detect_conflicts([d1, d2, d3], "main")
        self.assertEqual(len(self._superseded(found)), 0)


if __name__ == "__main__":
    unittest.main()

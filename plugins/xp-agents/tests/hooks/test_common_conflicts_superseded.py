#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — pattern 5: superseded decision.

Split from test_common_conflicts.py (pure move, no test-body edits).
Sibling patterns: overlap (1), assumption (2), convention (3),
stale_question (4) each live in their own test_common_conflicts_<pattern>.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import concerns
from conftest import _HookTestCase, make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_STATUS,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_SUPERSEDES,
)


class TestDetectConflictsCommon(_HookTestCase):
    def test_superseded_decision(self):
        events = [
            make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres"),
            make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL"),
        ]
        found = concerns.detect_conflicts(events, "main")
        self.assertTrue(any("superseded" in c["content"].lower() for c in found))

    def test_supersedes_metadata_skips_concern(self):
        """metadata.supersedes referencing the prior decision suppresses pattern #5."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": [d1["id"]]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_supersedes_metadata_wrong_id_still_fires(self):
        """Bogus nonexistent ID in supersedes does NOT silence the check."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": ["deadbeef12345678"]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_supersedes_metadata_empty_array_still_fires(self):
        """Empty supersedes array means no explicit override — concern still raised."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": []},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_resolves_metadata_skips_concern(self):
        """metadata.resolves on the later decision declares supersedence —
        the cascade auto-closes the prior decision, so suppressing the
        superseded-flag here is symmetric with the supersedes path and
        matches the pre_tool_bash advisory nudge's treatment.
        """
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={METADATA_KEY_RESOLVES: [d1["id"]]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_resolves_metadata_wrong_id_still_fires(self):
        """Bogus IDs must not silence the check — false-negative would hide
        real conflicts.
        """
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={METADATA_KEY_RESOLVES: ["deadbeef12345678"]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_resolves_and_supersedes_both_set_skips(self):
        """Pins OR semantics: even with a junk supersedes, a valid resolves
        still suppresses. Without this, a future refactor to AND or to
        supersedes-takes-precedence would pass the other two tests silently.
        """
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={
                METADATA_KEY_SUPERSEDES: ["deadbeef12345678"],
                METADATA_KEY_RESOLVES: [d1["id"]],
            },
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_empty_string_in_supersedes_does_not_skip_superseded_decision(self):
        """Pattern 5 parity: metadata.supersedes=[''] must not blanket-suppress
        the superseded-decision flag."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={METADATA_KEY_SUPERSEDES: [""]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_superseded_decision_concern_references_prior_decision(self):
        """Flag concern references the older (superseded) decision id."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        found = concerns.detect_conflicts([d1, d2], "main")
        flag = next(c for c in found if "superseded" in c["content"].lower())
        self.assertEqual(flag.get("references"), [d1["id"]])

    def test_supersedes_metadata_different_topic_still_fires(self):
        """supersedes must reference the same-topic predecessor, not any decision."""
        d_other = make_event(
            EVENT_TYPE_DECISION, topic="api", content="Use REST"
        )  # different topic
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(
            EVENT_TYPE_DECISION,
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": [d_other["id"]]},  # wrong topic reference
        )
        found = concerns.detect_conflicts([d_other, d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_resolved_superseded_concern_marks_topic_accepted(self):
        """Resolving a superseded-decision concern marks its topic as additive."""
        topic = "retro-try-answer-recording"
        old_concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Superseded decision: topic '{topic}' has multiple "
            "decisions without an intervening concern.",
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Accepted as additive",
            metadata={"resolves": [old_concern["id"]]},
        )
        d1 = make_event(EVENT_TYPE_DECISION, topic=topic, content="First")
        d2 = make_event(EVENT_TYPE_DECISION, topic=topic, content="Second")
        d3 = make_event(EVENT_TYPE_DECISION, topic=topic, content="Third")
        events = [old_concern, resolution, d1, d2, d3]
        found = concerns.detect_conflicts(events, "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_resolved_superseded_different_topic_does_not_cross_contaminate(self):
        """Accepted topic acceptance is topic-scoped, not global."""
        accepted_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Superseded decision: topic 'topic-a' has multiple "
            "decisions without an intervening concern.",
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Accepted",
            metadata={"resolves": [accepted_concern["id"]]},
        )
        d1 = make_event(EVENT_TYPE_DECISION, topic="topic-b", content="Use X")
        d2 = make_event(EVENT_TYPE_DECISION, topic="topic-b", content="Use Y")
        events = [accepted_concern, resolution, d1, d2]
        found = concerns.detect_conflicts(events, "main")
        b_concerns = [c for c in found if "topic 'topic-b'" in c["content"]]
        self.assertEqual(len(b_concerns), 1)

    def test_resolved_superseded_still_triggers_other_patterns(self):
        """Accepted-topic skip is pattern-#5-only — other patterns still fire."""
        accepted = make_event(
            EVENT_TYPE_CONCERN,
            content="Superseded decision: topic 'naming' has multiple "
            "decisions without an intervening concern.",
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Accepted",
            metadata={"resolves": [accepted["id"]]},
        )
        conv = make_event(
            EVENT_TYPE_CONVENTION, topic="naming", content="Use camelCase"
        )
        dec = make_event(EVENT_TYPE_DECISION, topic="naming", content="Use snake_case")
        events = [accepted, resolution, conv, dec]
        found = concerns.detect_conflicts(events, "main")
        convention_concerns = [c for c in found if "convention" in c["content"].lower()]
        self.assertEqual(len(convention_concerns), 1)

    def test_superseded_decision_cross_session_excluded(self):
        """Decisions on same topic separated by a session_started anchor are
        NOT flagged."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        boundary = make_event(EVENT_TYPE_SESSION_STARTED, content="session started")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        found = concerns.detect_conflicts([d1, boundary, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_superseded_decision_same_session_still_fires(self):
        """Same-session decision pair on same topic still triggers concern."""
        # Prior-session decision is excluded from the window; in-session
        # pair (d1, d2) is what should fire.
        old_d = make_event(EVENT_TYPE_DECISION, topic="db", content="Use SQLite")
        boundary = make_event(EVENT_TYPE_SESSION_STARTED, content="session started")
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        found = concerns.detect_conflicts([old_d, boundary, d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)
        self.assertIn(
            "Superseded decision: topic 'db'",
            superseded[0]["content"],
        )

    def test_superseded_decision_in_session_acceptance_honored(self):
        """In-window already_accepted_topics resolution still skips re-fire."""
        topic = "db"
        boundary = make_event(EVENT_TYPE_SESSION_STARTED, content="session started")
        old_concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Superseded decision: topic '{topic}' has multiple "
            "decisions without an intervening concern.",
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Accepted as additive",
            metadata={"resolves": [old_concern["id"]]},
        )
        d1 = make_event(EVENT_TYPE_DECISION, topic=topic, content="First")
        d2 = make_event(EVENT_TYPE_DECISION, topic=topic, content="Second")
        d3 = make_event(EVENT_TYPE_DECISION, topic=topic, content="Third")
        events = [boundary, old_concern, resolution, d1, d2, d3]
        found = concerns.detect_conflicts(events, "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_superseded_decision_exempt_topic_skipped(self):
        """Topics in SUPERSEDED_DECISION_EXEMPT_TOPICS never trip the detector.

        execution-mode is re-decided by /xp-assign each kickoff;
        multiple decisions per session are normal, not silent
        supersession. The exemption covers the same-session pair case
        that cross-session scoping doesn't catch.
        """
        d1 = make_event(EVENT_TYPE_DECISION, topic="execution-mode", content="Solo")
        d2 = make_event(
            EVENT_TYPE_DECISION, topic="execution-mode", content="Teammates"
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_superseded_decision_e2e_only_in_session_pairs_fire(self):
        """Cross+in-session sequences only flag in-session pairs."""
        # Session 1: stable topic decided once
        s1_a = make_event(EVENT_TYPE_DECISION, topic="topic-a", content="Pick A1")
        s1_b = make_event(EVENT_TYPE_DECISION, topic="topic-b", content="Pick B1")
        s2_start = make_event(EVENT_TYPE_SESSION_STARTED, content="start of s2")
        # Session 2: re-cite topic-a (cross-session re-cite, MUST NOT fire),
        # and topic-c gets two in-session decisions (MUST fire once).
        s2_a = make_event(EVENT_TYPE_DECISION, topic="topic-a", content="Pick A2")
        s2_c1 = make_event(EVENT_TYPE_DECISION, topic="topic-c", content="C1")
        s2_c2 = make_event(EVENT_TYPE_DECISION, topic="topic-c", content="C2")
        events = [s1_a, s1_b, s2_start, s2_a, s2_c1, s2_c2]
        found = concerns.detect_conflicts(events, "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)
        self.assertIn("topic 'topic-c'", superseded[0]["content"])

    def test_no_duplicate_superseded_decision(self):
        """Should not re-generate concern if one already exists for same conflict."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        existing_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Superseded decision: topic 'db' has multiple "
            "decisions without an intervening concern.",
        )
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        events = [d1, existing_concern, d2]
        found = concerns.detect_conflicts(events, "main")
        superseded_concerns = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded_concerns), 0)


if __name__ == "__main__":
    unittest.main()

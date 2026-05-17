#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — conflict detection patterns.

Split from test_common_smm.py. Covers all 5 conflict patterns:
overlapping working_on, assumption contradicted, convention violation,
stale question, superseded decision.
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
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_SESSION_END,
    EVENT_TYPE_STATUS,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_SUPERSEDES,
)


class TestDetectConflictsCommon(_HookTestCase):
    """Test detect_conflicts after extraction to concerns.py."""

    def test_overlapping_working_on(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        self.assertTrue(any("overlap" in c["content"].lower() for c in found))

    def test_overlap_concern_has_files_field(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap = [c for c in found if "overlap" in c["content"].lower()]
        self.assertTrue(len(overlap) > 0)
        self.assertIn("files", overlap[0])
        self.assertEqual(len(overlap[0]["files"]), 1)
        self.assertTrue(overlap[0]["files"][0].endswith("app.ts"))

    def test_no_overlap_different_file(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/other.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_empty_working_on_clears_overlap(self):
        """working_on=[] should clear agent's file list."""
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
            make_event(EVENT_TYPE_STATUS, agent_id="other", working_on=[]),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_stale_question_detected(self):
        q = make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        found = concerns.detect_conflicts(
            [q, *filler], "main", file_path="/tmp/x.ts", cwd="/tmp"
        )
        self.assertTrue(any("stale" in c["content"].lower() for c in found))

    def test_without_file_path_skips_pattern_1(self):
        """When file_path=None, skip overlapping working_on check."""
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(events, "main")
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_without_file_path_runs_other_patterns(self):
        """Patterns 2-5 still run when file_path=None."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY, content="Actually GraphQL", references=[a["id"]]
        )
        found = concerns.detect_conflicts([a, d], "main")
        self.assertTrue(any("contradict" in c["content"].lower() for c in found))

    def test_superseded_decision(self):
        events = [
            make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres"),
            make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL"),
        ]
        found = concerns.detect_conflicts(events, "main")
        self.assertTrue(any("superseded" in c["content"].lower() for c in found))

    def test_convention_violation(self):
        events = [
            make_event(EVENT_TYPE_CONVENTION, topic="naming", content="Use camelCase"),
            make_event(EVENT_TYPE_DECISION, topic="naming", content="Use snake_case"),
        ]
        found = concerns.detect_conflicts(events, "main")
        self.assertTrue(any("convention" in c["content"].lower() for c in found))

    def test_no_duplicate_convention_violation(self):
        """Should not re-generate concern if one already exists for same conflict."""
        conv = make_event(
            EVENT_TYPE_CONVENTION, topic="naming", content="Use camelCase"
        )
        dec = make_event(EVENT_TYPE_DECISION, topic="naming", content="Use snake_case")
        existing_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Convention violation: decision on 'naming' "
            "diverges from established convention.",
        )
        events = [conv, dec, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        convention_concerns = [c for c in found if "convention" in c["content"].lower()]
        self.assertEqual(len(convention_concerns), 0)

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

    def test_assumption_contradicted_concern_references_assumption(self):
        """Flag concern references the assumption event it flags (WEAK link)."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY, content="Actually GraphQL", references=[a["id"]]
        )
        found = concerns.detect_conflicts([a, d], "main")
        flag = next(c for c in found if "contradict" in c["content"].lower())
        self.assertEqual(flag.get("references"), [a["id"]])

    def test_assumption_contradicted_within_budget(self):
        """Assumption contradicted concern must stay within 400-char budget."""
        from event_schema import get_required_budget

        a = make_event(EVENT_TYPE_ASSUMPTION, content="x" * 300)
        d = make_event(EVENT_TYPE_DISCOVERY, content="y" * 300, references=[a["id"]])
        found = concerns.detect_conflicts([a, d], "main")
        flag = next(c for c in found if "contradict" in c["content"].lower())
        budget = get_required_budget("concern")
        self.assertLessEqual(
            len(flag["content"]),
            budget,
            f"concern content {len(flag['content'])} exceeds {budget}",
        )

    def test_multiple_discoveries_contradicting_same_assumption_emit_once(self):
        """N discoveries against one assumption → one concern, not N.

        Models the legacy-project pattern where 27 teammate agents each
        emitted a contradiction concern against assumption 210fe2885dec.
        Dedup must key on references, not content (which varies per
        discovery snippet).
        """
        a = make_event(EVENT_TYPE_ASSUMPTION, content="namespace shape will reconcile")
        d1 = make_event(
            EVENT_TYPE_DISCOVERY,
            content="packages/shared re-exports flat",
            references=[a["id"]],
        )
        d2 = make_event(
            EVENT_TYPE_DISCOVERY,
            content="createFieldCrypto exported at top",
            references=[a["id"]],
        )
        d3 = make_event(
            EVENT_TYPE_DISCOVERY,
            content="encryption barrel has the type",
            references=[a["id"]],
        )
        found = concerns.detect_conflicts([a, d1, d2, d3], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(
            len(contradicts),
            1,
            f"expected 1 contradiction concern (dedup by refs), got {len(contradicts)}",
        )
        self.assertEqual(contradicts[0].get("references"), [a["id"]])

    def test_ref_dedup_is_global_across_patterns(self):
        """An unresolved concern with refs=[X] suppresses re-emission for refs=[X].

        Cross-session pin: simulates a session-1 emission landing in the
        event log with one content phrasing, then a session-2 re-scan
        finding the same trigger. The new ref-dedup must short-circuit
        even when the existing concern's content text differs from what
        the current emitter would produce.

        Uses Pattern 3 (convention violation) — refs=[convention_id] is
        cross-pattern-stable. If this test passes, the ref-dedup contract
        holds globally, not just for the Pattern 2 bug fix.
        """
        conv = make_event(
            EVENT_TYPE_CONVENTION, topic="naming", content="Use camelCase"
        )
        dec = make_event(EVENT_TYPE_DECISION, topic="naming", content="Use snake_case")
        existing_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="DRIFTED PHRASING: prior-release wording for convention violation",
            references=[conv["id"]],
        )
        found = concerns.detect_conflicts([conv, dec, existing_concern], "main")
        new_violations = [c for c in found if "convention" in c["content"].lower()]
        self.assertEqual(
            len(new_violations),
            0,
            "ref-dedup must suppress re-emission when an unresolved concern "
            "already references the same root, regardless of content phrasing drift",
        )

    def test_convention_violation_concern_references_conventions(self):
        """Flag concern references the topic's convention ids."""
        conv = make_event(
            EVENT_TYPE_CONVENTION, topic="naming", content="Use camelCase"
        )
        dec = make_event(EVENT_TYPE_DECISION, topic="naming", content="Use snake_case")
        found = concerns.detect_conflicts([conv, dec], "main")
        flag = next(c for c in found if "convention" in c["content"].lower())
        self.assertEqual(flag.get("references"), [conv["id"]])

    def test_stale_question_concern_references_question(self):
        """Flag concern references the stale question id (WEAK link)."""
        q = make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        found = concerns.detect_conflicts(
            [q, *filler], "main", file_path="/tmp/x.ts", cwd="/tmp"
        )
        flag = next(c for c in found if "stale" in c["content"].lower())
        self.assertEqual(flag.get("references"), [q["id"]])

    def test_superseded_decision_concern_references_prior_decision(self):
        """Flag concern references the older (superseded) decision id."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        found = concerns.detect_conflicts([d1, d2], "main")
        flag = next(c for c in found if "superseded" in c["content"].lower())
        self.assertEqual(flag.get("references"), [d1["id"]])

    def test_overlapping_working_on_concern_has_no_references(self):
        """Pattern 1 references an agent_id, not an event id — no refs attached."""
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        flag = next(c for c in found if "overlap" in c["content"].lower())
        self.assertFalse(flag.get("references"))

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
        """Decisions on same topic separated by SESSION_END are NOT flagged."""
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        end = make_event(EVENT_TYPE_SESSION_END, content="session ended")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        found = concerns.detect_conflicts([d1, end, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_superseded_decision_same_session_still_fires(self):
        """Same-session decision pair on same topic still triggers concern."""
        # Prior-session decision is excluded from the window; in-session
        # pair (d1, d2) is what should fire.
        old_d = make_event(EVENT_TYPE_DECISION, topic="db", content="Use SQLite")
        end = make_event(EVENT_TYPE_SESSION_END, content="session ended")
        d1 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres")
        d2 = make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL")
        found = concerns.detect_conflicts([old_d, end, d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)
        self.assertIn(
            "Superseded decision: topic 'db'",
            superseded[0]["content"],
        )

    def test_superseded_decision_in_session_acceptance_honored(self):
        """In-window already_accepted_topics resolution still skips re-fire."""
        topic = "db"
        end = make_event(EVENT_TYPE_SESSION_END, content="session ended")
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
        events = [end, old_concern, resolution, d1, d2, d3]
        found = concerns.detect_conflicts(events, "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_superseded_decision_e2e_only_in_session_pairs_fire(self):
        """Cross+in-session sequences only flag in-session pairs."""
        # Session 1: stable topic decided once
        s1_a = make_event(EVENT_TYPE_DECISION, topic="topic-a", content="Pick A1")
        s1_b = make_event(EVENT_TYPE_DECISION, topic="topic-b", content="Pick B1")
        end1 = make_event(EVENT_TYPE_SESSION_END, content="end of s1")
        # Session 2: re-cite topic-a (cross-session re-cite, MUST NOT fire),
        # and topic-c gets two in-session decisions (MUST fire once).
        s2_a = make_event(EVENT_TYPE_DECISION, topic="topic-a", content="Pick A2")
        s2_c1 = make_event(EVENT_TYPE_DECISION, topic="topic-c", content="C1")
        s2_c2 = make_event(EVENT_TYPE_DECISION, topic="topic-c", content="C2")
        events = [s1_a, s1_b, end1, s2_a, s2_c1, s2_c2]
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

    def test_no_duplicate_assumption_contradicted(self):
        """Should not re-generate concern if one already exists for same conflict."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY, content="Actually GraphQL", references=[a["id"]]
        )
        existing_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Assumption contradicted: 'API is REST' "
            "contradicted by discovery 'Actually GraphQL'.",
        )
        events = [a, d, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        contradiction_concerns = [
            c for c in found if "contradict" in c["content"].lower()
        ]
        self.assertEqual(len(contradiction_concerns), 0)

    def test_no_duplicate_stale_question(self):
        """No duplicate concern for same stale question."""
        q = make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        existing_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Stale question: blocking question "
            f"(id {q['id']}) has not been answered.",
        )
        events = [q, *filler, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        stale_concerns = [c for c in found if "stale" in c["content"].lower()]
        self.assertEqual(len(stale_concerns), 0)

    def test_resolved_concern_allows_re_detection(self):
        """Resolved concerns should not suppress re-detection."""
        conv = make_event(
            EVENT_TYPE_CONVENTION, topic="naming", content="Use camelCase"
        )
        dec = make_event(EVENT_TYPE_DECISION, topic="naming", content="Use snake_case")
        concern_content = (
            "Convention violation: decision on 'naming' "
            "diverges from established convention."
        )
        old_concern = make_event(EVENT_TYPE_CONCERN, content=concern_content)
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Concern resolved",
            metadata={"resolves": [old_concern["id"]]},
        )
        events = [conv, dec, old_concern, resolution]
        found = concerns.detect_conflicts(events, "main")
        convention_concerns = [c for c in found if "convention" in c["content"].lower()]
        self.assertEqual(len(convention_concerns), 1)


if __name__ == "__main__":
    unittest.main()

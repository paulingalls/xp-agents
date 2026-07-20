#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — pattern 2: assumption contradicted.

Split from test_common_conflicts.py (pure move, no test-body edits).
Sibling patterns: overlap (1), convention (3), stale_question (4),
superseded (5) each live in their own test_common_conflicts_<pattern>.py.
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
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_STATUS,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_SUPERSEDES,
)


class TestDetectConflictsCommon(_HookTestCase):
    def test_without_file_path_runs_other_patterns(self):
        """Patterns 2-5 still run when file_path=None."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY, content="Actually GraphQL", references=[a["id"]]
        )
        found = concerns.detect_conflicts([a, d], "main")
        self.assertTrue(any("contradict" in c["content"].lower() for c in found))

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
        """Assumption contradicted concern must stay within the concern budget
        (read from the schema below, so a budget change cannot strand it)."""
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

    def test_resolved_assumption_contradiction_not_reraised(self):
        """A resolved contradiction stops re-firing — the events are immutable,
        so re-raising (and escalating) every scan is pure noise. Mirrors the
        superseded-decision `already_accepted_topics` suppression: a prior
        RESOLVED concern referencing the assumption marks it acknowledged."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="alias_run splits cleanly")
        prior = make_event(
            EVENT_TYPE_CONCERN,
            content="Assumption contradicted: 'alias_run...' — by discovery.",
            references=[a["id"]],
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Triage: dropped — superseded by the discovery",
            working_on=[],
            metadata={METADATA_KEY_RESOLVES: [prior["id"]]},
        )
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Supersedes the assumption: never shipped",
            references=[a["id"]],
        )
        found = concerns.detect_conflicts([a, prior, resolver, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(
            len(contradicts),
            0,
            f"resolved contradiction must not re-raise, got {len(contradicts)}",
        )

    def test_resolved_multi_ref_contradiction_not_reraised(self):
        """A resolved contradiction whose concern references the assumption
        ALONGSIDE other ids still marks the assumption acknowledged.

        Guards the flat resolved-ref-id set: a whole-set tuple keyed on
        (assumption, extra) would never match the single-assumption probe,
        re-firing the exact noise this suppression removes."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="alias_run splits cleanly")
        other = make_event(EVENT_TYPE_DISCOVERY, content="unrelated context")
        prior = make_event(
            EVENT_TYPE_CONCERN,
            content="Assumption contradicted: 'alias_run...' — by discovery.",
            references=[a["id"], other["id"]],
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Triage: dropped — superseded by the discovery",
            working_on=[],
            metadata={METADATA_KEY_RESOLVES: [prior["id"]]},
        )
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Supersedes the assumption: never shipped",
            references=[a["id"]],
        )
        found = concerns.detect_conflicts([a, other, prior, resolver, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(
            len(contradicts),
            0,
            "multi-ref resolved contradiction must mark the assumption "
            f"acknowledged, got {len(contradicts)}",
        )

    def test_empty_string_in_resolves_does_not_blanket_suppress(self):
        """A discovery with metadata.resolves=[''] must NOT suppress the
        contradiction — empty-string startswith-matches everything, which
        would silently mute a real conflict."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata={METADATA_KEY_RESOLVES: [""]},
        )
        found = concerns.detect_conflicts([a, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(len(contradicts), 1)

    def test_supersedes_metadata_on_discovery_skips_contradiction(self):
        """A discovery that structurally declares metadata.supersedes of the
        assumption never raises the contradiction — supersession is the
        intended forward mechanism, not an unresolved conflict."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL — supersedes the REST assumption",
            references=[a["id"]],
            metadata={METADATA_KEY_SUPERSEDES: [a["id"]]},
        )
        found = concerns.detect_conflicts([a, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(len(contradicts), 0)

    def test_resolves_metadata_on_discovery_skips_contradiction(self):
        """Symmetric with supersedes: metadata.resolves on the discovery is a
        STRONG link that cascade-closes the assumption, so re-flagging it as an
        open contradiction would contradict the link hierarchy."""
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY,
            content="Actually GraphQL",
            references=[a["id"]],
            metadata={METADATA_KEY_RESOLVES: [a["id"]]},
        )
        found = concerns.detect_conflicts([a, d], "main")
        contradicts = [c for c in found if "contradict" in c["content"].lower()]
        self.assertEqual(len(contradicts), 0)

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


if __name__ == "__main__":
    unittest.main()

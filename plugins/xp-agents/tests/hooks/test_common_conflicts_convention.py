#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — pattern 3: convention violation.

Split from test_common_conflicts.py (pure move, no test-body edits).
Sibling patterns: overlap (1), assumption (2), stale_question (4),
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
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)


class TestDetectConflictsCommon(_HookTestCase):
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

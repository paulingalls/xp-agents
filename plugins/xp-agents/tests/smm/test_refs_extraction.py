#!/usr/bin/env python3
"""Tests for [refs: id1, id2] suffix extraction at event-construction time.

Both event-construction entry points must consume the suffix:
  - event_builder.build_event(args)  ← shell append.sh path
  - _common.make_event(type, agent, content, **extra)  ← Python direct path

The extraction strips the trailing `[refs: ...]` token from content and routes
the valid 12-hex IDs by EVIDENCE:
  - closing event (terminal disposition) → metadata.resolves (the STRONG
    closure channel; the target is marked resolved)
  - every other event (adoption, deferral, plain prose) → top-level
    `references` (a WEAK, non-closing link)

Recording that you took work on must not close the guard that verifies it, so
only an event that actually carries a terminal disposition may close its target.
An explicit caller-supplied metadata.resolves is NEVER stripped or rewritten —
the routing decides only where the SUFFIX-derived ids land.
"""

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import resolution
from event_builder import build_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import (
    DISPOSITION_DEFERRED,
    DISPOSITION_DROPPED,
    DISPOSITION_WONT_FIX,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_RESOLVES,
)


def _ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace with all build_event-recognized fields defaulted to
    None / falsy, then override via kwargs."""
    defaults = {
        "type": EVENT_TYPE_DECISION,
        "agent": "main",
        "content": "",
        "references": None,
        "metadata": None,
        "topic": None,
        "priority": None,
        "severity": None,
        "files": None,
        "working_on": None,
        "intent_status": None,
        "duration_seconds": None,
        "event_count": None,
        "unresolved_items": None,
        "keep": None,
        "fix": None,
        "try_items": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestBuildEventRefsExtraction(unittest.TestCase):
    """event_builder.build_event must extract the [refs: ...] suffix and route
    the extracted IDs to references (intent) or metadata.resolves (closing)."""

    def test_extracts_refs_suffix_into_references(self):
        event = build_event(
            _ns(content="adopting Try foo bar [refs: abc123def456]", topic="t")
        )
        self.assertEqual(event["content"], "adopting Try foo bar")
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertNotIn("metadata", event)

    def test_explicit_metadata_resolves_survives_on_intent_event(self):
        """HARD RULE: a caller-declared closure is never stripped or rewritten.
        Suffix ids still land in references — the two channels coexist."""
        event = build_event(
            _ns(
                content="adopting [refs: bbbbbbbbbbbb]",
                topic="t",
                metadata='{"resolves": ["aaaaaaaaaaaa"]}',
            )
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])
        self.assertEqual(event["references"], ["bbbbbbbbbbbb"])

    def test_unions_explicit_references_with_suffix(self):
        event = build_event(
            _ns(
                content="adopting [refs: bbbbbbbbbbbb]",
                topic="t",
                references='["aaaaaaaaaaaa"]',
            )
        )
        self.assertEqual(event["references"], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])

    def test_does_not_duplicate_ids_already_in_references(self):
        event = build_event(
            _ns(
                content="adopting [refs: aaaaaaaaaaaa]",
                topic="t",
                references='["aaaaaaaaaaaa"]',
            )
        )
        self.assertEqual(event["references"], ["aaaaaaaaaaaa"])

    def test_ignores_bare_hex_in_content_without_refs_wrapper(self):
        event = build_event(
            _ns(content="see commit abc123def456 for context", topic="t")
        )
        self.assertEqual(event["content"], "see commit abc123def456 for context")
        self.assertNotIn("metadata", event)
        self.assertNotIn("references", event)

    def test_idempotent_when_no_suffix(self):
        event = build_event(_ns(content="just a regular content line", topic="t"))
        self.assertEqual(event["content"], "just a regular content line")
        self.assertNotIn("metadata", event)
        self.assertNotIn("references", event)

    def test_drops_malformed_tokens_keeps_valid(self):
        event = build_event(
            _ns(content="adopting [refs: not-hex, abc123def456]", topic="t")
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(event["references"], ["abc123def456"])

    def test_extracts_multiple_valid_ids(self):
        event = build_event(
            _ns(content="adopting [refs: aaaaaaaaaaaa, bbbbbbbbbbbb]", topic="t")
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(event["references"], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])

    def test_deferral_is_intent_not_closure(self):
        """disposition=deferred is NOT terminal — a deferral records intent."""
        event = build_event(
            _ns(
                type=EVENT_TYPE_STATUS,
                content="carrying this Try [refs: aaaaaaaaaaaa]",
                metadata=f'{{"{METADATA_KEY_DISPOSITION}": "{DISPOSITION_DEFERRED}"}}',
            )
        )
        self.assertEqual(event["references"], ["aaaaaaaaaaaa"])
        self.assertNotIn(METADATA_KEY_RESOLVES, event["metadata"])


class TestBuildEventClosingEvents(unittest.TestCase):
    """A terminal disposition IS the evidence of closure: suffix ids land in
    metadata.resolves exactly as they did before the routing split."""

    def test_dropped_preserves_non_resolves_metadata_keys(self):
        event = build_event(
            _ns(
                type=EVENT_TYPE_STATUS,
                content="dropped [refs: aaaaaaaaaaaa]",
                metadata=f'{{"{METADATA_KEY_DISPOSITION}": "{DISPOSITION_DROPPED}"}}',
            )
        )
        self.assertEqual(event["metadata"][METADATA_KEY_DISPOSITION], "dropped")
        self.assertEqual(event["metadata"][METADATA_KEY_RESOLVES], ["aaaaaaaaaaaa"])
        self.assertNotIn("references", event)

    def test_wont_fix_closes_like_dropped(self):
        """The predicate is terminal-disposition, not `== dropped`. wont_fix is
        already terminal at question close; it closes here too."""
        event = build_event(
            _ns(
                type=EVENT_TYPE_STATUS,
                content="closing unanswered [refs: aaaaaaaaaaaa]",
                metadata=f'{{"{METADATA_KEY_DISPOSITION}": "{DISPOSITION_WONT_FIX}"}}',
            )
        )
        self.assertEqual(event["metadata"][METADATA_KEY_RESOLVES], ["aaaaaaaaaaaa"])
        self.assertNotIn("references", event)

    def test_dropped_dedupes_against_explicit_resolves(self):
        event = build_event(
            _ns(
                type=EVENT_TYPE_STATUS,
                content="dropped [refs: aaaaaaaaaaaa]",
                metadata=(
                    f'{{"{METADATA_KEY_DISPOSITION}": "{DISPOSITION_DROPPED}", '
                    f'"{METADATA_KEY_RESOLVES}": ["aaaaaaaaaaaa"]}}'
                ),
            )
        )
        self.assertEqual(event["metadata"][METADATA_KEY_RESOLVES], ["aaaaaaaaaaaa"])


class TestMakeEventRefsExtraction(unittest.TestCase):
    """_common.make_event must route the [refs: ...] suffix the same way
    build_event does — one extractor, both entry points."""

    def test_extracts_refs_suffix_into_references(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting Try foo bar [refs: abc123def456]",
            topic="t",
        )
        self.assertEqual(event["content"], "adopting Try foo bar")
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertNotIn("metadata", event)

    def test_explicit_metadata_resolves_survives_on_intent_event(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting [refs: bbbbbbbbbbbb]",
            topic="t",
            metadata={METADATA_KEY_RESOLVES: ["aaaaaaaaaaaa"]},
        )
        self.assertEqual(event["metadata"][METADATA_KEY_RESOLVES], ["aaaaaaaaaaaa"])
        self.assertEqual(event["references"], ["bbbbbbbbbbbb"])

    def test_unions_explicit_references_with_suffix(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting [refs: bbbbbbbbbbbb]",
            topic="t",
            references=["aaaaaaaaaaaa"],
        )
        self.assertEqual(event["references"], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])

    def test_does_not_mutate_caller_reference_list(self):
        """Defensive copy: a list the caller shares across events must not grow."""
        shared = ["aaaaaaaaaaaa"]
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting [refs: bbbbbbbbbbbb]",
            topic="t",
            references=shared,
        )
        self.assertEqual(shared, ["aaaaaaaaaaaa"])
        self.assertEqual(event["references"], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])

    def test_ignores_bare_hex_in_content_without_refs_wrapper(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "see commit abc123def456 for context",
            topic="t",
        )
        self.assertEqual(event["content"], "see commit abc123def456 for context")
        self.assertNotIn("metadata", event)
        self.assertNotIn("references", event)

    def test_idempotent_when_no_suffix(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION, "main", "just regular content", topic="t"
        )
        self.assertEqual(event["content"], "just regular content")
        self.assertNotIn("metadata", event)
        self.assertNotIn("references", event)

    def test_drops_malformed_tokens_keeps_valid(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting [refs: not-hex, abc123def456]",
            topic="t",
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(event["references"], ["abc123def456"])

    def test_status_with_dropped_disposition_and_refs(self):
        """The work_selection_decide.py drop path: status + dropped + refs."""
        event = _common.make_event(
            EVENT_TYPE_STATUS,
            "xp-work-selection",
            "Dropped Try [refs: aaaaaaaaaaaa]",
            working_on=[],
            metadata={METADATA_KEY_DISPOSITION: DISPOSITION_DROPPED},
        )
        self.assertEqual(event["content"], "Dropped Try")
        self.assertEqual(event["metadata"][METADATA_KEY_DISPOSITION], "dropped")
        self.assertEqual(event["metadata"][METADATA_KEY_RESOLVES], ["aaaaaaaaaaaa"])
        self.assertNotIn("references", event)


class TestCascadeDirection(unittest.TestCase):
    """`references` is not a blank field — it feeds the WEAK cascade in
    resolution.compute_resolutions. Pin the DIRECTION: closure flows from a
    resolved target TO the event that references it, never backwards. An
    adopting event must leave the concern it names OPEN — that is the whole
    point of routing intent away from metadata.resolves.
    """

    def _concern(self) -> dict:
        return {
            "id": "aaaaaaaaaaaa",
            "ts": "2026-01-01T00:00:00+00:00",
            "type": EVENT_TYPE_CONCERN,
            "agent_id": "main",
            "content": "an open concern",
            "severity": "high",
            "schema_version": 1,
        }

    def test_adopting_decision_leaves_referenced_concern_open(self):
        concern = self._concern()
        adoption = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            f"Adopting the fix [refs: {concern['id']}]",
            topic="retro-try-fix-it",
        )
        self.assertEqual(adoption["references"], [concern["id"]])
        resolutions = resolution.compute_resolutions([concern, adoption])
        self.assertNotIn(concern["id"], resolutions["resolved_concern_ids"])

    def test_dropping_status_closes_referenced_concern(self):
        """The falsifiable half: a terminal disposition still closes."""
        concern = self._concern()
        drop = _common.make_event(
            EVENT_TYPE_STATUS,
            "main",
            f"Dropping it [refs: {concern['id']}]",
            working_on=[],
            metadata={METADATA_KEY_DISPOSITION: DISPOSITION_DROPPED},
        )
        resolutions = resolution.compute_resolutions([concern, drop])
        self.assertIn(concern["id"], resolutions["resolved_concern_ids"])

    def test_adopting_decision_itself_closes_when_its_target_closes(self):
        """The OTHER half of the cascade, and the reason `references` was not a
        blank field to move into: `decision` is a RELAYING bucket. Once the
        adopted concern closes, the adopting decision — which now names it in
        `references` — is itself marked resolved, and relays that closure on to
        anything referencing the decision.

        Pinned deliberately, not accepted accidentally. Two consequences ride on
        it: compact.py drops resolved decisions from the retained set (so the
        `retro-try-<slug>` decision, and the stable topic the superseded-decision
        detector keys on, ages out early), and a flag event pointing at the
        decision auto-closes with it. Before the routing split an adoption
        carried no `references` at all and could never be a cascade target, so
        this behavior is NEW. If a future change to resolution.py demotes
        `decision` to a non-relaying bucket, this test is the tripwire.
        """
        concern = self._concern()
        adoption = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            f"Adopting the fix [refs: {concern['id']}]",
            topic="retro-try-fix-it",
        )
        landed = _common.make_event(
            EVENT_TYPE_STATUS,
            "main",
            "the work landed",
            working_on=[],
            metadata={METADATA_KEY_RESOLVES: [concern["id"]]},
        )
        flag = _common.make_event(
            EVENT_TYPE_CONCERN,
            "main",
            "flag raised against the adoption decision",
            severity="low",
            references=[adoption["id"]],
        )
        resolutions = resolution.compute_resolutions([concern, adoption, landed, flag])
        self.assertIn(concern["id"], resolutions["resolved_concern_ids"])
        # Level 1: the adopting decision cascade-closes with its target.
        self.assertIn(adoption["id"], resolutions["resolved_decision_ids"])
        # Level 2: `decision` relays, so the flag against it closes too.
        self.assertIn(flag["id"], resolutions["resolved_concern_ids"])


if __name__ == "__main__":
    unittest.main()

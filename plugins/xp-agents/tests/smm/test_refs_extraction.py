#!/usr/bin/env python3
"""Tests for [refs: id1, id2] suffix extraction at event-construction time.

Both event-construction entry points must consume the suffix:
  - event_builder.build_event(args)  ← shell append.sh path
  - _common.make_event(type, agent, content, **extra)  ← Python direct path

The extraction strips the trailing `[refs: ...]` token from content and
appends valid 12-hex IDs to metadata.resolves (unioning with any explicit
metadata.resolves the caller passed). This lets every event writer wire
metadata.resolves via a documented content convention without having to
craft metadata JSON by hand.
"""

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
from event_builder import build_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_STATUS


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
    """event_builder.build_event must extract [refs: ...] suffix and union
    extracted IDs into metadata.resolves before returning."""

    def test_extracts_refs_suffix_into_metadata_resolves(self):
        event = build_event(
            _ns(content="adopting Try foo bar [refs: abc123def456]", topic="t")
        )
        self.assertEqual(event["content"], "adopting Try foo bar")
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])

    def test_unions_explicit_metadata_resolves_with_suffix(self):
        event = build_event(
            _ns(
                content="adopting [refs: bbbbbbbbbbbb]",
                topic="t",
                metadata='{"resolves": ["aaaaaaaaaaaa"]}',
            )
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(
            event["metadata"]["resolves"], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
        )

    def test_does_not_duplicate_ids_already_in_metadata(self):
        event = build_event(
            _ns(
                content="adopting [refs: aaaaaaaaaaaa]",
                topic="t",
                metadata='{"resolves": ["aaaaaaaaaaaa"]}',
            )
        )
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])

    def test_ignores_bare_hex_in_content_without_refs_wrapper(self):
        event = build_event(
            _ns(content="see commit abc123def456 for context", topic="t")
        )
        self.assertEqual(event["content"], "see commit abc123def456 for context")
        self.assertNotIn("metadata", event)

    def test_idempotent_when_no_suffix(self):
        event = build_event(_ns(content="just a regular content line", topic="t"))
        self.assertEqual(event["content"], "just a regular content line")
        self.assertNotIn("metadata", event)

    def test_drops_malformed_tokens_keeps_valid(self):
        event = build_event(
            _ns(content="adopting [refs: not-hex, abc123def456]", topic="t")
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])

    def test_extracts_multiple_valid_ids(self):
        event = build_event(
            _ns(content="adopting [refs: aaaaaaaaaaaa, bbbbbbbbbbbb]", topic="t")
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(
            event["metadata"]["resolves"], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
        )

    def test_preserves_non_resolves_metadata_keys(self):
        event = build_event(
            _ns(
                type="status",
                content="dropped [refs: aaaaaaaaaaaa]",
                metadata='{"disposition": "dropped"}',
            )
        )
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])


class TestMakeEventRefsExtraction(unittest.TestCase):
    """_common.make_event must extract [refs: ...] suffix and union extracted
    IDs into metadata.resolves the same way build_event does."""

    def test_extracts_refs_suffix_into_metadata_resolves(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting Try foo bar [refs: abc123def456]",
            topic="t",
        )
        self.assertEqual(event["content"], "adopting Try foo bar")
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])

    def test_unions_explicit_metadata_resolves_with_suffix(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting [refs: bbbbbbbbbbbb]",
            topic="t",
            metadata={"resolves": ["aaaaaaaaaaaa"]},
        )
        self.assertEqual(
            event["metadata"]["resolves"], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
        )

    def test_ignores_bare_hex_in_content_without_refs_wrapper(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "see commit abc123def456 for context",
            topic="t",
        )
        self.assertEqual(event["content"], "see commit abc123def456 for context")
        self.assertNotIn("metadata", event)

    def test_idempotent_when_no_suffix(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION, "main", "just regular content", topic="t"
        )
        self.assertEqual(event["content"], "just regular content")
        self.assertNotIn("metadata", event)

    def test_drops_malformed_tokens_keeps_valid(self):
        event = _common.make_event(
            EVENT_TYPE_DECISION,
            "main",
            "adopting [refs: not-hex, abc123def456]",
            topic="t",
        )
        self.assertEqual(event["content"], "adopting")
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])

    def test_status_with_disposition_and_refs(self):
        """The work_selection_decide.py path: status + disposition + refs."""
        event = _common.make_event(
            EVENT_TYPE_STATUS,
            "xp-work-selection",
            "Dropped Try [refs: aaaaaaaaaaaa]",
            working_on=[],
            metadata={"disposition": "dropped"},
        )
        self.assertEqual(event["content"], "Dropped Try")
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])


if __name__ == "__main__":
    unittest.main()

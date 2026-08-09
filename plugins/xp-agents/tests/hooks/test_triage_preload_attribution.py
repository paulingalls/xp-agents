#!/usr/bin/env python3
"""Run-attribution suffix on the work-selection triage preload.

story-001: bash_post_tool now stamps cwd/test_failed/test_count on the
test-failure concern (test_bash_test_concern_metadata.py). This pins the
render leg: one helper called from both the full and digest line forms, so
they cannot drift — matching `_intent_suffix`'s own shape.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import triage_preload
from conftest import make_event
from event_schema import DISPOSITION_DEFERRED, EVENT_TYPE_CONCERN


def _concern_with_attribution(**metadata_overrides) -> dict:
    metadata = {
        "test_failed": 2,
        "test_count": 23,
        "cwd": "~/worktree-story-001-x",
    }
    metadata.update(metadata_overrides)
    return make_event(
        EVENT_TYPE_CONCERN,
        content="Test failures detected: 2 failed (pytest)",
        severity="high",
        ts="2026-01-01T00:00:00+00:00",
        metadata=metadata,
    )


class TestFullLineAttribution(unittest.TestCase):
    def test_renders_failed_total_and_checkout(self):
        item = _concern_with_attribution()
        result = triage_preload.format_triage_section(
            "Open Concerns", [item], ["2026-02-01T00:00:00+00:00"]
        )
        self.assertIn("[2/23 failed in worktree-story-001-x]", result)

    def test_absent_keys_renders_byte_identical_to_today(self):
        item = make_event(
            EVENT_TYPE_CONCERN,
            content="Data loss: unbounded queue",
            severity="high",
            ts="2026-01-01T00:00:00+00:00",
            metadata={},
        )
        with_metadata = triage_preload.format_triage_section(
            "Open Concerns", [item], ["2026-02-01T00:00:00+00:00"]
        )
        item_no_metadata_key = dict(item)
        del item_no_metadata_key["metadata"]
        without_metadata = triage_preload.format_triage_section(
            "Open Concerns", [item_no_metadata_key], ["2026-02-01T00:00:00+00:00"]
        )
        self.assertEqual(with_metadata, without_metadata)
        self.assertNotIn("failed in", with_metadata)

    def test_cwd_missing_omits_suffix_entirely(self):
        item = _concern_with_attribution(cwd=None)
        del item["metadata"]["cwd"]
        result = triage_preload.format_triage_section(
            "Open Concerns", [item], ["2026-02-01T00:00:00+00:00"]
        )
        self.assertNotIn("failed in", result)


class TestDigestLineAttribution(unittest.TestCase):
    def test_renders_failed_total_and_checkout(self):
        # severity must NOT be high: _digests exempts high-severity items
        # from the shorter form (see triage_preload._digests).
        item = _concern_with_attribution()
        item["severity"] = "medium"
        intents = {item["id"]: {"intent": DISPOSITION_DEFERRED, "defer_count": 1}}
        result = triage_preload.format_triage_section(
            "Open Concerns",
            [item],
            ["2026-02-01T00:00:00+00:00"],
            intents=intents,
        )
        self.assertIn("Deferred earlier", result)
        self.assertIn("[2/23 failed in worktree-story-001-x]", result)


if __name__ == "__main__":
    unittest.main()

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


class TestDegradedAttribution(unittest.TestCase):
    """story-002: bash_failure knows less, and what it knows still renders.

    Requiring all three keys made the degraded producer's concerns render
    NOTHING — the run with no counts is exactly the one a reader most needs
    attributed to a checkout. `cwd` is the single gate; the counts only
    choose which form.
    """

    def _render(self, item: dict) -> str:
        return triage_preload.format_triage_section(
            "Open Concerns", [item], ["2026-02-01T00:00:00+00:00"]
        )

    def test_failed_without_total_renders_the_count_alone(self):
        item = _concern_with_attribution()
        del item["metadata"]["test_count"]
        self.assertIn("[2 failed in worktree-story-001-x]", self._render(item))

    def test_checkout_alone_still_renders(self):
        item = _concern_with_attribution()
        del item["metadata"]["test_count"]
        del item["metadata"]["test_failed"]
        self.assertIn("[in worktree-story-001-x]", self._render(item))

    def test_full_counts_form_is_unchanged(self):
        self.assertIn(
            "[2/23 failed in worktree-story-001-x]",
            self._render(_concern_with_attribution()),
        )

    def test_total_without_failed_does_not_invent_a_form(self):
        # Neither producer creates this shape; it must not render a bare
        # denominator that reads like a result.
        item = _concern_with_attribution()
        del item["metadata"]["test_failed"]
        self.assertIn("[in worktree-story-001-x]", self._render(item))


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

#!/usr/bin/env python3
"""Tests for work_selection_decide.py — triage subcommands (debt/concern/
question triage).

Split from test_work_selection_decide.py to stay under the file-size budget.
Shared base TestCase (`_DecideTestCase`) lives in
_work_selection_decide_helpers.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

from _work_selection_decide_helpers import _DecideTestCase
from conftest import make_event
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_DEBT, EVENT_TYPE_STATUS


class TestTriageAdopt(_DecideTestCase):
    """triage-adopt: status event, disposition=adopted, references=[id].

    Adopting an item means taking the work on. It must NOT close the item —
    the item closes when the work lands. This is the headline defect the
    routing exists to fix: an adopted-but-unfixed debt used to launder itself
    into the curated pillars as "confirmed fixed".
    """

    def test_creates_status_with_references_not_resolves(self):
        self.mod.run(
            action="triage-adopt",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertNotIn("resolves", event["metadata"])
        self.assertEqual(event["metadata"]["disposition"], "adopted")
        self.assertEqual(event["working_on"], [])

    def test_adopted_concern_stays_open(self):
        """End-to-end against the resolver: the adopted concern is NOT closed."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="secret scan misses .env files",
            severity="high",
            files=["scan.py"],
        )
        from _common import append_safe

        append_safe(self.smm_dir, concern)
        self.mod.run(
            action="triage-adopt",
            smm_dir=self.smm_dir,
            content="",
            event_id=concern["id"],
        )
        from resolution import compute_resolutions

        resolutions = compute_resolutions(self._read_events())
        self.assertNotIn(concern["id"], resolutions["resolved_concern_ids"])
        self.assertEqual(self._last_event()["references"], [concern["id"]])

    def test_content_includes_short_id(self):
        self.mod.run(
            action="triage-adopt",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertIn("abc123de", event["content"])


class TestTriageDefer(_DecideTestCase):
    """triage-defer: status event, disposition=deferred, target in `references`.

    The link is the reversal: a deferral used to record NO link at all, on the
    reasoning that carrying an item says nothing about it. But an unlinked defer
    is undetectable by construction — it is the reason the ~20 legacy
    triage-defers on disk can never be recovered, and the reason a deferred debt
    was re-offered bare at every kickoff, forever. Linking is not closing: the
    debt must stay OPEN, which the second test asserts.
    """

    def test_creates_status_with_references_not_resolves(self):
        self.mod.run(
            action="triage-defer",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertEqual(event["metadata"]["action"], "triage_disposition")
        self.assertNotIn("resolves", event["metadata"])
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertEqual(event["working_on"], [])

    def test_deferred_debt_stays_open(self):
        """Linking is NOT closing — a `status` lands in `other_resolutions`,
        which does not relay closure. The debt must still be offered."""
        import resolution

        debt = make_event(EVENT_TYPE_DEBT, content="A debt to carry")
        self._write_events([debt])
        self.mod.run(
            action="triage-defer",
            smm_dir=self.smm_dir,
            content="",
            event_id=debt["id"],
        )
        resolutions = resolution.compute_resolutions(self._read_events())
        self.assertNotIn(debt["id"], resolution.collect_all_resolved_ids(resolutions))


class TestTriageDrop(_DecideTestCase):
    """triage-drop: status event, disposition=dropped, resolves=[id]."""

    def test_creates_status_with_resolves(self):
        self.mod.run(
            action="triage-drop",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])
        self.assertEqual(event["metadata"]["disposition"], "dropped")

    def test_content_includes_short_id(self):
        self.mod.run(
            action="triage-drop",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertIn("abc123de", event["content"])


class TestTriageEnrichment(_DecideTestCase):
    """Triage status content inlines a snippet of the resolved event's content
    so cross-session drop memory (retro_metrics.dropped_tries_recent) can match
    candidate Tries by topic, not just opaque event ids.
    """

    def _seed_concern(self, content: str) -> str:
        from event_schema import EVENT_TYPE_CONCERN

        concern = make_event(EVENT_TYPE_CONCERN, content=content)
        from _common import append_safe

        append_safe(self.smm_dir, concern)
        return concern["id"]

    def test_triage_drop_content_contains_target_snippet(self):
        target_id = self._seed_concern("namespace shape mismatch on encryption barrel")
        self.mod.run(
            action="triage-drop",
            smm_dir=self.smm_dir,
            content="",
            event_id=target_id,
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertIn(
            "namespace shape",
            event["content"],
            f"triage-drop must inline target snippet, got: {event['content']!r}",
        )
        self.assertLessEqual(
            len(event["content"]),
            200,
            "triage status content must respect 200-char status budget",
        )

    def test_triage_defer_content_contains_target_snippet(self):
        target_id = self._seed_concern("audit writer needs INSERT-only role")
        self.mod.run(
            action="triage-defer",
            smm_dir=self.smm_dir,
            content="",
            event_id=target_id,
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertIn("audit writer", event["content"])
        # Existing deferred-path contract: no metadata.resolves on defers.
        self.assertNotIn("resolves", event["metadata"])

    def test_triage_falls_back_to_terse_form_when_target_missing(self):
        # No seed — target lookup will fail (event_id is well-formed but
        # references no event). Impl must degrade to the prior "Triage:
        # disposition <short-id>" terse form rather than fabricate content
        # or crash.
        self.mod.run(
            action="triage-drop",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertIn("abc123de", event["content"])
        # No em-dash separator when there's no snippet to inline.
        self.assertNotIn("—", event["content"])

    def test_enriched_content_visible_in_dropped_tries_recent(self):
        """End-to-end: enriched triage-drop survives retro-digest extraction.

        Pins the consumer contract for xp-retrospective.md:28 — the LLM
        topic-match safety net must see a usable snippet, not just an
        opaque event id. Folded from former Story 3 backstop.
        """
        target_id = self._seed_concern("namespace shape mismatch on encryption barrel")
        self.mod.run(
            action="triage-drop",
            smm_dir=self.smm_dir,
            content="",
            event_id=target_id,
        )
        from retro_metrics import _collect_dropped_tries_recent

        drops = _collect_dropped_tries_recent(self._read_events(), limit=10)
        self.assertGreaterEqual(len(drops), 1)
        snippets = [d["content"] for d in drops]
        self.assertTrue(
            any("namespace shape" in s for s in snippets),
            f"expected an enriched snippet in dropped_tries_recent, got: {snippets!r}",
        )


class TestTriageCliArgparse(_DecideTestCase):
    """End-to-end argparse for triage subcommands."""

    def test_triage_adopt_persists_event(self):
        code = self._run_main(
            [
                "triage-adopt",
                "--smm-dir",
                str(self.smm_dir),
                "--event-id",
                "abc123def456",
            ]
        )
        self.assertEqual(code, 0)
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertNotIn("resolves", event["metadata"])

    def test_triage_defer_persists_event(self):
        code = self._run_main(
            [
                "triage-defer",
                "--smm-dir",
                str(self.smm_dir),
                "--event-id",
                "abc123def456",
            ]
        )
        self.assertEqual(code, 0)
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "deferred")

    def test_triage_drop_persists_event(self):
        code = self._run_main(
            [
                "triage-drop",
                "--smm-dir",
                str(self.smm_dir),
                "--event-id",
                "abc123def456",
            ]
        )
        self.assertEqual(code, 0)
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])


if __name__ == "__main__":
    unittest.main()

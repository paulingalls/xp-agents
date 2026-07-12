#!/usr/bin/env python3
"""Tests for work_selection_decide.py — the Try-item adopt/defer/drop helper.

The helper extracts `[refs: ...]` from retro Try text and appends a decision
or status event with the refs routed by evidence: a closing event (terminal
disposition) populates metadata.resolves; an intent event (adoption, deferral)
populates top-level `references`. Replaces LLM-crafted --metadata JSON
discipline with code.
"""

import os
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

import work_selection_decide
from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)
from work_selection_filters import _FORCE_CLOSE_THRESHOLD

# The exact metadata every retro-lane disposition now carries. Spelled out once:
# a test that asserts the whole dict is what catches a lane tag going missing,
# and a missing lane tag silently disarms the FORCE-CLOSE gate.
_RETRO_DEFERRED = {"action": "retro_try_disposition", "disposition": "deferred"}
_RETRO_DROPPED = {"action": "retro_try_disposition", "disposition": "dropped"}


class _DecideTestCase(_HookTestCase):
    """Shared setup: expose mod + _last_event() + _run_main()."""

    def setUp(self):
        super().setUp()
        self.mod = work_selection_decide
        # Chdir out of any worktree path so agent_id resolves to "main".
        self._prev_cwd = os.getcwd()
        os.chdir(self.smm_dir)

    def tearDown(self):
        os.chdir(self._prev_cwd)
        super().tearDown()

    def _last_event(self) -> dict:
        events = self._read_events()
        self.assertGreater(len(events), 0, "expected at least one event")
        return events[-1]

    def _run_main(self, argv: list[str]) -> int:
        old_argv = sys.argv
        sys.argv = ["work_selection_decide.py", *argv]
        try:
            self.mod.main()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
        finally:
            sys.argv = old_argv


class TestAdopt(_DecideTestCase):
    """adopt subcommand: emits decision event with topic + optional references.

    Adoption records intent, not resolution — the refs land in the WEAK
    `references` field so taking the work on cannot close the item that
    verifies it.
    """

    def test_adopt_with_refs_populates_references(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Commit after green [refs: abc123def456, 7df84bb18a49]",
            topic="retro-try-commit-after-green",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_DECISION)
        self.assertEqual(event["topic"], "retro-try-commit-after-green")
        self.assertEqual(event["references"], ["abc123def456", "7df84bb18a49"])
        self.assertNotIn("resolves", event.get("metadata", {}))

    def test_adopt_with_refs_strips_suffix_from_content(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Commit after green [refs: abc123def456]",
            topic="retro-try-commit-after-green",
        )
        event = self._last_event()
        self.assertEqual(event["content"], "Commit after green")

    def test_adopt_without_refs_has_no_link_fields(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Refactor prep before add",
            topic="retro-try-refactor-first",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_DECISION)
        self.assertEqual(event["topic"], "retro-try-refactor-first")
        self.assertNotIn("resolves", event.get("metadata", {}))
        self.assertNotIn("references", event)
        self.assertEqual(event["content"], "Refactor prep before add")

    def test_adopt_emits_decision_event_type(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="A try",
            topic="retro-try-foo",
        )
        self.assertEqual(self._last_event()["type"], EVENT_TYPE_DECISION)

    def test_adopt_agent_id_is_resolved(self):
        """agent_id is teammate-resolved attribution per the agent-id-semantics
        ADR; the test cwd is a non-worktree tmpdir so it resolves to 'main'."""
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="A try",
            topic="retro-try-foo",
        )
        self.assertEqual(self._last_event()["agent_id"], "main")


class TestDefer(_DecideTestCase):
    """defer subcommand: status event, disposition=deferred, working_on=[].

    Deferral is intent (the Try is carried, not closed), so its refs land in
    `references` — deferred is not a terminal disposition.
    """

    def test_defer_with_refs_sets_references_and_disposition(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this [refs: abc123def456, 7df84bb18a49]",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["working_on"], [])
        self.assertEqual(event["references"], ["abc123def456", "7df84bb18a49"])
        self.assertEqual(event["metadata"], _RETRO_DEFERRED)

    def test_defer_overbudget_content_truncates_preserves_refs(self):
        """A Try whose prose exceeds the 200-char status budget defers
        successfully — content is truncated to the budget, refs preserved.

        Regression: defer used to raise "Content exceeds status budget" for a
        Try only a couple of chars over, making valid carried Tries
        un-deferrable through the normal path.
        """
        prose = "Implement a blocking pre-commit gate that " + "x" * 200
        self.assertGreater(len(prose), 200)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"{prose} [refs: abc123def456]",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertLessEqual(len(event["content"]), 200)
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertEqual(event["metadata"]["disposition"], "deferred")

    def test_defer_without_refs_has_only_disposition(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this with no refs",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"], _RETRO_DEFERRED)
        self.assertNotIn("references", event)
        self.assertEqual(event["working_on"], [])
        self.assertEqual(event["content"], "Defer this with no refs")

    def test_defer_strips_refs_suffix(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer [refs: abc123def456]",
        )
        self.assertEqual(self._last_event()["content"], "Defer")


class TestDrop(_DecideTestCase):
    """drop subcommand: status event, disposition=dropped, working_on=[]."""

    def test_drop_without_refs_has_only_dropped_disposition(self):
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content="Drop this forever",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"], _RETRO_DROPPED)
        self.assertEqual(event["working_on"], [])
        self.assertNotIn("resolves", event["metadata"])

    def test_drop_with_refs_sets_resolves_and_dropped(self):
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content="Drop it [refs: abc123def456]",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(
            event["metadata"], {**_RETRO_DROPPED, "resolves": ["abc123def456"]}
        )

    def test_drop_overbudget_content_truncates(self):
        """drop of an over-budget Try truncates to the status budget."""
        prose = "Drop this stale Try about " + "y" * 200
        self.assertGreater(len(prose), 200)
        self.mod.run(action="drop", smm_dir=self.smm_dir, content=prose)
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertLessEqual(len(event["content"]), 200)
        self.assertEqual(event["metadata"]["disposition"], "dropped")


class TestRefParsing(_DecideTestCase):
    """Regex + hex-filter edge cases."""

    def test_malformed_tokens_dropped_valid_kept(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Item [refs: not-hex, abc123def456, 42@#, short123]",
            topic="retro-try-filter",
        )
        event = self._last_event()
        self.assertEqual(event["references"], ["abc123def456"])

    def test_no_refs_suffix_leaves_content_untouched(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Plain content no refs",
            topic="retro-try-plain",
        )
        event = self._last_event()
        self.assertEqual(event["content"], "Plain content no refs")
        self.assertNotIn("references", event)

    def test_all_malformed_refs_treated_as_no_refs(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Item [refs: not-hex, 42@#]",
            topic="retro-try-nothing",
        )
        event = self._last_event()
        self.assertNotIn("references", event)

    def test_refs_with_only_whitespace_separator(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Item [refs: abc123def456 7df84bb18a49]",
            topic="retro-try-space",
        )
        event = self._last_event()
        self.assertEqual(event["references"], ["abc123def456", "7df84bb18a49"])

    def test_trailing_whitespace_after_refs_stripped(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Item text [refs: abc123def456]   ",
            topic="retro-try-ws",
        )
        self.assertEqual(self._last_event()["content"], "Item text")


class TestValidationRaises(_DecideTestCase):
    """Invalid events surface as errors rather than silent no-ops.

    `_common.append_safe` swallows schema-validation failures. The helper
    prints a success-looking event id even when nothing was written. Guard
    the contract by calling validate_event ourselves and raising.
    """

    def test_adopt_with_generic_topic_raises(self):
        """`retro-try-adopted` is explicitly rejected by the schema — the
        helper must not claim success when nothing was written."""
        with self.assertRaises(ValueError):
            self.mod.run(
                action="adopt",
                smm_dir=self.smm_dir,
                content="Something",
                topic="retro-try-adopted",
            )
        self.assertEqual(self._read_events(), [])

    def test_triage_without_event_id_raises(self):
        with self.assertRaises(ValueError):
            self.mod.run(
                action="triage-adopt",
                smm_dir=self.smm_dir,
                content="",
            )

    def test_triage_with_invalid_event_id_raises(self):
        with self.assertRaises(ValueError):
            self.mod.run(
                action="triage-adopt",
                smm_dir=self.smm_dir,
                content="",
                event_id="not-a-hex-id",
            )

    def test_unknown_action_raises(self):
        with self.assertRaises(ValueError):
            self.mod.run(
                action="bogus",
                smm_dir=self.smm_dir,
                content="x",
                topic="retro-try-x",
            )


class TestCliArgparse(_DecideTestCase):
    """End-to-end argparse behavior via main()."""

    def test_adopt_without_topic_exits_with_error(self):
        code = self._run_main(
            [
                "adopt",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Some try",
            ]
        )
        self.assertNotEqual(code, 0)

    def test_main_adopt_persists_event(self):
        code = self._run_main(
            [
                "adopt",
                "--smm-dir",
                str(self.smm_dir),
                "--topic",
                "retro-try-cli",
                "--content",
                "CLI try [refs: abc123def456]",
            ]
        )
        self.assertEqual(code, 0)
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_DECISION)
        self.assertEqual(event["references"], ["abc123def456"])

    def test_main_defer_persists_event(self):
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Defer [refs: abc123def456]",
            ]
        )
        self.assertEqual(code, 0)
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertEqual(event["metadata"], _RETRO_DEFERRED)


# ---------------------------------------------------------------------------
# Triage subcommands (debt/concern/question triage)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# FORCE-CLOSE gate — refuse plain defer when a Try has been deferred 3+ times.
# Carrying a Try across 3+ retros without adoption is dishonest.
# Gate fires on the 4th defer attempt; user must use a force flag.
# ---------------------------------------------------------------------------


class _ForceCloseTestCase(_DecideTestCase):
    """Helpers for seeding prior-defer history against a Try id.

    `link_field` selects how the seeded deferral names its Try:
      - "resolves"   → legacy metadata.resolves (every deferral already on
                       disk in a real SMM log carries this shape)
      - "references" → the new top-level field deferrals write from now on
    The gate must count BOTH, or migrating the writer silently resets every
    Try's deferral count to zero and disarms the gate on exactly the Tries it
    exists to catch.
    """

    def _seed_prior_defers(
        self, try_ref_id: str, count: int, link_field: str = "resolves"
    ) -> None:
        self._write_events(
            [self._defer_event(i, try_ref_id, link_field) for i in range(count)]
        )

    def _defer_event(self, index: int, try_ref_id: str, link_field: str) -> dict:
        event = {
            "id": f"{index:012x}",
            "ts": f"2026-01-{index + 1:02d}T00:00:00+00:00",
            "type": EVENT_TYPE_STATUS,
            "agent_id": "main",
            "content": f"Defer {index}",
            "schema_version": 1,
            "working_on": [],
            "metadata": {"disposition": "deferred"},
        }
        match link_field:
            case "resolves":
                event["metadata"]["resolves"] = [try_ref_id]
            case "references":
                event["references"] = [try_ref_id]
            case _:
                raise ValueError(f"unknown link_field: {link_field}")
        return event


class TestForceCloseGate(_ForceCloseTestCase):
    """Plain defer is allowed up to 2 prior defers, refused at 3+."""

    def test_zero_prior_defers_allowed(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this [refs: aaaaaaaaaaaa]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_two_prior_defers_allowed(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 2)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer again [refs: aaaaaaaaaaaa]",
        )
        # Last event is the new defer; the seeded 2 still precede.
        self.assertEqual(len(self._read_events()), 3)
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_three_prior_defers_plain_defer_refused(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Defer once more [refs: aaaaaaaaaaaa]",
            )
        msg = str(ctx.exception)
        self.assertIn("FORCE-CLOSE", msg)
        # The Try id is named so the user can find the offending item.
        self.assertIn("aaaaaaaa", msg)
        # No new event was written.
        self.assertEqual(len(self._read_events()), 3)

    def test_four_prior_defers_plain_defer_refused(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 4)
        with self.assertRaises(ValueError):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="And again [refs: aaaaaaaaaaaa]",
            )

    def test_no_refs_skips_gate(self):
        """No refs means nothing to count — defer always allowed."""
        # Seed unrelated history; without refs in content, gate can't link.
        self._seed_prior_defers("aaaaaaaaaaaa", 5)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer with no refs",
        )
        self.assertEqual(self._last_event()["metadata"], _RETRO_DEFERRED)

    def test_defers_for_other_try_dont_count(self):
        """Only defers whose resolves overlap with the current refs count."""
        self._seed_prior_defers("bbbbbbbbbbbb", 5)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Different Try [refs: aaaaaaaaaaaa]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")


class TestForceAdoptBreaksGate(_ForceCloseTestCase):
    """--force-adopt converts the gated defer into an adopt decision."""

    def test_force_adopt_at_threshold_writes_decision(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Adopt now [refs: aaaaaaaaaaaa]",
            force_adopt_topic="retro-try-finally-adopted",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_DECISION)
        self.assertEqual(event["topic"], "retro-try-finally-adopted")
        # Forced or not, an adoption is still intent — it links, it doesn't close.
        self.assertEqual(event["references"], ["aaaaaaaaaaaa"])
        self.assertNotIn("resolves", event.get("metadata", {}))
        self.assertEqual(event["content"], "Adopt now")


class TestForceDropBreaksGate(_ForceCloseTestCase):
    """--force-drop converts the gated defer into a drop status."""

    def test_force_drop_at_threshold_writes_dropped(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])


class TestForceDeferWithDateBreaksGate(_ForceCloseTestCase):
    """--force-defer-with-date defers but records a target date in metadata."""

    def test_force_defer_with_date_writes_defer_until(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Hold until [refs: aaaaaaaaaaaa]",
            force_defer_until="2026-09-01",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertEqual(event["metadata"]["defer_until"], "2026-09-01")
        self.assertEqual(event["references"], ["aaaaaaaaaaaa"])
        self.assertNotIn("resolves", event["metadata"])

    def test_force_defer_with_date_rejects_bad_date_format(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Hold until [refs: aaaaaaaaaaaa]",
                force_defer_until="next quarter",
            )

    def test_force_defer_with_date_rejects_past_date(self):
        """Past dates would silently launder Tries past the FORCE-CLOSE gate."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Hold until [refs: aaaaaaaaaaaa]",
                force_defer_until="2020-01-01",
            )
        self.assertIn("today", str(ctx.exception))
        self.assertIn("launder", str(ctx.exception))

    def test_force_close_message_lists_all_refs(self):
        """Multi-ref Tries: message names every gated ref, not just the first."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self._seed_prior_defers("bbbbbbbbbbbb", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Both stale [refs: aaaaaaaaaaaa, bbbbbbbbbbbb]",
            )
        msg = str(ctx.exception)
        self.assertIn("aaaaaaaa", msg)
        self.assertIn("bbbbbbbb", msg)


class _ReferencesHistoryMixin:
    """Re-run a FORCE-CLOSE suite against deferral history recorded the NEW
    way (top-level `references`) instead of the legacy metadata.resolves.

    Subclassing rather than parameterizing: this file runs under plain
    `unittest discover` in CI, where a pytest marker would deselect nothing
    and break the run (decision `test-runner-portability`).
    """

    def _seed_prior_defers(
        self, try_ref_id: str, count: int, link_field: str = "references"
    ) -> None:
        super()._seed_prior_defers(try_ref_id, count, link_field)  # type: ignore[misc]


class TestForceCloseGateReferencesHistory(_ReferencesHistoryMixin, TestForceCloseGate):
    """The gate counts deferrals linked via `references`, not just resolves."""


class TestForceAdoptBreaksGateReferencesHistory(
    _ReferencesHistoryMixin, TestForceAdoptBreaksGate
):
    pass


class TestForceDropBreaksGateReferencesHistory(
    _ReferencesHistoryMixin, TestForceDropBreaksGate
):
    pass


class TestForceDeferWithDateBreaksGateReferencesHistory(
    _ReferencesHistoryMixin, TestForceDeferWithDateBreaksGate
):
    pass


class TestForceCloseGateMixedHistory(_ForceCloseTestCase):
    """A real SMM log at migration time holds BOTH shapes: deferrals written
    before the routing change (metadata.resolves) and after (references).
    Neither leg alone reaches the threshold — only counting both does.
    """

    def _seed_mixed(self, try_ref_id: str, legacy: int, modern: int) -> None:
        events = [self._defer_event(i, try_ref_id, "resolves") for i in range(legacy)]
        events += [
            self._defer_event(legacy + i, try_ref_id, "references")
            for i in range(modern)
        ]
        self._write_events(events)

    def test_mixed_legacy_and_new_history_reaches_threshold(self):
        self._seed_mixed("aaaaaaaaaaaa", legacy=2, modern=1)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Defer once more [refs: aaaaaaaaaaaa]",
            )
        self.assertIn("FORCE-CLOSE", str(ctx.exception))
        self.assertEqual(len(self._read_events()), 3)

    def test_mixed_history_below_threshold_still_allowed(self):
        self._seed_mixed("aaaaaaaaaaaa", legacy=1, modern=1)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer again [refs: aaaaaaaaaaaa]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_one_event_carrying_both_shapes_counts_once(self):
        """A deferral naming the Try in both fields is still ONE deferral."""
        events = []
        for i in range(3):
            event = self._defer_event(i, "aaaaaaaaaaaa", "resolves")
            event["references"] = ["aaaaaaaaaaaa"]
            events.append(event)
        self._write_events(events)
        # 3 events, double-linked — the gate must see 3, not 6, and refuse.
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Defer once more [refs: aaaaaaaaaaaa]",
            )
        self.assertIn("have 3 prior deferrals", str(ctx.exception))


class TestForceCloseLaneScoping(_ForceCloseTestCase):
    """The gate counts deferrals of the TRY, not deferrals of things the Try
    merely mentions — and it must keep counting the untagged deferrals written
    before the lane tag existed.

    Three legs, load-bearing in opposite directions. Drop the lane check and a
    *debt's* deferral inflates a Try's count toward a FORCE-CLOSE it never
    earned. Drop the try-target scoping and another *Try's* deferral does the
    same thing through a debt they both cite — same bag, one lane over. Drop the
    untagged leg and pre-tag deferrals stop counting, zeroing those Tries' counts
    and disarming the gate on exactly the long-carried Tries it exists to catch.
    """

    TRY_ID = "2b15e8490179"

    def test_triage_defer_of_a_cited_debt_does_not_inflate_the_count(self):
        """Story test 3. The Try's ref bag holds the debt ids its prose cites,
        and the triage lane now links its deferrals in that same `references`
        field. A debt's deferral is not the Try's.

        Live pair this reproduces: Try 2b15e8490179's bag holds debt
        9ec0731f5597, which already carries triage-defer 181cb8fa2316.
        """
        debt = make_event(EVENT_TYPE_DEBT, content="The debt the Try cites")
        self._write_events([debt])
        for _ in range(_FORCE_CLOSE_THRESHOLD + 1):
            self.mod.run(
                action="triage-defer",
                smm_dir=self.smm_dir,
                content="",
                event_id=debt["id"],
            )
        # The Try itself has NEVER been deferred; only the debt it cites has.
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Carry the Try [refs: {self.TRY_ID}, {debt['id']}]",
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertIn(self.TRY_ID, event["references"])

    def test_defer_of_another_try_citing_the_same_debt_does_not_inflate(self):
        """The SAME bag leak, one lane over. The lane check stops a *debt's*
        deferral from counting; it does nothing about another *Try's* deferral
        reaching this Try through a shared cited id, because both events are
        retro-lane and both bags hold the debt.

        This Try has NEVER been deferred. Only the other one has.
        """
        debt = make_event(EVENT_TYPE_DEBT, content="The debt BOTH Tries cite")
        self._write_events([debt])
        other_try = "3c3c3c3c3c3c"
        for _ in range(_FORCE_CLOSE_THRESHOLD):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry the OTHER Try [refs: {other_try}, {debt['id']}]",
            )
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Carry THIS Try [refs: {self.TRY_ID}, {debt['id']}]",
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertIn(self.TRY_ID, event["references"])

    def test_legacy_untagged_defer_still_counts(self):
        """Story test 3b. Every retro deferral written before the lane tag
        existed carries no `metadata.action`; a bare
        `action == retro_try_disposition` gate would exclude all of them and
        disarm this gate on the Tries carried longest. The plugin ships to
        installs whose logs hold exactly this shape, which is why the fixture
        builds it explicitly rather than reading one off this repo's log — this
        repo has none (its untagged deferrals are all unlinked triage-defers).
        """
        self._seed_prior_defers(self.TRY_ID, _FORCE_CLOSE_THRESHOLD, "references")
        seeded = self._read_events()
        self.assertTrue(
            all("action" not in e["metadata"] for e in seeded),
            "fixture must be UNTAGGED or this test proves nothing",
        )
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry it again [refs: {self.TRY_ID}]",
            )
        self.assertIn("FORCE-CLOSE", str(ctx.exception))

    def test_tagged_retro_defers_count(self):
        """The forward path: deferrals the writer tags today reach the gate."""
        for _ in range(_FORCE_CLOSE_THRESHOLD):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry it [refs: {self.TRY_ID}]",
            )
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content=f"Carry it again [refs: {self.TRY_ID}]",
            )
        self.assertIn("FORCE-CLOSE", str(ctx.exception))


class TestForceCloseCli(_ForceCloseTestCase):
    """End-to-end CLI argparse coverage for the new flags."""

    def test_cli_plain_defer_at_threshold_exits_nonzero(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Plain defer [refs: aaaaaaaaaaaa]",
            ]
        )
        self.assertNotEqual(code, 0)

    def test_cli_force_adopt_at_threshold_persists_decision(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Adopt now [refs: aaaaaaaaaaaa]",
                "--force-adopt",
                "retro-try-cli-forced",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._last_event()["type"], EVENT_TYPE_DECISION)

    def test_cli_force_drop_at_threshold_persists_drop(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Drop now [refs: aaaaaaaaaaaa]",
                "--force-drop",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._last_event()["metadata"]["disposition"], "dropped")

    def test_cli_force_defer_with_date_persists_defer_until(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Hold until [refs: aaaaaaaaaaaa]",
                "--force-defer-with-date",
                "2026-09-01",
            ]
        )
        self.assertEqual(code, 0)
        event = self._last_event()
        self.assertEqual(event["metadata"]["defer_until"], "2026-09-01")

    def test_cli_force_flags_mutually_exclusive(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        code = self._run_main(
            [
                "defer",
                "--smm-dir",
                str(self.smm_dir),
                "--content",
                "Conflict [refs: aaaaaaaaaaaa]",
                "--force-drop",
                "--force-adopt",
                "retro-try-x",
            ]
        )
        self.assertNotEqual(code, 0)


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


class TestDropContentCascade(_DecideTestCase):
    """drop scans content for debt/concern/discovery hex IDs and cascades.

    When a Try mentions an underlying open debt/concern/discovery event by
    its 12-hex ID in prose (not just in `[refs: ...]`), dropping the Try
    must also resolve the root events — otherwise the retro agent sees the
    root still open and re-proposes a fresh Try every session. Cascade
    scope mirrors PROBE_RESOLVABLE_TYPES (debt + concern + discovery).
    """

    def _seed_event(
        self,
        event_type: str,
        event_id: str,
        extra: dict | None = None,
    ) -> dict:
        kwargs: dict = {"id": event_id, "content": f"seeded {event_type}"}
        if extra:
            kwargs.update(extra)
        event = make_event(event_type, **kwargs)
        existing = self._read_events()
        self._write_events([*existing, event])
        return event

    def test_drop_resolves_debt_in_content(self):
        debt = self._seed_event(EVENT_TYPE_DEBT, "9c3f5406cacd", {"files": ["x.py"]})
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"1Password debt {debt['id']}: close with rationale",
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertIn(debt["id"], event["metadata"].get("resolves", []))

    def test_drop_cascade_survives_content_truncation(self):
        """A debt id mentioned past the 200-char budget still cascades.

        Guards fix ordering: cascade hex-token scan must run on the full
        content BEFORE the budget truncation, or a trailing id is lost.
        """
        debt = self._seed_event(EVENT_TYPE_DEBT, "9c3f5406cacd", {"files": ["x.py"]})
        prose = "Drop this Try " + "z" * 220 + f" closes {debt['id']}"
        self.assertGreater(prose.index(debt["id"]), 200)
        self.mod.run(action="drop", smm_dir=self.smm_dir, content=prose)
        event = self._last_event()
        self.assertLessEqual(len(event["content"]), 200)
        self.assertIn(debt["id"], event["metadata"].get("resolves", []))

    def test_drop_resolves_concern_in_content(self):
        concern = self._seed_event(
            EVENT_TYPE_CONCERN, "aaaaaaaaaaaa", {"severity": "medium", "files": []}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Concern {concern['id']} won't resolve — drop it",
        )
        event = self._last_event()
        self.assertIn(concern["id"], event["metadata"].get("resolves", []))

    def test_drop_resolves_discovery_in_content(self):
        discovery = self._seed_event(
            EVENT_TYPE_DISCOVERY, "bbbbbbbbbbbb", {"references": ["referenced-id"]}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Discovery {discovery['id']} no longer relevant",
        )
        event = self._last_event()
        self.assertIn(discovery["id"], event["metadata"].get("resolves", []))

    def test_drop_ignores_question_hex_token(self):
        question = self._seed_event(
            EVENT_TYPE_QUESTION, "cccccccccccc", {"priority": "\U0001f534"}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Question {question['id']} mentioned but not for cascade",
        )
        event = self._last_event()
        self.assertNotIn(question["id"], event["metadata"].get("resolves", []))

    def test_drop_ignores_decision_hex_token(self):
        decision = self._seed_event(
            EVENT_TYPE_DECISION, "dddddddddddd", {"topic": "some-topic"}
        )
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Per decision {decision['id']}, dropping this Try",
        )
        event = self._last_event()
        self.assertNotIn(decision["id"], event["metadata"].get("resolves", []))

    def test_drop_ignores_unknown_hex_token(self):
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content="Drop with stray hex eeeeeeeeeeee not matching any event",
        )
        event = self._last_event()
        self.assertNotIn("eeeeeeeeeeee", event["metadata"].get("resolves", []))

    def test_drop_dedupes_debt_id_in_both_content_and_refs_suffix(self):
        debt = self._seed_event(EVENT_TYPE_DEBT, "ffffffffffff", {"files": ["x.py"]})
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Debt {debt['id']} done [refs: {debt['id']}]",
        )
        event = self._last_event()
        resolves = event["metadata"].get("resolves", [])
        self.assertEqual(resolves.count(debt["id"]), 1)

    def test_force_drop_also_resolves_debt_in_content(self):
        debt = self._seed_event(EVENT_TYPE_DEBT, "111111111111", {"files": ["x.py"]})
        # Seed prior defers so force-drop is the only path through.
        prior_defers = [
            {
                "id": f"{i:012x}",
                "ts": f"2026-01-{i + 1:02d}T00:00:00+00:00",
                "type": EVENT_TYPE_STATUS,
                "agent_id": "main",
                "content": f"Defer {i}",
                "schema_version": 1,
                "working_on": [],
                "metadata": {
                    "resolves": ["aaaaaaaaaaaa"],
                    "disposition": "deferred",
                },
            }
            for i in range(3)
        ]
        existing = self._read_events()
        self._write_events([*existing, *prior_defers])
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content=f"Drop debt {debt['id']} [refs: aaaaaaaaaaaa]",
            force_drop=True,
        )
        event = self._last_event()
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertIn(debt["id"], event["metadata"]["resolves"])

    def test_drop_resolves_multiple_debts_in_content(self):
        debt1 = self._seed_event(EVENT_TYPE_DEBT, "222222222222", {"files": ["a.py"]})
        debt2 = self._seed_event(EVENT_TYPE_DEBT, "333333333333", {"files": ["b.py"]})
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content=f"Drop both: {debt1['id']} and {debt2['id']}",
        )
        resolves = self._last_event()["metadata"].get("resolves", [])
        self.assertIn(debt1["id"], resolves)
        self.assertIn(debt2["id"], resolves)

    def test_drop_with_no_hex_tokens_skips_events_read(self):
        """Perf guard: bare prose drops must not scan events.jsonl.

        Protects the `if tokens:` short-circuit so future refactors can't
        accidentally make every drop O(events). Resolves concern eab4b083f5bf.
        """
        from unittest.mock import patch

        with patch.object(
            work_selection_decide._common, "read_events_locked"
        ) as mock_read:
            self.mod.run(
                action="drop",
                smm_dir=self.smm_dir,
                content="Drop forever, no hex tokens in prose",
            )
            mock_read.assert_not_called()


class TestForceDropConventionEmission(_ForceCloseTestCase):
    """--record-convention-topic + --record-convention-content on a
    `defer --force-drop` emits a convention event in addition to the drop
    status event. The convention is a durable suppression record so the
    retro agent won't re-propose the Try under any signal.

    Force-drop is the canonical "user explicitly rejects, never re-propose"
    moment — regular drops are one-shot per Wisdom and don't get a
    convention prompt (per design call).
    """

    def test_force_drop_with_convention_flags_emits_two_events(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
            convention_topic="retro-drop-security-review-diff-only",
            convention_content=(
                "/security-review is diff-only; never propose for docs-only changes."
            ),
        )
        events = self._read_events()
        # 3 seeded prior-defers + drop + convention
        self.assertEqual(len(events), 5)
        self.assertEqual(events[-2]["type"], EVENT_TYPE_STATUS)
        self.assertEqual(events[-2]["metadata"]["disposition"], "dropped")
        convention = events[-1]
        self.assertEqual(convention["type"], EVENT_TYPE_CONVENTION)
        self.assertEqual(convention["topic"], "retro-drop-security-review-diff-only")
        self.assertIn("diff-only", convention["content"])

    def test_force_drop_convention_overbudget_content_truncates(self):
        """An over-budget convention rationale truncates rather than failing.

        Mirrors the main-event chokepoint so the convention path can't raise
        "Content exceeds convention budget" and abort the drop's record.
        """
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        long_rationale = "Never re-propose this kind of Try because " + "w" * 250
        self.assertGreater(len(long_rationale), 250)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
            convention_topic="retro-drop-overbudget-rationale",
            convention_content=long_rationale,
        )
        convention = self._read_events()[-1]
        self.assertEqual(convention["type"], EVENT_TYPE_CONVENTION)
        self.assertLessEqual(len(convention["content"]), 250)

    def test_force_drop_without_convention_flags_emits_only_drop(self):
        """Default behavior unchanged: force-drop alone emits one event."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
        )
        events = self._read_events()
        self.assertEqual(len(events), 4)
        self.assertEqual(events[-1]["type"], EVENT_TYPE_STATUS)
        self.assertEqual(events[-1]["metadata"]["disposition"], "dropped")

    def test_regular_drop_rejects_convention_flags(self):
        """Convention prompt is force-drop only — plain `drop` rejects."""
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="drop",
                smm_dir=self.smm_dir,
                content="Drop now",
                convention_topic="retro-drop-test",
                convention_content="rationale",
            )
        self.assertIn("force-drop", str(ctx.exception).lower())

    def test_convention_emission_is_idempotent(self):
        """Second invocation with same topic appends the drop but NOT a
        second convention. The discarded rationale surfaces on stderr —
        silent skipping would lose user signal.
        """
        import io
        from contextlib import redirect_stderr

        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
            convention_topic="retro-drop-test-foo",
            convention_content="rationale 1",
        )
        # Second force-drop against same topic — convention MUST be skipped
        # AND the second rationale's loss must surface on stderr (honesty).
        err = io.StringIO()
        with redirect_stderr(err):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop again [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="retro-drop-test-foo",
                convention_content="rationale 2",
            )
        self.assertIn("retro-drop-test-foo", err.getvalue())
        self.assertIn("already recorded", err.getvalue())

        events = self._read_events()
        conventions = [e for e in events if e.get("type") == "convention"]
        self.assertEqual(len(conventions), 1)
        # First write wins
        self.assertIn("rationale 1", conventions[0]["content"])
        # Two drop events should exist (one per force-drop call)
        drops = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and (e.get("metadata") or {}).get("disposition") == "dropped"
        ]
        self.assertEqual(len(drops), 2)

    def test_convention_topic_must_use_retro_drop_prefix(self):
        """Slug without retro-drop- prefix rejected to avoid collision
        with retro-try-<slug> adoption topics.
        """
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop forever [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="security-review-diff-only",
                convention_content="rationale",
            )
        self.assertIn("retro-drop-", str(ctx.exception))

    def test_convention_topic_must_be_kebab_case(self):
        """Topic must match ^[a-z0-9]+(-[a-z0-9]+)+$ (after prefix)."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop forever [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="retro-drop-NotKebab_Case",
                convention_content="rationale",
            )
        self.assertIn("kebab", str(ctx.exception).lower())

    def test_convention_flags_require_both_or_neither(self):
        """Topic without content (or vice versa) rejected."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Drop forever [refs: aaaaaaaaaaaa]",
                force_drop=True,
                convention_topic="retro-drop-foo",
                # content missing
            )

    def test_convention_flags_require_force_drop(self):
        """--force-adopt or --force-defer-with-date must not silently
        accept the convention flags; only --force-drop honors them.
        """
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Adopt [refs: aaaaaaaaaaaa]",
                force_adopt_topic="retro-try-foo",
                convention_topic="retro-drop-foo",
                convention_content="rationale",
            )
        self.assertIn("force-drop", str(ctx.exception).lower())


class TestForceDropFilterFunctions(unittest.TestCase):
    """Pure filter functions over an event list — no SMM I/O, no flock.

    The force-drop path used to do 3 independent locked reads
    (_convention_topic_exists, _count_prior_defers, _build_drop_event
    cascade). Filters now take the events list as an arg so they can be
    unit-tested without writing to disk, and the orchestrator does one
    locked read per invocation.
    """

    def _events(self) -> list[dict]:
        # Mixed event set: 2 conventions, 2 deferred statuses, 1 debt, 1 concern.
        return [
            make_event(
                EVENT_TYPE_CONVENTION,
                topic="retro-drop-foo",
                content="durable suppression for foo",
            ),
            make_event(
                EVENT_TYPE_CONVENTION,
                topic="retro-drop-bar",
                content="durable suppression for bar",
            ),
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try ref aaaaaaaaaaaa",
                metadata={"disposition": "deferred", "resolves": ["aaaaaaaaaaaa"]},
            ),
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try ref bbbbbbbbbbbb",
                metadata={"disposition": "deferred", "resolves": ["bbbbbbbbbbbb"]},
            ),
            make_event(EVENT_TYPE_DEBT, content="some debt", files=["x.py"]),
            make_event(EVENT_TYPE_CONCERN, content="some concern", files=["y.py"]),
        ]

    def test_convention_topic_exists_filter_hit(self):
        self.assertTrue(
            work_selection_decide._convention_topic_exists_filter(
                self._events(), "retro-drop-foo"
            )
        )

    def test_convention_topic_exists_filter_miss(self):
        self.assertFalse(
            work_selection_decide._convention_topic_exists_filter(
                self._events(), "retro-drop-unseen"
            )
        )

    def test_count_prior_defers_filter_counts_matches(self):
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(
                self._events(), ["aaaaaaaaaaaa"]
            ),
            1,
        )

    def test_count_prior_defers_filter_counts_references_link(self):
        """New-shape deferrals name their Try in `references`."""
        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try",
                metadata={"disposition": "deferred"},
                references=["cccccccccccc"],
            )
        ]
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(events, ["cccccccccccc"]),
            1,
        )

    def test_count_prior_defers_filter_counts_double_linked_event_once(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try",
                metadata={"disposition": "deferred", "resolves": ["cccccccccccc"]},
                references=["cccccccccccc"],
            )
        ]
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(events, ["cccccccccccc"]),
            1,
        )

    def test_count_prior_defers_filter_ignores_non_deferred_references(self):
        """An adopting status also carries `references` now — it is not a defer."""
        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="adopted Try",
                metadata={"disposition": "adopted"},
                references=["cccccccccccc"],
            )
        ]
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(events, ["cccccccccccc"]),
            0,
        )

    def test_count_prior_defers_filter_handles_empty_refs(self):
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(self._events(), []),
            0,
        )

    def test_count_prior_defers_filter_no_match(self):
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(
                self._events(), ["ffffffffffff"]
            ),
            0,
        )

    def test_cascade_ids_filter_returns_resolvable_overlap(self):
        events = self._events()
        debt_id = events[4]["id"]
        concern_id = events[5]["id"]
        result = work_selection_decide._cascade_ids_filter(
            events, {debt_id, concern_id, "no-such-id"}
        )
        self.assertEqual(result, {debt_id, concern_id})

    def test_cascade_ids_filter_skips_non_resolvable_types(self):
        # CONVENTION + STATUS events are not in PROBE_RESOLVABLE_TYPES,
        # so even if their ids appear in tokens they must not cascade-close.
        events = self._events()
        convention_id = events[0]["id"]
        status_id = events[2]["id"]
        result = work_selection_decide._cascade_ids_filter(
            events, {convention_id, status_id}
        )
        self.assertEqual(result, set())


if __name__ == "__main__":
    unittest.main()

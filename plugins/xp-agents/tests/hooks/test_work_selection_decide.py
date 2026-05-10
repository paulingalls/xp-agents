#!/usr/bin/env python3
"""Tests for work_selection_decide.py — the Try-item adopt/defer/drop helper.

The helper extracts `[refs: ...]` from retro Try text and appends a decision
or status event with metadata.resolves populated automatically. Replaces
LLM-crafted --metadata JSON discipline with code.
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

import resolves_probe
import work_selection_decide
from conftest import _HookTestCase
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_STATUS


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
    """adopt subcommand: emits decision event with topic + optional resolves."""

    def test_adopt_with_refs_populates_metadata_resolves(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Commit after green [refs: abc123def456, 7df84bb18a49]",
            topic="retro-try-commit-after-green",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_DECISION)
        self.assertEqual(event["topic"], "retro-try-commit-after-green")
        self.assertEqual(
            event["metadata"]["resolves"],
            ["abc123def456", "7df84bb18a49"],
        )

    def test_adopt_with_refs_strips_suffix_from_content(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Commit after green [refs: abc123def456]",
            topic="retro-try-commit-after-green",
        )
        event = self._last_event()
        self.assertEqual(event["content"], "Commit after green")

    def test_adopt_without_refs_has_no_resolves_key(self):
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
    """defer subcommand: status event, disposition=deferred, working_on=[]."""

    def test_defer_with_refs_sets_resolves_and_disposition(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this [refs: abc123def456, 7df84bb18a49]",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["working_on"], [])
        self.assertEqual(
            event["metadata"],
            {
                "resolves": ["abc123def456", "7df84bb18a49"],
                "disposition": "deferred",
            },
        )

    def test_defer_without_refs_has_only_disposition(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this with no refs",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"], {"disposition": "deferred"})
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
        self.assertEqual(event["metadata"], {"disposition": "dropped"})
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
            event["metadata"],
            {"resolves": ["abc123def456"], "disposition": "dropped"},
        )


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
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])

    def test_no_refs_suffix_leaves_content_untouched(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Plain content no refs",
            topic="retro-try-plain",
        )
        event = self._last_event()
        self.assertEqual(event["content"], "Plain content no refs")
        self.assertNotIn("resolves", event.get("metadata", {}))

    def test_all_malformed_refs_treated_as_no_refs(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Item [refs: not-hex, 42@#]",
            topic="retro-try-nothing",
        )
        event = self._last_event()
        self.assertNotIn("resolves", event.get("metadata", {}))

    def test_refs_with_only_whitespace_separator(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Item [refs: abc123def456 7df84bb18a49]",
            topic="retro-try-space",
        )
        event = self._last_event()
        self.assertEqual(
            event["metadata"]["resolves"],
            ["abc123def456", "7df84bb18a49"],
        )

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
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])

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
        self.assertEqual(
            event["metadata"],
            {"resolves": ["abc123def456"], "disposition": "deferred"},
        )


# ---------------------------------------------------------------------------
# Triage subcommands (debt/concern/question triage)
# ---------------------------------------------------------------------------


class TestTriageAdopt(_DecideTestCase):
    """triage-adopt: status event, disposition=adopted, resolves=[id]."""

    def test_creates_status_with_resolves(self):
        self.mod.run(
            action="triage-adopt",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])
        self.assertEqual(event["metadata"]["disposition"], "adopted")
        self.assertEqual(event["working_on"], [])

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
    """triage-defer: status event, disposition=deferred, no resolves."""

    def test_creates_status_without_resolves(self):
        self.mod.run(
            action="triage-defer",
            smm_dir=self.smm_dir,
            content="",
            event_id="abc123def456",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertNotIn("resolves", event["metadata"])
        self.assertEqual(event["working_on"], [])


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


# ---------------------------------------------------------------------------
# FORCE-CLOSE gate — refuse plain defer when a Try has been deferred 3+ times.
# Carrying a Try across 3+ retros without adoption is dishonest.
# Gate fires on the 4th defer attempt; user must use a force flag.
# ---------------------------------------------------------------------------


class _ForceCloseTestCase(_DecideTestCase):
    """Helpers for seeding prior-defer history against a Try id."""

    def _seed_prior_defers(self, try_ref_id: str, count: int) -> None:
        events = []
        for i in range(count):
            events.append(
                {
                    "id": f"{i:012x}",
                    "ts": f"2026-01-{i + 1:02d}T00:00:00+00:00",
                    "type": EVENT_TYPE_STATUS,
                    "agent_id": "main",
                    "content": f"Defer {i}",
                    "schema_version": 1,
                    "working_on": [],
                    "metadata": {
                        "resolves": [try_ref_id],
                        "disposition": "deferred",
                    },
                }
            )
        self._write_events(events)


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
        self.assertEqual(self._last_event()["metadata"], {"disposition": "deferred"})

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
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])
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
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])

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
        self.assertEqual(event["metadata"]["resolves"], ["abc123def456"])

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


class TestAdoptSignalsProbeRefresh(_DecideTestCase):
    """Story-002 AC#2: adopt path must signal probe refresh after recording
    the decision so subsequent fast pre-commit probes (within the 5s
    wall-clock window) re-read disk and see the just-written decision."""

    def _sentinel(self) -> Path:
        return resolves_probe.refresh_sentinel_path(self.smm_dir)

    def test_adopt_signals_probe_refresh(self):
        self.assertFalse(self._sentinel().exists())
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="Try with refs [refs: abc123def456]",
            topic="retro-try-some-slug",
        )
        self.assertTrue(
            self._sentinel().exists(),
            "adopt path MUST signal probe refresh after appending the "
            "decision so subsequent fast pre-commit probes see it.",
        )

    def test_force_adopt_via_defer_signals_probe_refresh(self):
        # force-adopt under defer also writes a decision event → must signal.
        self.assertFalse(self._sentinel().exists())
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Try [refs: abc123def456]",
            force_adopt_topic="retro-try-foo",
        )
        self.assertTrue(self._sentinel().exists())

    def test_drop_does_not_signal_probe_refresh(self):
        # drop is a status event, not a decision — no probe refresh needed.
        self.mod.run(
            action="drop",
            smm_dir=self.smm_dir,
            content="Drop this Try [refs: abc123def456]",
        )
        self.assertFalse(self._sentinel().exists())

    def test_plain_defer_does_not_signal_probe_refresh(self):
        # defer is a status event → no refresh.
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this Try [refs: abc123def456]",
        )
        self.assertFalse(self._sentinel().exists())


if __name__ == "__main__":
    unittest.main()

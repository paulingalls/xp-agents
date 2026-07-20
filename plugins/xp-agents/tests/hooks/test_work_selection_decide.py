#!/usr/bin/env python3
"""Tests for work_selection_decide.py — the Try-item adopt/defer/drop helper.

The helper extracts `[refs: ...]` from retro Try text and appends a decision
or status event with the refs routed by evidence: a closing event (terminal
disposition) populates metadata.resolves; an intent event (adoption, deferral)
populates top-level `references`. Replaces LLM-crafted --metadata JSON
discipline with code.

Covers the core adopt/defer/drop actions, ref-parsing edge cases, and the
argparse CLI surface for them. Triage subcommands, the FORCE-CLOSE gate, and
drop's content-cascade/convention-emission moved to same-stem siblings when
this file crossed 500 lines: test_work_selection_decide_triage.py,
test_work_selection_decide_force_close_gate.py,
test_work_selection_decide_force_close_extra.py, and
test_work_selection_decide_drop_cascade.py. Shared base TestCases and
constants live in _work_selection_decide_helpers.py so no sibling imports
another.
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

from _work_selection_decide_helpers import (
    _RETRO_DEFERRED,
    _RETRO_DROPPED,
    _DecideTestCase,
)
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_STATUS


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


if __name__ == "__main__":
    unittest.main()

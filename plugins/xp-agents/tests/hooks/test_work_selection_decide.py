#!/usr/bin/env python3
"""Tests for work_selection_decide.py — the Try-item adopt/defer/drop helper.

The helper extracts `[refs: ...]` from retro Try text and appends a decision
or status event with metadata.resolves populated automatically. Replaces
LLM-crafted --metadata JSON discipline with code.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import work_selection_decide
from conftest import _HookTestCase


class _DecideTestCase(_HookTestCase):
    """Shared setup: expose mod + _last_event()."""

    def setUp(self):
        super().setUp()
        self.mod = work_selection_decide

    def _last_event(self) -> dict:
        events = self._read_events()
        self.assertGreater(len(events), 0, "expected at least one event")
        return events[-1]


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
        self.assertEqual(event["type"], "decision")
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
        self.assertEqual(event["type"], "decision")
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
        self.assertEqual(self._last_event()["type"], "decision")

    def test_adopt_agent_id_is_xp_work_selection(self):
        self.mod.run(
            action="adopt",
            smm_dir=self.smm_dir,
            content="A try",
            topic="retro-try-foo",
        )
        self.assertEqual(self._last_event()["agent_id"], "xp-work-selection")


class TestDefer(_DecideTestCase):
    """defer subcommand: status event, disposition=deferred, working_on=[]."""

    def test_defer_with_refs_sets_resolves_and_disposition(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this [refs: abc123def456, 7df84bb18a49]",
        )
        event = self._last_event()
        self.assertEqual(event["type"], "status")
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
        self.assertEqual(event["type"], "status")
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
        self.assertEqual(event["type"], "status")
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
        self.assertEqual(event["type"], "status")
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
        self.assertEqual(event["type"], "decision")
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
        self.assertEqual(event["type"], "status")
        self.assertEqual(
            event["metadata"],
            {"resolves": ["abc123def456"], "disposition": "deferred"},
        )


if __name__ == "__main__":
    unittest.main()

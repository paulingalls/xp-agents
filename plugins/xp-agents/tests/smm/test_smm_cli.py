#!/usr/bin/env python3
"""Tests for smm_cli: SMM CLI with rendering and write operations."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import smm_cli
import smm_schema
from conftest import _HookTestCase, make_event


def _entry(content, source="seed", **extra):
    """Build a valid entry with a fresh id."""
    import secrets

    e = {
        "id": secrets.token_hex(6),
        "content": content,
        "source": source,
        "ts": "2026-04-09T02:15:28+00:00",
    }
    e.update(extra)
    return e


class TestRenderMarkdown(unittest.TestCase):
    """render_markdown produces four-pillar markdown from a dict."""

    def test_empty_renders_four_pillars(self):
        result = smm_cli.render_markdown(smm_schema.empty_smm())
        self.assertIn("## Intent", result)
        self.assertIn("## Constraints", result)
        self.assertIn("## Risks", result)
        self.assertIn("## Wisdom", result)

    def test_empty_pillars_have_no_bullets(self):
        result = smm_cli.render_markdown(smm_schema.empty_smm())
        for line in result.splitlines():
            self.assertFalse(line.startswith("- "))

    def test_intent_goal_rendered(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        result = smm_cli.render_markdown(smm)
        self.assertIn("Ship v1", result)

    def test_intent_customer_intent_rendered(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Add RBAC", type="customer_intent")]
        result = smm_cli.render_markdown(smm)
        self.assertIn("Add RBAC", result)

    def test_constraint_rendered(self):
        smm = smm_schema.empty_smm()
        smm["constraints"] = [_entry("Use REST", type="decision")]
        result = smm_cli.render_markdown(smm)
        self.assertIn("Use REST", result)

    def test_risk_rendered(self):
        smm = smm_schema.empty_smm()
        smm["risks"] = [_entry("Auth fragile", type="concern", severity="problem")]
        result = smm_cli.render_markdown(smm)
        self.assertIn("Auth fragile", result)

    def test_wisdom_rendered_plain(self):
        smm = smm_schema.empty_smm()
        smm["wisdom"] = [_entry("Commit after green")]
        result = smm_cli.render_markdown(smm)
        self.assertIn("- Commit after green", result)

    def test_multiple_entries_per_pillar(self):
        smm = smm_schema.empty_smm()
        smm["wisdom"] = [
            _entry("TDD always"),
            _entry("Small commits"),
        ]
        result = smm_cli.render_markdown(smm)
        self.assertIn("TDD always", result)
        self.assertIn("Small commits", result)


class TestExtractPillar(unittest.TestCase):
    """extract_pillar returns a single pillar section as markdown."""

    def test_extract_intent(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        result = smm_cli.extract_pillar(smm, "intent")
        self.assertIn("## Intent", result)
        self.assertIn("Ship v1", result)

    def test_extract_excludes_other_pillars(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        smm["wisdom"] = [_entry("TDD always")]
        result = smm_cli.extract_pillar(smm, "intent")
        self.assertNotIn("Wisdom", result)
        self.assertNotIn("TDD always", result)

    def test_extract_missing_pillar_returns_empty(self):
        smm = smm_schema.empty_smm()
        result = smm_cli.extract_pillar(smm, "nonexistent")
        self.assertEqual(result, "")

    def test_extract_empty_pillar_returns_header(self):
        smm = smm_schema.empty_smm()
        result = smm_cli.extract_pillar(smm, "intent")
        self.assertIn("## Intent", result)


class TestExtractPillars(unittest.TestCase):
    """extract_pillars returns multiple pillar sections concatenated."""

    def test_extract_two_pillars(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        smm["constraints"] = [_entry("Use REST", type="decision")]
        result = smm_cli.extract_pillars(smm, {"intent", "constraints"})
        self.assertIn("Intent", result)
        self.assertIn("Ship v1", result)
        self.assertIn("Constraints", result)
        self.assertIn("Use REST", result)

    def test_extract_pillars_excludes_others(self):
        smm = smm_schema.empty_smm()
        smm["intent"] = [_entry("Ship v1", type="goal")]
        smm["wisdom"] = [_entry("TDD always")]
        result = smm_cli.extract_pillars(smm, {"intent"})
        self.assertNotIn("TDD always", result)

    def test_extract_pillars_wraps_in_header(self):
        smm = smm_schema.empty_smm()
        result = smm_cli.extract_pillars(smm, {"intent"})
        self.assertIn("# Shared Mental Model", result)


def _valid_smm_json(**overrides) -> str:
    """Build a valid SMM JSON string."""
    data = smm_schema.empty_smm()
    data.update(overrides)
    return json.dumps(data)


def _smm_with_intent(content: str = "Ship v1") -> str:
    """Build an SMM JSON with one intent entry."""
    import secrets

    data = smm_schema.empty_smm()
    data["intent"] = [
        {
            "id": secrets.token_hex(6),
            "content": content,
            "source": "seed",
            "ts": "2026-01-01T00:00:00+00:00",
            "type": "goal",
        }
    ]
    return json.dumps(data)


class TestSaveCommand(_HookTestCase):
    """Tests for smm_cli.save() — validate + write + watermark + compact."""

    def test_writes_smm_file(self):
        content = _smm_with_intent("Ship v1")
        smm_cli.save(content, smm_dir=self.smm_dir)
        import smm_store

        smm_file = self.smm_dir / smm_store.SMM_FILENAME
        self.assertTrue(smm_file.exists())
        data = json.loads(smm_file.read_text())
        self.assertEqual(data["intent"][0]["content"], "Ship v1")

    def test_updates_curation_watermark(self):
        self._write_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
            ]
        )
        smm_cli.save(_valid_smm_json(), smm_dir=self.smm_dir)
        import materialize as _mat

        wm = _mat.read_curation_watermark(self.smm_dir)
        self.assertEqual(wm["event_count"], 2)
        self.assertEqual(wm["agent_id"], "xp-housekeeper")

    def test_overwrites_existing_smm(self):
        import smm_store

        smm_store.save_smm(self.smm_dir, smm_schema.empty_smm())
        smm_cli.save(_smm_with_intent("new goal"), smm_dir=self.smm_dir)
        data = smm_store.load_smm(self.smm_dir)
        self.assertEqual(data["intent"][0]["content"], "new goal")

    def test_rejects_invalid_json(self):
        with self.assertRaises(json.JSONDecodeError):
            smm_cli.save("not json", smm_dir=self.smm_dir)

    def test_rejects_invalid_schema(self):
        with self.assertRaises(ValueError):
            smm_cli.save('{"bad": "schema"}', smm_dir=self.smm_dir)

    def test_triggers_compaction(self):
        from unittest.mock import patch

        self._write_events([make_event("goal", content="Ship v1")])
        with patch("compact.compact_after_curation") as mock:
            smm_cli.save(_valid_smm_json(), smm_dir=self.smm_dir)
        mock.assert_called_once_with(self.smm_dir)

    def test_compaction_failure_does_not_fail_write(self):
        from unittest.mock import patch

        import smm_store

        with patch("compact.compact_after_curation", side_effect=OSError("boom")):
            smm_cli.save(_valid_smm_json(), smm_dir=self.smm_dir)
        self.assertTrue((self.smm_dir / smm_store.SMM_FILENAME).exists())


class TestCompleteCuration(_HookTestCase):
    """Tests for smm_cli.complete_curation() — watermark + compact."""

    def test_updates_watermark(self):
        self._write_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
            ]
        )
        smm_cli.complete_curation(self.smm_dir)
        import materialize as _mat

        wm = _mat.read_curation_watermark(self.smm_dir)
        self.assertEqual(wm["event_count"], 2)
        self.assertEqual(wm["agent_id"], "xp-housekeeper")

    def test_runs_compaction(self):
        from unittest.mock import patch

        self._write_events([make_event("goal", content="Ship v1")])
        with patch("compact.compact_after_curation") as mock:
            smm_cli.complete_curation(self.smm_dir)
        mock.assert_called_once_with(self.smm_dir)

    def test_compaction_failure_does_not_raise(self):
        from unittest.mock import patch

        self._write_events([make_event("goal", content="Ship v1")])
        with patch("compact.compact_after_curation", side_effect=OSError("boom")):
            smm_cli.complete_curation(self.smm_dir)

    def test_watermark_advances_after_compaction(self):
        from _append_impl import append_event

        events = [make_event("goal", content="Ship v1")]
        events += [
            make_event("status", content=f"work {i}", working_on=[]) for i in range(20)
        ]
        self._write_events(events)
        smm_cli.complete_curation(self.smm_dir)
        import materialize as _mat

        wm1 = _mat.read_curation_watermark(self.smm_dir)
        self.assertEqual(wm1["event_count"], 21)

        for i in range(10):
            e = make_event("status", content=f"more {i}", working_on=[])
            append_event(self.smm_dir, e)

        smm_cli.complete_curation(self.smm_dir)
        wm2 = _mat.read_curation_watermark(self.smm_dir)
        events_after, _ = _mat.parse_events(self.smm_dir)
        self.assertEqual(wm2["event_count"], len(events_after))

    def test_save_calls_complete_curation(self):
        from unittest.mock import patch

        self._write_events([make_event("goal", content="Ship v1")])
        with patch.object(smm_cli, "complete_curation") as mock:
            smm_cli.save(_valid_smm_json(), smm_dir=self.smm_dir)
        mock.assert_called_once_with(self.smm_dir)


# ---------------------------------------------------------------------------
# add-item CLI
# ---------------------------------------------------------------------------


class TestAddItemCommand(_HookTestCase):
    def test_creates_entry(self):
        import io
        from unittest.mock import patch

        with patch("sys.stdin", io.StringIO("TDD always")):
            result = smm_cli._cmd_add_item(
                _make_cli_args(
                    self.smm_dir,
                    pillar="wisdom",
                    type=None,
                    topic=None,
                    severity=None,
                    source="curated",
                    source_event_id=None,
                )
            )
        self.assertEqual(result, 0)
        import smm_store

        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 1)
        self.assertEqual(smm["wisdom"][0]["content"], "TDD always")

    def test_prints_id(self):
        import io
        from unittest.mock import patch

        with (
            patch("sys.stdin", io.StringIO("TDD always")),
            patch("sys.stdout", new_callable=io.StringIO) as mock_out,
        ):
            smm_cli._cmd_add_item(
                _make_cli_args(
                    self.smm_dir,
                    pillar="wisdom",
                    type=None,
                    topic=None,
                    severity=None,
                    source="curated",
                    source_event_id=None,
                )
            )
        output = mock_out.getvalue().strip()
        self.assertRegex(output, r"^[0-9a-f]{12}$")

    def test_error_on_invalid_type(self):
        import io
        from unittest.mock import patch

        with (
            patch("sys.stdin", io.StringIO("Bad")),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            result = smm_cli._cmd_add_item(
                _make_cli_args(
                    self.smm_dir,
                    pillar="intent",
                    type="concern",
                    topic=None,
                    severity=None,
                    source="curated",
                    source_event_id=None,
                )
            )
        self.assertEqual(result, 1)


def _make_cli_args(smm_dir, command="add-item", **kwargs):
    """Build a namespace mimicking argparse output."""
    import argparse

    ns = argparse.Namespace(smm_dir=smm_dir, command=command)
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# update-item CLI
# ---------------------------------------------------------------------------


class TestUpdateItemCommand(_HookTestCase):
    def setUp(self):
        super().setUp()
        import smm_store

        self.uid = smm_store.add_item(
            self.smm_dir,
            "constraints",
            "Use REST",
            type="decision",
            topic="api-style",
        )

    def test_changes_content(self):
        import io
        from unittest.mock import patch

        with patch("sys.stdin", io.StringIO("Use GraphQL")):
            result = smm_cli._cmd_update_item(
                _make_cli_args(
                    self.smm_dir,
                    command="update-item",
                    item_id=self.uid,
                    type=None,
                    topic=None,
                    severity=None,
                )
            )
        self.assertEqual(result, 0)
        import smm_store

        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(smm["constraints"][0]["content"], "Use GraphQL")

    def test_error_on_missing_id(self):
        import io
        from unittest.mock import patch

        with (
            patch("sys.stdin", io.StringIO("")),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            result = smm_cli._cmd_update_item(
                _make_cli_args(
                    self.smm_dir,
                    command="update-item",
                    item_id="00000000-0000-4000-8000-000000000000",
                    type=None,
                    topic=None,
                    severity=None,
                )
            )
        self.assertEqual(result, 1)


# ---------------------------------------------------------------------------
# remove-item CLI
# ---------------------------------------------------------------------------


class TestRemoveItemCommand(_HookTestCase):
    def test_removes_entry(self):
        import smm_store

        uid = smm_store.add_item(self.smm_dir, "wisdom", "TDD always")
        result = smm_cli._cmd_remove_item(
            _make_cli_args(
                self.smm_dir,
                command="remove-item",
                item_id=uid,
            )
        )
        self.assertEqual(result, 0)
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 0)

    def test_error_on_missing_id(self):
        import io
        from unittest.mock import patch

        with patch("sys.stderr", new_callable=io.StringIO):
            result = smm_cli._cmd_remove_item(
                _make_cli_args(
                    self.smm_dir,
                    command="remove-item",
                    item_id="00000000-0000-4000-8000-000000000000",
                )
            )
        self.assertEqual(result, 1)


# ---------------------------------------------------------------------------
# promote-event CLI
# ---------------------------------------------------------------------------


class TestPromoteEventCommand(_HookTestCase):
    def test_creates_entry(self):
        import io
        from unittest.mock import patch

        event = make_event("goal", content="Ship v1")
        self._write_events([event])
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            result = smm_cli._cmd_promote_event(
                _make_cli_args(
                    self.smm_dir,
                    command="promote-event",
                    event_id=event["id"],
                    pillar=None,
                )
            )
        self.assertEqual(result, 0)
        import smm_store

        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["intent"]), 1)
        self.assertEqual(smm["intent"][0]["content"], "Ship v1")
        uid = out.getvalue().strip()
        self.assertEqual(smm["intent"][0]["id"], uid)

    def test_error_on_missing_event(self):
        import io
        from unittest.mock import patch

        self._write_events([])
        with patch("sys.stderr", new_callable=io.StringIO):
            result = smm_cli._cmd_promote_event(
                _make_cli_args(
                    self.smm_dir,
                    command="promote-event",
                    event_id="00000000-0000-4000-8000-000000000000",
                    pillar=None,
                )
            )
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()

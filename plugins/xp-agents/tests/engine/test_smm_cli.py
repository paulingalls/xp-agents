#!/usr/bin/env python3
"""Tests for smm_cli.py CLI behaviors.

Contract:
- `render` prints render_markdown(smm) to stdout.
- `section`, `has-section`, `save`, `get-event` behave as documented.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, make_event, run_cli

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"

_SMM_SIGNATURE = "# Shared Mental Model \u2014 Curated View"


def _seed_smm(smm_dir: Path) -> None:
    """Write a minimal valid SMM file so load_smm returns real content."""
    import smm_store
    from smm_schema import empty_smm

    data = empty_smm()
    smm_store.save_smm(smm_dir, data)


class TestRenderOutput(_SMMTestCase):
    """render prints markdown to stdout."""

    def test_render_prints_signature_header(self):
        _seed_smm(self.smm_dir)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)

    def test_render_without_seeded_smm(self):
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(_SMM_SIGNATURE, result.stdout)


class TestGetEvent(_SMMTestCase):
    """get-event retrieves individual events from events.jsonl."""

    def _append_event(self, event_type: str = "status", content: str = "test") -> str:
        """Append an event and return its ID."""
        event = make_event(event_type, content=content)
        events_file = self.smm_dir / "events.jsonl"
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event["id"]

    def test_get_event_exact_match(self):
        """get-event with full ID prints event JSON."""
        event_id = self._append_event(content="exact match test")
        result = run_cli(_CLI, ["get-event", event_id], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["id"], event_id)
        self.assertEqual(parsed["content"], "exact match test")

    def test_get_event_prefix_match(self):
        """get-event with 6-char prefix resolves to full event."""
        event_id = self._append_event(content="prefix test")
        prefix = event_id[:6]
        result = run_cli(_CLI, ["get-event", prefix], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["id"], event_id)

    def test_get_event_not_found(self):
        """get-event with nonexistent ID returns exit 1."""
        self._append_event()
        result = run_cli(_CLI, ["get-event", "000000000000"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr.lower())

    def test_get_event_ambiguous_prefix(self):
        """get-event with prefix matching multiple events returns exit 1."""
        # Write two events sharing a 4-char prefix but different full IDs.
        shared = "abcd"
        for suffix in ["00000001", "00000002"]:
            event = make_event("status", content="ambig")
            event["id"] = shared + suffix
            events_file = self.smm_dir / "events.jsonl"
            with events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        result = run_cli(_CLI, ["get-event", shared], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr.lower())


class TestSmmCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


class TestRiskIdRendering(_SMMTestCase):
    """Risk entries should render with [id] suffix for discoverability."""

    def test_risk_entries_show_id(self):
        """Risk items render as '- content [id]'."""
        import smm_store
        from smm_schema import empty_smm

        data = empty_smm()
        data["risks"] = [
            {
                "id": "aaa111bbb222",
                "content": "Quality gate broken",
                "source": "curated",
                "ts": "2026-01-01T00:00:00+00:00",
                "type": "concern",
                "severity": "problem",
            }
        ]
        smm_store.save_smm(self.smm_dir, data)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("Quality gate broken [aaa111bbb222]", result.stdout)

    def test_constraint_entries_no_id(self):
        """Non-risk pillar entries should NOT show IDs."""
        import smm_store
        from smm_schema import empty_smm

        data = empty_smm()
        data["constraints"] = [
            {
                "id": "ccc333ddd444",
                "content": "Use Postgres",
                "source": "seed",
                "ts": "2026-01-01T00:00:00+00:00",
                "type": "decision",
            }
        ]
        smm_store.save_smm(self.smm_dir, data)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("- Use Postgres", result.stdout)
        self.assertNotIn("ccc333ddd444", result.stdout)


if __name__ == "__main__":
    unittest.main()

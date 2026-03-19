#!/usr/bin/env python3
"""Tests for prompt nugget delta injection from events."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event


class TestPromptNugget(_HookTestCase):
    """Test prompt nugget delta injection from events."""

    def test_no_events_returns_none(self):
        """No events -> no nugget."""
        import prompt_nugget

        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """Recursion prevention for xp-* agents."""
        import prompt_nugget

        self._write_events([make_event("concern", content="Bug found")])
        result = prompt_nugget.run(
            {
                "session_id": "s1",
                "agent_id": "main",
                "agent_type": "xp-quality-review",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_shows_new_concern(self):
        """New concern appears in nugget."""
        import prompt_nugget

        self._write_events([make_event("concern", content="No tests for auth module")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("concern", result)
        self.assertIn("No tests for auth module", result)

    def test_shows_new_decision(self):
        """New decision appears in nugget."""
        import prompt_nugget

        self._write_events([make_event("decision", content="Use REST API")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("decision", result)
        self.assertIn("Use REST API", result)

    def test_status_events_excluded(self):
        """Status events are not signal types — excluded from nugget."""
        import prompt_nugget

        self._write_events([make_event("status", content="Working on auth")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_watermark_advances(self):
        """Second call with no new events returns None."""
        import prompt_nugget

        self._write_events([make_event("concern", content="Missing validation")])
        # First call sees the event
        result1 = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result1)
        # Second call — watermark advanced, nothing new
        result2 = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result2)

    def test_caps_at_five(self):
        """At most 5 items shown even with more new events."""
        import prompt_nugget

        self._write_events(
            [make_event("concern", content=f"Issue {i}") for i in range(8)]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.count("[concern]"), 5)


if __name__ == "__main__":
    unittest.main()

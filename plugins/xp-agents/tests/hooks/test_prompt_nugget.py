#!/usr/bin/env python3
"""Tests for prompt nugget delta injection from events."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)


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

        self._write_events([make_event(EVENT_TYPE_CONCERN, content="Bug found")])
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

        self._write_events(
            [make_event(EVENT_TYPE_CONCERN, content="No tests for auth module")]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("concern", result)
        self.assertIn("No tests for auth module", result)

    def test_shows_new_decision(self):
        """New decision appears in nugget."""
        import prompt_nugget

        self._write_events([make_event(EVENT_TYPE_DECISION, content="Use REST API")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("decision", result)
        self.assertIn("Use REST API", result)

    def test_status_events_excluded(self):
        """Status events are not signal types — excluded from nugget."""
        import prompt_nugget

        self._write_events([make_event(EVENT_TYPE_STATUS, content="Working on auth")])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_watermark_advances(self):
        """Second call with no new events returns None."""
        import prompt_nugget

        self._write_events(
            [make_event(EVENT_TYPE_CONCERN, content="Missing validation")]
        )
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

    def test_caps_at_three(self):
        """At most 3 items shown even with more new events."""
        import prompt_nugget

        self._write_events(
            [make_event(EVENT_TYPE_CONCERN, content=f"Issue {i}") for i in range(8)]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertEqual(result.count("[concern]"), 3)

    def test_priority_ordering(self):
        """Higher priority types shown before lower priority."""
        import prompt_nugget

        self._write_events(
            [
                make_event(EVENT_TYPE_DECISION, content="Use REST", topic="api"),
                make_event(EVENT_TYPE_DEBT, content="Missing tests", files=["a.py"]),
                make_event(EVENT_TYPE_CONCERN, content="Auth issue", severity="high"),
                make_event(EVENT_TYPE_ASSUMPTION, content="API is stable"),
            ]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        lines = result.strip().split("\n")[1:]  # skip header
        self.assertEqual(len(lines), 3)
        # Concern first, then assumption, then debt (decision dropped)
        self.assertIn("[concern]", lines[0])
        self.assertIn("[assumption]", lines[1])
        self.assertIn("[debt]", lines[2])

    def test_most_recent_within_same_priority(self):
        """Within same type, most recent event is shown."""
        import prompt_nugget

        self._write_events(
            [
                make_event(EVENT_TYPE_CONCERN, content="Old concern", severity="high"),
                make_event(
                    EVENT_TYPE_CONCERN, content="Middle concern", severity="high"
                ),
                make_event(
                    EVENT_TYPE_CONCERN, content="Newest concern", severity="high"
                ),
                make_event(
                    EVENT_TYPE_CONCERN, content="Latest concern", severity="high"
                ),
            ]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        lines = result.strip().split("\n")[1:]  # skip header
        self.assertEqual(len(lines), 3)
        # Most recent 3, newest first
        self.assertIn("Latest concern", lines[0])
        self.assertIn("Newest concern", lines[1])
        self.assertIn("Middle concern", lines[2])
        self.assertNotIn("Old concern", result)

    def test_mixed_priority_and_recency(self):
        """High priority type beats more recent low priority type."""
        import prompt_nugget

        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN, content="Early concern", severity="high"
                ),
                make_event(EVENT_TYPE_DECISION, content="Decision 1", topic="api"),
                make_event(EVENT_TYPE_DECISION, content="Decision 2", topic="db"),
                make_event(EVENT_TYPE_DECISION, content="Decision 3", topic="auth"),
                make_event(EVENT_TYPE_DEBT, content="Recent debt", files=["a.py"]),
            ]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        lines = result.strip().split("\n")[1:]
        self.assertEqual(len(lines), 3)
        # Concern beats debt beats decision despite recency
        self.assertIn("[concern]", lines[0])
        self.assertIn("[debt]", lines[1])
        self.assertIn("[decision]", lines[2])

    def test_resolved_concern_excluded(self):
        """Concern resolved by a later event should not appear in nugget."""
        import prompt_nugget

        concern = make_event(
            EVENT_TYPE_CONCERN, content="Test failures", severity="high"
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Tests pass now",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolution])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        # Concern is resolved — should not appear
        if result:
            self.assertNotIn("Test failures", result)

    def test_unresolved_concern_still_shown(self):
        """Unresolved concern should still appear."""
        import prompt_nugget

        self._write_events(
            [
                make_event(EVENT_TYPE_CONCERN, content="Real problem", severity="high"),
            ]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Real problem", result)

    def test_test_failure_concern_excluded(self):
        """Test failure concerns are filtered — already visible in tool output."""
        import prompt_nugget

        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN,
                    content="Test command failed (unittest): Exit code 1",
                    severity="medium",
                ),
                make_event(
                    EVENT_TYPE_CONCERN,
                    content="Test failures detected: 3 failed (unittest)",
                    severity="medium",
                ),
            ]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_lint_concern_excluded(self):
        """Lint concerns are filtered — already visible in edit hook output."""
        import prompt_nugget

        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN,
                    content="Lint errors in plugins/xp-agents/scripts/foo.py: 2 errors",
                    severity="medium",
                ),
            ]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_non_test_concern_still_shown(self):
        """Non-test/lint concerns still appear in nuggets."""
        import prompt_nugget

        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN,
                    content="Commit touches 12 files",
                    severity="medium",
                ),
            ]
        )
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Commit touches", result)

    def test_single_read_path(self):
        """Reads events.jsonl once via read_events_raw, never read_delta."""
        import _common
        import prompt_nugget
        import read_delta

        self._write_events(
            [make_event(EVENT_TYPE_CONCERN, content="X", severity="high")]
        )

        real_raw = _common.read_events_raw

        with (
            patch("_common.read_events_raw", side_effect=real_raw) as mock_raw,
            patch.object(read_delta, "read_delta") as mock_rd,
        ):
            result = prompt_nugget.run(
                {"session_id": "s1", "agent_id": "main"},
                smm_dir=self.smm_dir,
            )

        mock_rd.assert_not_called()
        self.assertEqual(
            mock_raw.call_count,
            1,
            f"read_events_raw called {mock_raw.call_count} times, expected 1",
        )
        assert result is not None
        self.assertIn("X", result)

    def test_resolution_chain_completeness(self):
        """Pre-watermark resolver still cascade-filters post-watermark dependents."""
        import prompt_nugget

        # Pre-watermark: root concern AND its resolver. A delta-only resolution
        # path would miss the resolver and fail to cascade-filter the dependent.
        old_concern = make_event(
            EVENT_TYPE_CONCERN, content="Old root concern", severity="high"
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Root concern fixed",
            working_on=[],
            metadata={"resolves": [old_concern["id"]]},
        )
        self._write_events([old_concern, resolver])
        prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )

        # Post-watermark: dependent (WEAK ref to pre-watermark root) + control.
        cascading_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Cascading dependent concern",
            severity="high",
            references=[old_concern["id"]],
        )
        # Independent post-watermark concern guarantees a non-None nugget so the
        # negative assertion on cascading_concern is meaningful.
        control = make_event(
            EVENT_TYPE_CONCERN, content="Independent live concern", severity="high"
        )
        self._write_events([old_concern, resolver, cascading_concern, control])

        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Independent live concern", result)
        self.assertNotIn("Cascading dependent concern", result)

    def test_resolved_debt_excluded(self):
        """Debt resolved by a later event should not appear."""
        import prompt_nugget

        debt = make_event(EVENT_TYPE_DEBT, content="Missing test", files=["a.py"])
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Test added",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        self._write_events([debt, resolution])
        result = prompt_nugget.run(
            {"session_id": "s1", "agent_id": "main"},
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("Missing test", result)


if __name__ == "__main__":
    unittest.main()

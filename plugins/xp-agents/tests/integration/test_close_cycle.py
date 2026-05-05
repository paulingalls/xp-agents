"""E2E integration capstone for sprint-063 / M-2 close-cycle stall fix.

Drives the marker-gated close-cycle pipeline that stories 001 and 002
jointly establish:

1. Close skill writes ``CLOSE_CYCLE_ACTIVE`` marker before
   ``/security-review`` (story-002 prose change).
2. Stop hook ``close_cycle_stop_gate`` blocks the agent while the
   marker is present (story-001 primitive).
3. ``subagent_stop._handle_close_reviewer_done`` consumes the marker
   when xp-close-reviewer finishes (story-001 primitive).
4. Bare ``/security-review`` outside a close cycle never trips the
   gate (the desired sidestep).

Sprint AC #4 (per-skill ordering pin) is satisfied by the existing
``_Step4_5SecurityIncludeTests`` mixin in ``tests/_close_fixtures.py``
which the four close-skill test classes already inherit — restating
it here would add a third place to update when heading conventions
evolve.
"""

from __future__ import annotations

from conftest import _IntegrationTestCase
from event_schema import EVENT_TYPE_STATUS


def _security_complete_event(event_id: str) -> dict:
    """SECURITY_COMPLETE seed event — same shape as review_cycle_done.py emits."""
    return {
        "id": event_id,
        "type": EVENT_TYPE_STATUS,
        "ts": "2026-05-05T16:00:00+00:00",
        "agent": "main",
        "content": "Security review complete",
        "metadata": {"action": "security_complete"},
        "working_on": [],
    }


class TestCloseCycleE2E(_IntegrationTestCase):
    """Marker-gated close-cycle pipeline: write → block → consume → release."""

    def test_positive_close_cycle_marker_lifecycle(self):
        """Full positive flow: marker write → block → security event →
        still block → close-reviewer subagent_stop drives consume →
        gate released (no stall).
        """
        import close_cycle_stop_gate
        import markers

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        )

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE))

        block_msg = close_cycle_stop_gate.run(
            {"agent_id": "main", "agent_type": "main"},
            self.smm_dir,
        )
        self.assertIsNotNone(block_msg)
        assert block_msg is not None
        self.assertIn("close-reviewer next", block_msg)

        # Security event arrives. Gate checks marker presence, not
        # events, so it must STILL block — close-reviewer hasn't run.
        self._seed_events([_security_complete_event("sec0000000001")])
        block_after_security = close_cycle_stop_gate.run(
            {"agent_id": "main", "agent_type": "main"},
            self.smm_dir,
        )
        self.assertIsNotNone(block_after_security)

        # close-reviewer subagent completes → consume marker.
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "xp-cr-1",
                "agent_type": "xp-close-reviewer",
                "last_assistant_message": "Review complete",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "subagent_stop should consume CLOSE_CYCLE_ACTIVE on xp-close-reviewer",
        )

        # Sprint AC #2 — "no stall": gate releases.
        pass_through = close_cycle_stop_gate.run(
            {"agent_id": "main", "agent_type": "main"},
            self.smm_dir,
        )
        self.assertIsNone(
            pass_through,
            "gate must pass through after marker consumed — no stall",
        )

    def test_negative_standalone_security_review_no_marker_no_block(self):
        """The desired sidestep: bare /security-review outside a close
        cycle never trips the gate. Manual invocations must remain
        cheap and uninterrupted.
        """
        import close_cycle_stop_gate
        import markers

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        )

        result = close_cycle_stop_gate.run(
            {"agent_id": "main", "agent_type": "main"},
            self.smm_dir,
        )
        self.assertIsNone(result)

    # No event-ordering test: marker-consume IS the close-reviewer
    # completion signal (no completion event emitted). The pass-through
    # assertion in the positive test above already proves the ordering.

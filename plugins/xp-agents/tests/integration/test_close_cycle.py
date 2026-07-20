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

The capstone drives marker writes through the ``markers.py`` CLI to
exercise its argparse + allowlist surface end-to-end. Production
preloads use a sibling wrapper that ultimately calls the same
primitive — both paths share it, so regressions in either reach
this suite.

Sprint AC #4 (per-skill ordering pin) is satisfied by the existing
``_Step4SecurityIncludeTests`` mixin in ``tests/_close_fixtures.py``
which the four close-skill test classes already inherit — restating
it here would add a third place to update when heading conventions
evolve.
"""

from __future__ import annotations

import json

from conftest import _MARKERS_PY, _IntegrationTestCase, run_cli
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


def _close_started_event(event_id: str) -> dict:
    """CLOSE_STARTED anchor — emitted by every close preload alongside the marker."""
    return {
        "id": event_id,
        "type": EVENT_TYPE_STATUS,
        "ts": "2026-05-05T15:00:00+00:00",
        "agent": "main",
        "content": "Close started",
        "metadata": {"action": "close_started"},
        "working_on": [],
    }


def _close_reviewer_complete_event(event_id: str) -> dict:
    """Reviewer-completion evidence — same shape subagent_stop now emits when
    xp-close-reviewer finishes (story-002 Part 1)."""
    return {
        "id": event_id,
        "type": EVENT_TYPE_STATUS,
        "ts": "2026-05-05T17:00:00+00:00",
        "agent": "xp-cr-1",
        "content": "Subagent complete",
        "metadata": {"action": "subagent_complete", "agent_type": "xp-close-reviewer"},
        "working_on": [],
    }


class TestCloseCycleE2E(_IntegrationTestCase):
    """Marker-gated close-cycle pipeline: write → block → consume → release."""

    def test_positive_close_cycle_marker_lifecycle(self):
        """Full positive flow under the evidence rule (story-002):
        marker write + close_started anchor → block → security event →
        still block (no reviewer yet) → close-reviewer subagent_stop emits
        completion evidence AND consumes the marker → gate released.

        Also proves the evidence path directly: even while the marker still
        lingers, a seeded reviewer-completion event after close_started
        releases the gate — the block honors evidence, not just marker
        presence (AC #2, #6).
        """
        import close_cycle_stop_gate
        import markers

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        )

        # Drive the marker write through the markers.py CLI surface to
        # exercise argparse + _CLI_ALLOWLIST end-to-end. The production
        # path (close-skill preloads) uses _preload_base.sh:write_marker
        # which calls markers.marker_write directly; both share the
        # underlying primitive but only the CLI path catches argparse /
        # allowlist regressions. The preload also emits a close_started
        # event — seed it as the current-cycle anchor.
        cli_result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(cli_result.returncode, 0, cli_result.stderr)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE))
        # _seed_events overwrites events.jsonl, so accumulate the log as the
        # cycle progresses — the close_started anchor must persist to every
        # subsequent read.
        log = [_close_started_event("closestart001")]
        self._seed_events(log)

        block_msg = close_cycle_stop_gate.run(
            {"agent_id": "main", "agent_type": "main"},
            self.smm_dir,
        )
        block_msg = self._assert_not_none(block_msg)
        self.assertIn("xp-close-reviewer", block_msg)

        # Security event arrives. No reviewer-completion evidence yet, so the
        # gate must STILL block — a close STARTED but no reviewer RAN.
        log.append(_security_complete_event("sec0000000001"))
        self._seed_events(log)
        block_after_security = close_cycle_stop_gate.run(
            {"agent_id": "main", "agent_type": "main"},
            self.smm_dir,
        )
        self.assertIsNotNone(block_after_security)

        # Evidence path (AC #2/#6): seed the reviewer-completion event that
        # subagent_stop now emits. Even with the marker still present, the
        # gate releases — it honors the evidence a reviewer ran this cycle.
        log.append(_close_reviewer_complete_event("reviewerdone1"))
        self._seed_events(log)
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "marker still lingers — evidence, not consume, drives this release",
        )
        release_on_evidence = close_cycle_stop_gate.run(
            {"agent_id": "main", "agent_type": "main"},
            self.smm_dir,
        )
        self.assertIsNone(
            release_on_evidence,
            "reviewer-completion evidence must release the lingering marker",
        )

        # Real subagent_stop path: close-reviewer completes → emits its own
        # completion evidence AND consumes the marker (Part 1). Gate releases
        # on the marker-absent path too — no stall.
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

    def test_real_stranding_vector_when_marker_unconsumed(self):
        """Stranding vector: close skill writes the marker via the CLI
        (real prose path), /security-review records its completion, but
        xp-close-reviewer never fires — so its SubagentStop never
        consumes the marker. The next Stop hook MUST block, otherwise
        the agent would silently auto-resume past Step 4.5.

        Pinning this scenario is the whole point of the capstone: the
        positive test proves consume-on-close-reviewer releases the
        gate; this test proves the gate STAYS shut when consume never
        happens. Together they bracket the marker lifecycle.
        """
        import markers

        # Drive marker write through the markers.py CLI to exercise
        # argparse + _CLI_ALLOWLIST end-to-end. Production preloads use
        # _preload_base.sh:write_marker (calls marker_write directly);
        # this CLI path stays exercised so allowlist/argparse drift
        # surfaces here.
        cli_result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(cli_result.returncode, 0, cli_result.stderr)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE))

        # Security review completes (the only event the close skill
        # records between marker-write and xp-close-reviewer). Marker
        # remains — review_cycle_done.py emits SECURITY_COMPLETE, it
        # does NOT consume the close-cycle marker.
        self._seed_events([_security_complete_event("strand0000001")])

        # xp-close-reviewer is intentionally NOT invoked here. This is
        # the stranding vector: the LLM forgets / a hook regression
        # prevents the SubagentStop from firing, etc.

        # Run the gate via subprocess so we exercise the real
        # block_output() JSON shape the harness sees (decision=block).
        result = self._run_script(
            "close_cycle_stop_gate.py",
            {"agent_id": "main", "agent_type": "main"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("Close cycle mid-flight", decision["reason"])
        self.assertIn("xp-close-reviewer", decision["reason"])

        # Marker is still present — the agent is stranded mid-cycle
        # until xp-close-reviewer's SubagentStop runs. THIS is the
        # load-bearing invariant: a marker that vanished without
        # xp-close-reviewer would silently auto-resume the cycle.
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "Stranding vector: marker must persist when xp-close-reviewer "
            "never fires — close-cycle MUST NOT auto-resume",
        )

    def test_stop_hook_active_bypass_with_young_marker_is_silent(self):
        """Young marker + stop_hook_active is a live in-flight cycle, NOT abandonment.

        stop_hook_active latches session-wide once any Stop hook returns a
        'reason', so by close time it is usually already True. A legitimate
        yield during the async Step 4b /code-review wait (CLOSE_CYCLE_ACTIVE
        still young) must therefore NOT be treated as abandonment: the gate
        records no concern, emits no bypass stderr, and leaves the young marker
        in place. The workflow-completion notification re-wakes the agent and
        the close finishes; the SessionStart sweep is the backstop if a young
        cycle is genuinely abandoned. Only an AGED marker records the loud
        bypass concern — unit coverage in
        tests/hooks/test_close_cycle_stop_gate_core.py.
        """
        import event_schema
        import markers
        import materialize
        from event_schema import EVENT_TYPE_CONCERN

        cli_result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(cli_result.returncode, 0, cli_result.stderr)

        result = self._run_script(
            "close_cycle_stop_gate.py",
            {
                "agent_id": "main",
                "agent_type": "main",
                "stop_hook_active": True,
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Pass-through, not block — defer-on-stop_hook_active stays for loop
        # prevention. No JSON decision payload on stdout.
        self.assertEqual(result.stdout.strip(), "")
        # No spurious bypass signal for a young in-flight cycle.
        self.assertNotIn("close-cycle gate bypassed", result.stderr.lower())

        events, _ = materialize.parse_events(self.smm_dir)
        bypass_concerns = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_CONCERN
            and e.get("metadata", {}).get("kind")
            == event_schema.CONCERN_KIND_CLOSE_CYCLE_BYPASS
        ]
        self.assertEqual(
            len(bypass_concerns),
            0,
            "young in-flight marker must NOT record a spurious abandonment concern",
        )

        # Young marker preserved — the cycle is still in-flight.
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "young marker must be preserved on bypass",
        )

    def test_stop_hook_active_without_marker_no_concern(self):
        """Sanity: stop_hook_active=True with NO marker is the normal
        case (most close cycles never bypass). Must not record a
        spurious concern.
        """
        import event_schema
        import materialize
        from event_schema import EVENT_TYPE_CONCERN

        result = self._run_script(
            "close_cycle_stop_gate.py",
            {
                "agent_id": "main",
                "agent_type": "main",
                "stop_hook_active": True,
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")
        self.assertNotIn("close-cycle gate bypassed", result.stderr.lower())

        events, _ = materialize.parse_events(self.smm_dir)
        bypass_concerns = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_CONCERN
            and e.get("metadata", {}).get("kind")
            == event_schema.CONCERN_KIND_CLOSE_CYCLE_BYPASS
        ]
        self.assertEqual(bypass_concerns, [])

    # No event-ordering test: marker-consume IS the close-reviewer
    # completion signal (no completion event emitted). The pass-through
    # assertion in the positive test above already proves the ordering.

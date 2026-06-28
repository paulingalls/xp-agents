#!/usr/bin/env python3
"""accept_terminal hook pin (sprint-104 story-005 Fix C).

The ACCEPT_IN_FLIGHT drain lived in review_cycle_done.py and matched
its targets via substring (`schedule`/`sprint-review` in target_name).
That breaks single-responsibility (review-cycle hook owning accept's
marker lifecycle) AND is a latent landmine: a future skill named
something like `something-schedule-related` would substring-match and
drain the marker early, re-exposing the accept gate (concern
c277a0730abe captured the same shape).

The extracted accept_terminal.py hook scopes the drain to an EXPLICIT
ALLOWLIST: exact match on `xp-schedule` / `xp-sprint-review` plus
their plugin-qualified forms (`xp-agents:xp-schedule` etc.). No
substring, no surprises.

Tests:
  * The two skill terminal dispatches still drain (parity).
  * Plugin-qualified forms still drain.
  * Unrelated skills do NOT drain.
  * The xp-sprint-reviewer AGENT name no longer drains (INVERSION of
    the previous "collision-pin" — the substring matcher used to drain
    it; the allowlist correctly doesn't).
  * Substring near-misses (`something-schedule-related`) do NOT drain.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import accept_terminal
import markers
from conftest import _HookTestCase, _make_agent_input, _make_skill_input


class TestAcceptTerminalHookDrainsOnAllowlist(_HookTestCase):
    """Explicit allowlist drains ACCEPT_IN_FLIGHT — no substring matching."""

    def test_schedule_skill_drains(self):
        """xp-schedule skill completion drains the marker (parity preserved)."""
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(_make_skill_input("xp-schedule"), smm_dir=self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))

    def test_sprint_review_skill_drains(self):
        """xp-sprint-review skill completion drains the marker (parity preserved)."""
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(_make_skill_input("xp-sprint-review"), smm_dir=self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))

    def test_plugin_qualified_schedule_drains(self):
        """Plugin-qualified `xp-agents:xp-schedule` also drains."""
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(
            _make_skill_input("xp-agents:xp-schedule"), smm_dir=self.smm_dir
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))

    def test_plugin_qualified_sprint_review_drains(self):
        """Plugin-qualified `xp-agents:xp-sprint-review` also drains."""
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(
            _make_skill_input("xp-agents:xp-sprint-review"), smm_dir=self.smm_dir
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))


class TestAcceptTerminalHookDoesNotDrainOnNearMisses(_HookTestCase):
    """Explicit allowlist guards: substring near-misses must NOT drain."""

    def test_sprint_reviewer_agent_does_not_drain(self):
        """INVERSION of the previous substring behavior.

        The old review_cycle_done.py substring matcher drained when the
        xp-sprint-reviewer AGENT name arrived via tool_input.subagent_type
        (because `sprint-review in xp-sprint-reviewer`). The allowlist
        correctly does NOT match — the reviewer agent is not a terminal
        dispatch from accept; only the skill is. (The xp-sprint-reviewer
        agent is in fact spawned BY the /xp-sprint-review skill, so the
        skill's allowlist hit already drains the marker; the redundant
        agent-name match was unnecessary AND a latent leak.)
        """
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(
            _make_agent_input("xp-sprint-reviewer"), smm_dir=self.smm_dir
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT),
            "xp-sprint-reviewer agent name must NOT drain — only the skill is",
        )

    def test_substring_near_miss_schedule_does_not_drain(self):
        """A skill named `something-schedule-related` must NOT drain.

        This is the latent landmine concern c277a0730abe described:
        a future skill whose name contains 'schedule' would substring-
        match the legacy code and drain the accept marker early,
        re-exposing the accept gate. The allowlist forecloses this.
        """
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(
            _make_skill_input("xp-something-schedule-related"), smm_dir=self.smm_dir
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT),
            "near-miss substring `schedule` must NOT drain under the allowlist",
        )

    def test_substring_near_miss_sprint_review_does_not_drain(self):
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(
            _make_skill_input("xp-sprint-reviewing-tools"), smm_dir=self.smm_dir
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT),
            "near-miss substring `sprint-review` must NOT drain under allowlist",
        )

    def test_other_plugin_qualified_schedule_does_not_drain(self):
        """sprint-close finding A6 (accept_terminal leg): only `xp-agents:`
        is our namespace. A third-party plugin's `otherplugin:xp-schedule`
        must NOT drain — they ship their own /xp-schedule and our marker is
        scoped to our flow."""
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(
            _make_skill_input("otherplugin:xp-schedule"), smm_dir=self.smm_dir
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT),
            "third-party plugin's xp-schedule must NOT drain our marker",
        )

    def test_unrelated_skill_does_not_drain(self):
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        accept_terminal.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT),
            "unrelated skill must NOT drain",
        )


class TestAcceptTerminalHookIdempotent(_HookTestCase):
    """The drain is a no-op when the marker is unarmed (kickoff-tail case)."""

    def test_unarmed_consume_is_noop(self):
        """The kickoff-tail /xp-schedule runs with no armed marker; no error."""
        # No marker armed.
        result = accept_terminal.run(
            _make_skill_input("xp-schedule"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))


if __name__ == "__main__":
    unittest.main()

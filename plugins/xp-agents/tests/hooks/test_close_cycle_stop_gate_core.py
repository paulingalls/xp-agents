#!/usr/bin/env python3
"""Tests for close_cycle_stop_gate.py — base block/bypass behavior + registration.

Split from test_close_cycle_stop_gate.py by test-class grouping: this file
covers the base gate (block when CLOSE_CYCLE_ACTIVE is present, pass-through
otherwise, xp-agent/AskUserQuestion/stop_hook_active deferrals, the
abandonment-bypass concern recording) and the hooks.json Stop-array
registration order. See test_close_cycle_stop_gate_deferral.py for the
evidence-based release and the age-bounded Step 4b mid-cycle defer.

Mirrors sprint_stop_gate.py shape but with a single block trigger:
the CLOSE_CYCLE_ACTIVE marker. ASKING_USER deferral preserves
AskUserQuestion dialogue flow; the review-mid-cycle deferral applies
only inside the close /code-review's Step 4b window (markers.review_mid_cycle)
so the close-reviewer nudge waits for the async workflow — otherwise the
close cycle wants to block mid-cycle. Teammates deferral is NOT applied.
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _hooks_json import HooksJsonTestCase
from conftest import _HookTestCase, _make_stop_input


class TestCloseCycleStopGate(_HookTestCase):
    """Block when CLOSE_CYCLE_ACTIVE marker is present, else pass-through."""

    def test_blocks_when_marker_present(self):
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_block_message_names_all_three_close_phases(self):
        # The mid-flight nudge must name every step the agent should run, in
        # the canonical close-skill order: /security-review (Step 4),
        # /code-review high (Step 4b, gated on RUN_FULL_CODE_REVIEW=true),
        # then xp-close-reviewer (Step 4.5). The earlier message omitted
        # /code-review high, so an agent re-entering the close cycle could
        # read it as "skip Step 4b" — but post-merge there's no diff, so
        # /code-review must run pre-merge or never. Order matters because the
        # agent follows the nudge sequentially: /security-review precedes
        # /code-review in the close skill, and the close-reviewer comes last.
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("/code-review", result)
        self.assertIn("/security-review", result)
        self.assertIn("xp-close-reviewer", result)
        # `/code-review high` is load-bearing — bare `/code-review` would
        # default to a lower effort and skip the full pre-merge workflow.
        self.assertIn("/code-review high", result)
        # Canonical order: security-review (Step 4) → code-review (Step 4b)
        # → close-reviewer (Step 4.5). Substring positions enforce it.
        sec = result.index("/security-review")
        code = result.index("/code-review")
        reviewer = result.index("xp-close-reviewer")
        self.assertLess(
            sec,
            code,
            "/security-review (Step 4) must precede /code-review (Step 4b)",
        )
        self.assertLess(
            code,
            reviewer,
            "/code-review (Step 4b) must precede xp-close-reviewer (Step 4.5)",
        )

    def test_no_block_when_marker_absent(self):
        import close_cycle_stop_gate

        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_block_when_xp_agent(self):
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(
            _make_stop_input(agent_type="xp-nav"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_no_block_when_stop_hook_active(self):
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_bypass_records_high_severity_concern_with_recovery_hint(self):
        """Bypass (stop_hook_active=True + marker) must escalate to severity=high
        and include a recovery instruction in both the concern content and
        stderr — so xp-end-session's high-severity 'watch' surfaces it next
        session and the terminating agent leaves a visible breadcrumb on
        stderr right now. Only an AGED marker (truly abandoned) records; a
        young in-flight marker is left alone (see the mid-cycle test)."""
        import os

        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate = close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC + 60
        old = marker_path.stat().st_mtime - backdate
        os.utime(marker_path, (old, old))
        stderr_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf):
            result = close_cycle_stop_gate.run(
                _make_stop_input(stop_hook_active=True),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1, "exactly one bypass concern expected")
        concern = concerns[0]
        self.assertEqual(concern["severity"], "high")
        self.assertIn("Recovery:", concern["content"])
        self.assertIn("xp-close-reviewer", concern["content"])

        stderr = stderr_buf.getvalue()
        self.assertIn("Recovery:", stderr)
        self.assertIn("xp-close-reviewer", stderr)

    def test_bypass_keeps_young_marker_and_records_no_concern(self):
        """Young marker (< threshold) on bypass is a live in-flight cycle: the
        marker stays put AND no abandonment concern is recorded — recording one
        for a young (e.g. Step 4b async-wait) yield is a false positive. The
        SessionStart sweep is the backstop if a young cycle is truly abandoned."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )

        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "young marker must be preserved on bypass",
        )
        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(
            len(concerns),
            0,
            "young in-flight marker must NOT record an abandonment concern",
        )

    def test_bypass_consumes_old_marker(self):
        """Old marker (>= threshold) is consumed — cycle empirically
        abandoned, avoids re-firing the gate on every subsequent Stop."""
        import os

        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate_sec = close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC + 60
        old_mtime = marker_path.stat().st_mtime - backdate_sec
        os.utime(marker_path, (old_mtime, old_mtime))

        close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "old marker must be consumed on bypass",
        )
        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)

    def test_bypass_handles_stat_race_without_crashing(self):
        """If the marker vanishes between marker_exists() and stat()
        (theoretical race; rare in practice), the gate still records the
        concern + stderr but skips the consume cleanly. Simulated by
        making marker_exists lie 'present' for CLOSE_CYCLE_ACTIVE only
        (ASKING_USER must still return False) — stat() then raises
        FileNotFoundError because no file was written to disk."""
        from unittest.mock import patch

        import close_cycle_stop_gate
        import markers

        def _selective_marker_exists(_smm_dir, marker, _agent_id=""):
            return marker == markers.CLOSE_CYCLE_ACTIVE

        with patch(
            "close_cycle_stop_gate.markers.marker_exists",
            side_effect=_selective_marker_exists,
        ):
            close_cycle_stop_gate.run(
                _make_stop_input(stop_hook_active=True),
                smm_dir=self.smm_dir,
            )

        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)

    def test_no_block_during_step_4b_review_mid_cycle(self):
        """Fix 1: during Step 4b the close /code-review workflow is in flight
        (simplify_done set when it launched, quality_review_done not yet set).
        The gate must NOT push xp-close-reviewer — Step 4.5 comes AFTER the
        async workflow returns and /xp-quality-review (consume-findings)
        validates its findings. Defer (return None) so the agent yields and is
        re-woken by the workflow-completion notification.

        Same-key keying: the flag is written under the SAME agent_id the gate
        resolves via identity.resolve_agent_id — mirroring sprint_stop_gate."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_blocks_after_quality_review_done(self):
        """Fix 1 regression: once /xp-quality-review sets quality_review_done
        (Step 4b complete) the cycle is no longer mid-flight — the gate
        resumes nudging xp-close-reviewer."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.write_review_cycle(
            self.smm_dir,
            agent_id,
            {
                "simplify_done": True,
                "quality_review_done": True,
                "last_review_commit": "abc123",
            },
        )

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_blocks_before_step_4b_neither_flag(self):
        """Fix 1 regression: before Step 4b (no review flags set) the cycle is
        not mid-flight — the gate still nudges. Only the in-flight window is
        suppressed."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        # quality_review_done WITHOUT simplify_done is a completed self-find
        # review, not mid-cycle — must NOT suppress (the load-bearing invariant
        # shared with sprint_stop_gate).
        markers.set_review_flag(self.smm_dir, agent_id, "quality_review_done")

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_bypass_during_step_4b_records_no_spurious_concern(self):
        """A stop_hook_active latch during the Step 4b window (young marker,
        simplify_done set, agent yielding for the async /code-review) must NOT
        record an abandonment concern — that was the false positive: stop_hook_active
        is usually already latched session-wide by close time, so a legitimate
        Step 4b yield would otherwise log a spurious high-severity 'close
        abandoned' concern even though the workflow notification re-wakes the
        agent and the close finishes. The young marker is left intact."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input(stop_hook_active=True)
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)

        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(
            len(concerns), 0, "young Step 4b yield must not record a spurious concern"
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "young marker preserved through the Step 4b yield",
        )

    # The concern-budget pin moved with the content it bounds: three detectors
    # now record this same abandonment from one shared constant, so the pin
    # lives beside that constant in tests/hooks/test_close_cycle_abandonment.py.
    # Leaving a copy here would bound whichever spelling this module still
    # happened to import.

    def test_no_block_when_asking_user(self):
        """Defer when AskUserQuestion dialogue is in flight."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.marker_write(self.smm_dir, markers.ASKING_USER, "1")
        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_passes_through(self):
        import close_cycle_stop_gate

        result = close_cycle_stop_gate.run(
            _make_stop_input(), smm_dir=Path("/nonexistent/smm")
        )
        self.assertIsNone(result)


class TestGateCoversOnlyTheSecurityBearingCloses(_HookTestCase):
    """Which closes this gate is FOR, pinned so the gap is not "fixed".

    The gate's block message tells the agent to run a security review and the
    broad code review, and its only release is evidence that the branch-close
    reviewer ran. Story-close does neither: it skips the security review (the
    enclosing sprint-close covers its diff), and under story cadence its review
    path is the full per-story review cycle, which never forks that reviewer.

    So story-close's preload deliberately does not arm this gate. Read without
    this pin, that looks like an oversight next to the other three preloads —
    and "fixing" it would arm a gate that could never release: it would block
    until the marker aged out, then record a high-severity "close abandoned"
    concern against a close that ran exactly the review it was supposed to.
    """

    _MODES = ("sprint", "plan", "free")

    def _preload(self, mode: str) -> str:
        return (
            Path(__file__).parents[2]
            / "skills"
            / f"xp-{mode}-close"
            / "scripts"
            / "preload.sh"
        ).read_text()

    def test_story_close_does_not_arm_the_gate(self):
        self.assertNotIn(
            "write_marker CLOSE_CYCLE_ACTIVE",
            self._preload("story"),
            "story-close must NOT arm the close-cycle Stop gate: the gate's "
            "only release is a branch-close-reviewer completion, which the "
            "story review path deliberately does not produce, so the gate "
            "would block until the marker aged out and then record a false "
            "abandonment concern",
        )

    def test_the_other_three_closes_do_arm_it(self):
        for mode in self._MODES:
            with self.subTest(mode=mode):
                self.assertIn("write_marker CLOSE_CYCLE_ACTIVE", self._preload(mode))

    def test_the_recovery_message_names_exactly_those_three(self):
        """`_BYPASS_RECOVERY` already names /xp-{sprint,plan,free}-close and is
        correct as written — this pins it against a well-meant edit that adds
        story to the list for symmetry with the other close skills."""
        import close_cycle_stop_gate

        recovery = close_cycle_stop_gate._BYPASS_RECOVERY
        self.assertIn("{sprint,plan,free}", recovery)
        self.assertNotIn("story", recovery)

    def test_the_docstring_says_which_closes_are_covered(self):
        """The prose a future reader consults before touching the gap above."""
        import close_cycle_stop_gate

        doc = (close_cycle_stop_gate.__doc__ or "").lower()
        self.assertIn("story", doc)
        self.assertIn("security", doc)


class TestCloseCycleStopGateRegistration(HooksJsonTestCase):
    """Hook is registered in hooks.json Stop array between sprint_stop_gate
    and housekeeping_stop_gate."""

    def test_registered_in_hooks_json(self):
        stop_entries = self.data["hooks"].get("Stop", [])
        self.assertEqual(len(stop_entries), 1, "Single Stop entry expected")
        commands = [h.get("command", "") for h in stop_entries[0].get("hooks", [])]
        names = [
            Path(next(t for t in c.split() if t.endswith(".py"))).name for c in commands
        ]
        self.assertIn("close_cycle_stop_gate.py", names)
        i_close = names.index("close_cycle_stop_gate.py")
        i_sprint = names.index("sprint_stop_gate.py")
        i_housekeeping = names.index("housekeeping_stop_gate.py")
        self.assertLess(i_sprint, i_close)
        self.assertLess(i_close, i_housekeeping)


if __name__ == "__main__":
    unittest.main()

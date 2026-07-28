#!/usr/bin/env python3
"""The hook-liveness heartbeat marker and its staleness predicate.

Split from the concurrency and CLI suites in
test_hook_heartbeat_liveness.py to stay under the 500-line cap.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import hook_liveness
import marker_names
import markers
import session_markers
from _heartbeat_fixtures import env as _env
from conftest import _HookTestCase


class TestHeartbeatMarkerDefinition(_HookTestCase):
    """The marker name and MarkerDef both consumers resolve through."""

    def test_marker_name_is_a_well_formed_dotfile(self):
        self.assertEqual(marker_names.HOOK_HEARTBEAT, ".hook-heartbeat")

    def test_marker_def_is_json_and_not_agent_scoped(self):
        self.assertEqual(markers.HOOK_HEARTBEAT.name, marker_names.HOOK_HEARTBEAT)
        self.assertEqual(markers.HOOK_HEARTBEAT.content_type, "json")
        self.assertFalse(markers.HOOK_HEARTBEAT.agent_scoped)

    def test_heartbeat_is_not_swept_at_session_start(self):
        """The sweep runs BEFORE markers are written on a fresh session start.

        A heartbeat consumed there and rewritten moments later is churn, and
        an ordering change would erase the signal this feature exists to read.

        Both halves are load-bearing. The per-session file can never appear in
        the sweep tuple, so that assertion alone cannot fail; the shared
        no-session-id marker CAN be added to it, and that is the regression
        worth pinning.
        """
        self.assertNotIn(markers.HOOK_HEARTBEAT, session_markers._STALE_SESSION_MARKERS)
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")):
            hook_liveness.write_heartbeat(self.smm_dir)
        session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, hook_liveness.heartbeat_marker("sess-a")
            )
        )


class TestPredicateWithoutMarker(_HookTestCase):
    def test_absent_marker_reports_not_live(self):
        result = hook_liveness.check_liveness(self.smm_dir)
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_NO_MARKER)

    def test_absent_marker_reason_names_the_likely_cause(self):
        """A refusal must diagnose, not just report a missing file."""
        reason = hook_liveness.check_liveness(self.smm_dir).reason
        self.assertIn("not loaded", reason)


class TestPredicateSessionAndFreshness(_HookTestCase):
    """Session identity is the primary signal; age is the backstop."""

    HOST_VAR = "CLAUDE_CODE_SESSION_ID"
    NOW = 1_000_000.0

    def _write(self, session_id: str, at: float) -> None:
        with patch.dict(os.environ, _env(**{self.HOST_VAR: session_id})):
            hook_liveness.write_heartbeat(self.smm_dir, now=at)

    def test_matching_id_and_fresh_is_live(self):
        self._write("sess-a", self.NOW)
        with patch.dict(os.environ, _env(**{self.HOST_VAR: "sess-a"})):
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW + 60)
        self.assertTrue(result.live, result.reason)
        self.assertEqual(result.code, hook_liveness.CODE_LIVE)

    def test_differing_id_is_not_live_however_fresh(self):
        """The restart case: a new session inherits a heartbeat written
        seconds ago by the previous one. Freshness alone would call that
        live while nothing is enforcing."""
        self._write("sess-old", self.NOW)
        with patch.dict(os.environ, _env(**{self.HOST_VAR: "sess-new"})):
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW + 1)
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_SESSION_MISMATCH)

    def test_matching_id_past_threshold_is_stale(self):
        self._write("sess-a", self.NOW)
        with patch.dict(os.environ, _env(**{self.HOST_VAR: "sess-a"})):
            result = hook_liveness.check_liveness(
                self.smm_dir, now=self.NOW + hook_liveness.STALE_AFTER_SECONDS + 1
            )
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_STALE)

    def test_each_verdict_carries_a_distinct_reason(self):
        self._write("sess-a", self.NOW)
        with patch.dict(os.environ, _env(**{self.HOST_VAR: "sess-a"})):
            live = hook_liveness.check_liveness(self.smm_dir, now=self.NOW)
            stale = hook_liveness.check_liveness(
                self.smm_dir, now=self.NOW + hook_liveness.STALE_AFTER_SECONDS
            )
        with patch.dict(os.environ, _env(**{self.HOST_VAR: "sess-b"})):
            mismatch = hook_liveness.check_liveness(self.smm_dir, now=self.NOW)
        absent = hook_liveness.check_liveness(Path(self.smm_dir) / "nowhere")
        reasons = [live.reason, stale.reason, mismatch.reason, absent.reason]
        self.assertEqual(len(set(reasons)), len(reasons), reasons)

    def test_marker_payload_carries_id_version_and_timestamp(self):
        self._write("sess-a", self.NOW)
        data = markers.marker_read(
            self.smm_dir, hook_liveness.heartbeat_marker("sess-a")
        )
        assert isinstance(data, dict)
        self.assertEqual(data["session_id"], "sess-a")
        self.assertEqual(data["written_at"], self.NOW)
        self.assertTrue(data["plugin_version"])

    def test_hooks_may_pass_the_session_id_they_were_handed(self):
        """A hook knows its session id from its own input payload — a more
        direct source than the environment."""
        with patch.dict(os.environ, _env(**{self.HOST_VAR: "from-env"})):
            hook_liveness.write_heartbeat(
                self.smm_dir, session_id="from-payload", now=self.NOW
            )
        data = markers.marker_read(
            self.smm_dir, hook_liveness.heartbeat_marker("from-payload")
        )
        assert isinstance(data, dict)
        self.assertEqual(data["session_id"], "from-payload")


class TestDegradesToTimeOnly(_HookTestCase):
    """An unfamiliar host exposes no session id. It must not be bricked."""

    NOW = 1_000_000.0

    def setUp(self):
        super().setUp()
        with patch.dict(os.environ, _env()):
            hook_liveness.write_heartbeat(self.smm_dir, now=self.NOW)

    def test_no_discoverable_id_and_fresh_is_live(self):
        with patch.dict(os.environ, _env()):
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW + 60)
        self.assertTrue(result.live, result.reason)

    def test_a_stale_shared_marker_still_consults_the_siblings(self):
        """The absent-vs-stale asymmetry.

        Absence already consulted siblings; staleness did not, though the
        argument is identical — a hook handed a payload id writes a
        per-session file this reader cannot name, so the shared marker goes
        stale while hooks are demonstrably running.
        """
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="live-one")):
            hook_liveness.write_heartbeat(
                self.smm_dir, now=self.NOW + hook_liveness.STALE_AFTER_SECONDS
            )
        with patch.dict(os.environ, _env()):
            result = hook_liveness.check_liveness(
                self.smm_dir, now=self.NOW + hook_liveness.STALE_AFTER_SECONDS + 60
            )
        self.assertTrue(result.live, result.reason)

    def test_no_discoverable_id_still_honours_the_threshold(self):
        with patch.dict(os.environ, _env()):
            result = hook_liveness.check_liveness(
                self.smm_dir, now=self.NOW + hook_liveness.STALE_AFTER_SECONDS
            )
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_STALE)


class TestAgeBoundary(_HookTestCase):
    """`now` is injectable so story-004's capstone need not wait out hours."""

    NOW = 1_000_000.0

    def setUp(self):
        super().setUp()
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")):
            hook_liveness.write_heartbeat(self.smm_dir, now=self.NOW)

    def _at(self, age: float) -> hook_liveness.Liveness:
        # The env patch stays INSIDE the test body. Entered from setUp via
        # enterContext/addCleanup it would exit AFTER tearDown, and
        # `patch.dict`'s exit restores the whole mapping from its entry
        # snapshot — reinstating the SMM_DIR that `_SMMTestCase.tearDown`
        # had just popped, pointed at a deleted temp dir, for every later
        # test in the worker.
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")):
            return hook_liveness.check_liveness(self.smm_dir, now=self.NOW + age)

    def test_one_second_inside_the_threshold_is_live(self):
        self.assertTrue(self._at(hook_liveness.STALE_AFTER_SECONDS - 1).live)

    def test_exactly_at_the_threshold_is_stale(self):
        self.assertFalse(self._at(hook_liveness.STALE_AFTER_SECONDS).live)

    def test_threshold_is_a_patchable_module_constant(self):
        """Story-004 shortens the threshold rather than sleeping through it."""
        with patch.object(hook_liveness, "STALE_AFTER_SECONDS", 10):
            self.assertTrue(self._at(9).live)
            self.assertFalse(self._at(11).live)

    def test_default_threshold_tolerates_a_long_pause_between_prompts(self):
        """Loose on purpose: a check that false-refuses gets switched off."""
        self.assertGreaterEqual(hook_liveness.STALE_AFTER_SECONDS, 4 * 60 * 60)

    def test_a_far_future_timestamp_is_not_live(self):
        """The window is bounded at BOTH ends.

        `age >= STALE_AFTER_SECONDS` alone reads a NEGATIVE age as fresh
        forever, so one wall-clock step backwards (NTP correction, VM snapshot
        restore) or a millisecond timestamp where seconds were meant would
        report "live" for the rest of the session — even after the runtime died,
        which is the silent unenforcement this module exists to detect. The
        housekeeping in-flight record bounds the same shared helper for exactly
        this reason; this leg had it only at the old end.
        """
        result = self._at(-(hook_liveness.FUTURE_SKEW_GRACE_SECONDS + 1))
        self.assertFalse(result.live, result.reason)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_a_millisecond_timestamp_is_not_live(self):
        """The cheapest real way to land a future timestamp."""
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")):
            hook_liveness.write_heartbeat(self.smm_dir, now=self.NOW * 1000)
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW)
        self.assertFalse(result.live, result.reason)

    def test_ordinary_clock_slew_is_still_live(self):
        """The cost is bounded on purpose: refusing a working session is the
        failure that gets a liveness check switched off, and a heartbeat inside
        the grace is rewritten by the session's next tool call anyway."""
        result = self._at(-(hook_liveness.FUTURE_SKEW_GRACE_SECONDS - 1))
        self.assertTrue(result.live, result.reason)
        self.assertNotIn("-", result.reason.split("heartbeat ")[-1])


class TestPredicateOnUnusableMarker(_HookTestCase):
    """`marker_read` already returns None for a symlink and for corrupt
    JSON. These assert the predicate does not undo that guarantee, and that
    it separates "cannot tell" from "told, and the answer is no"."""

    SESSION = "sess-a"

    def _marker_path(self) -> Path:
        return markers.marker_path(
            self.smm_dir, hook_liveness.heartbeat_marker(self.SESSION)
        )

    def _check(self) -> hook_liveness.Liveness:
        # The env patch stays INSIDE the call, for the reason spelled out in
        # TestAgeBoundary._at: entered from setUp it would exit after
        # tearDown and reinstate the SMM_DIR tearDown had just popped,
        # poisoning every later test in this xdist worker.
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.SESSION)):
            return hook_liveness.check_liveness(self.smm_dir)

    def test_corrupt_json_reports_not_live_without_raising(self):
        self._marker_path().write_text("{not json", encoding="utf-8")
        result = self._check()
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_symlinked_marker_reports_not_live_without_raising(self):
        real = self.smm_dir / "planted.json"
        real.write_text('{"session_id": "x", "written_at": 0}', encoding="utf-8")
        self._marker_path().symlink_to(real)
        result = self._check()
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_non_numeric_timestamp_reports_not_live_without_raising(self):
        self._marker_path().write_text(
            '{"session_id": "x", "written_at": "yesterday"}', encoding="utf-8"
        )
        result = self._check()
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_boolean_timestamp_reports_not_live(self):
        """`bool` is an `int` subclass, so a plain isinstance check admits it."""
        self._marker_path().write_text(
            '{"session_id": null, "written_at": true}', encoding="utf-8"
        )
        result = self._check()
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_non_finite_timestamp_reports_not_live(self):
        """JSON admits NaN/Infinity, and neither compares True against the
        threshold — on a fail-CLOSED check that silently reads as live."""
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                self._marker_path().write_text(
                    f'{{"session_id": null, "written_at": {literal}}}',
                    encoding="utf-8",
                )
                result = self._check()
                self.assertFalse(result.live)
                self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_out_of_range_timestamp_reports_not_live(self):
        """A JSON int too large to become a float must read as corrupt, not
        raise out of a predicate whose whole job is to return a verdict."""
        self._marker_path().write_text(
            f'{{"session_id": null, "written_at": {"1" * 400}}}', encoding="utf-8"
        )
        result = self._check()
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_unreadable_is_not_conflated_with_absent(self):
        """Both refuse, but only one of them means "no hook has run"."""
        absent = self._check()
        self._marker_path().write_text("{not json", encoding="utf-8")
        unreadable = self._check()
        self.assertNotEqual(absent.code, unreadable.code)
        self.assertNotEqual(absent.reason, unreadable.reason)

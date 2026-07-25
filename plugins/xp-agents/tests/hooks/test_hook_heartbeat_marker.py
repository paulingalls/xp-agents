#!/usr/bin/env python3
"""Tests for the hook-liveness heartbeat marker and its staleness predicate.

The primitive nothing calls yet: hooks will refresh the marker, a skill
preload will consume the verdict. Both consumers land later, so this suite
is the only pressure on the seam.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import hook_liveness
import marker_names
import markers
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
        """
        self.assertNotIn(markers.HOOK_HEARTBEAT, markers._STALE_SESSION_MARKERS)


class TestPredicateWithoutMarker(_HookTestCase):
    def test_absent_marker_reports_not_live(self):
        result = hook_liveness.check_liveness(self.smm_dir)
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_NO_MARKER)

    def test_absent_marker_reason_names_the_likely_cause(self):
        """A refusal must diagnose, not just report a missing file."""
        reason = hook_liveness.check_liveness(self.smm_dir).reason
        self.assertIn("not loaded", reason)


# Every environment candidate pinned to "", which the chain reads as absent.
# Tests opt back in by overriding one. Without this a developer running the
# suite from inside a live harness would inherit a real session id.
_NO_SESSION_ENV = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")


def _env(**overrides: str) -> dict[str, str]:
    return {**_NO_SESSION_ENV, **overrides}


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
        data = markers.marker_read(self.smm_dir, markers.HOOK_HEARTBEAT)
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
        data = markers.marker_read(self.smm_dir, markers.HOOK_HEARTBEAT)
        assert isinstance(data, dict)
        self.assertEqual(data["session_id"], "from-payload")


class TestDegradesToTimeOnly(_HookTestCase):
    """An unfamiliar host exposes no session id. It must not be bricked."""

    NOW = 1_000_000.0

    def setUp(self):
        super().setUp()
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="written-by")):
            hook_liveness.write_heartbeat(self.smm_dir, now=self.NOW)

    def test_no_discoverable_id_and_fresh_is_live(self):
        with patch.dict(os.environ, _env()):
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW + 60)
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
        self.enterContext(patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")))

    def _at(self, age: float) -> hook_liveness.Liveness:
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


class TestPredicateOnUnusableMarker(_HookTestCase):
    """`marker_read` already returns None for a symlink and for corrupt
    JSON. These assert the predicate does not undo that guarantee, and that
    it separates "cannot tell" from "told, and the answer is no"."""

    def _marker_path(self) -> Path:
        return markers.marker_path(self.smm_dir, markers.HOOK_HEARTBEAT)

    def test_corrupt_json_reports_not_live_without_raising(self):
        self._marker_path().write_text("{not json", encoding="utf-8")
        result = hook_liveness.check_liveness(self.smm_dir)
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_symlinked_marker_reports_not_live_without_raising(self):
        real = self.smm_dir / "planted.json"
        real.write_text('{"session_id": "x", "written_at": 0}', encoding="utf-8")
        self._marker_path().symlink_to(real)
        result = hook_liveness.check_liveness(self.smm_dir)
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_non_numeric_timestamp_reports_not_live_without_raising(self):
        self._marker_path().write_text(
            '{"session_id": "x", "written_at": "yesterday"}', encoding="utf-8"
        )
        result = hook_liveness.check_liveness(self.smm_dir)
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_UNREADABLE)

    def test_unreadable_is_not_conflated_with_absent(self):
        """Both refuse, but only one of them means "no hook has run"."""
        absent = hook_liveness.check_liveness(self.smm_dir)
        self._marker_path().write_text("{not json", encoding="utf-8")
        unreadable = hook_liveness.check_liveness(self.smm_dir)
        self.assertNotEqual(absent.code, unreadable.code)
        self.assertNotEqual(absent.reason, unreadable.reason)


class TestSessionIdChain(_HookTestCase):
    """Adding a harness must be a data change, not a redesign."""

    def test_first_candidate_wins(self):
        first, second = hook_liveness.SESSION_ID_ENV_CANDIDATES[:2]
        with patch.dict(os.environ, _env(**{first: "one", second: "two"})):
            self.assertEqual(hook_liveness.resolve_session_id(), "one")

    def test_falls_through_to_a_later_candidate(self):
        second = hook_liveness.SESSION_ID_ENV_CANDIDATES[1]
        with patch.dict(os.environ, _env(**{second: "two"})):
            self.assertEqual(hook_liveness.resolve_session_id(), "two")

    def test_empty_value_counts_as_absent(self):
        with patch.dict(os.environ, _env()):
            self.assertIsNone(hook_liveness.resolve_session_id())


if __name__ == "__main__":
    unittest.main()

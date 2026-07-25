#!/usr/bin/env python3
"""Tests for the hook-liveness heartbeat marker and its staleness predicate.

The primitive nothing calls yet: hooks will refresh the marker, a skill
preload will consume the verdict. Both consumers land later, so this suite
is the only pressure on the seam.
"""

import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

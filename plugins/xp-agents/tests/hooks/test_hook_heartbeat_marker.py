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

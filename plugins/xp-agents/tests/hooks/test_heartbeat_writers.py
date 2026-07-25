#!/usr/bin/env python3
"""The two hooks that write the hook-liveness heartbeat.

The marker primitive is tested in test_hook_heartbeat_marker.py /
test_hook_heartbeat_liveness.py. This suite pins the WRITERS: which hooks
refresh it, on which paths, and with which session id.

`UserPromptSubmit` is the primary writer — every session submits a prompt
before it can invoke anything, teammates included. `SessionStart` is the
lead's head start, so the very first preload of a session already has a
verdict to read.
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import hook_liveness
import markers
import session_start
from _heartbeat_fixtures import env as _env
from conftest import _HookTestCase


class _HeartbeatWriterTestCase(_HookTestCase):
    """Shared reads. Every env patch stays inside a method body — entered via
    enterContext/addCleanup it would exit AFTER tearDown and `patch.dict`
    restores the whole mapping, reinstating the SMM_DIR that tearDown popped
    and pointing every later test in the worker at a deleted temp dir.
    """

    def _payload(self, session_id: str) -> dict | None:
        return markers.marker_read(
            self.smm_dir, hook_liveness.heartbeat_marker(session_id)
        )

    def _wrote(self, session_id: str) -> bool:
        return markers.marker_exists(
            self.smm_dir, hook_liveness.heartbeat_marker(session_id)
        )


class TestSessionStartWritesHeartbeat(_HeartbeatWriterTestCase):
    """AC#1. Not gated on a fresh start: a resume or a compact is still a
    session whose hooks are live and whose preloads will ask."""

    SOURCES = ("startup", "clear", "resume", "compact")

    def _run(self, source: str, session_id: str) -> None:
        with patch.dict(os.environ, _env()):
            session_start.run(
                {"session_id": session_id, "source": source},
                smm_dir=self.smm_dir,
            )

    def test_every_source_writes_a_heartbeat(self):
        for source in self.SOURCES:
            with self.subTest(source=source):
                session_id = f"sess-{source}"
                self._run(source, session_id)
                self.assertTrue(
                    self._wrote(session_id),
                    f"source={source} left no heartbeat",
                )

    def test_heartbeat_carries_id_version_and_a_current_timestamp(self):
        before = time.time()
        self._run("startup", "sess-payload")
        data = self._payload("sess-payload")
        assert isinstance(data, dict)
        self.assertEqual(data["session_id"], "sess-payload")
        self.assertTrue(data["plugin_version"])
        self.assertGreaterEqual(data["written_at"], before)
        self.assertLessEqual(data["written_at"], time.time())

    def test_the_heartbeat_reads_back_as_live(self):
        """The point of the whole exercise: a preload asking right after a
        session start gets a positive verdict rather than a refusal."""
        self._run("startup", "sess-live")
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-live")):
            result = hook_liveness.check_liveness(self.smm_dir)
        self.assertTrue(result.live, result.reason)


class TestSessionStartSkipsNonMainPaths(_HeartbeatWriterTestCase):
    """AC#3, asserted rather than left to fall out of the smm_dir=None path.

    A teammate gets its heartbeat from `UserPromptSubmit` instead: its prompt
    is its entry point, so the write lands before it can invoke a skill, and
    the teammate SessionStart path stays free of the SMM resolution that
    would inject the whole render into its context.

    Each assertion names THIS session's marker rather than asking whether any
    heartbeat exists. A concurrent story seeds a fresh heartbeat into the
    shared per-test SMM, so a bare "no heartbeat file" assertion would pass
    today and go red the moment that lands. `_ABSENCE_ID` is unguessable by
    any seed, which makes the absence claim about our writer specifically.
    """

    _ABSENCE_ID = "story-002-absence-probe-no-seed-produces-this"

    def _run(self, extra: dict) -> None:
        with patch.dict(os.environ, _env()):
            session_start.run(
                {"session_id": self._ABSENCE_ID, "source": "startup", **extra},
                smm_dir=self.smm_dir,
            )

    def test_worktree_teammate_start_writes_no_heartbeat(self):
        self._run({"cwd": "/tmp/worktree-story-999"})
        self.assertFalse(self._wrote(self._ABSENCE_ID))

    def test_xp_agent_writes_no_heartbeat(self):
        """The recursion guard returns before anything else runs. A nested
        agent is not a session, and crediting one would report liveness for a
        session whose own hooks may never have fired."""
        self._run({"agent_type": "xp-code-reviewer"})
        self.assertFalse(self._wrote(self._ABSENCE_ID))

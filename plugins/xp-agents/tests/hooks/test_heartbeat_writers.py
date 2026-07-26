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
import user_prompt_log
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


class TestUserPromptSubmitRefreshesHeartbeat(_HeartbeatWriterTestCase):
    """AC#2. The primary writer: every session submits a prompt before it can
    invoke anything, which is what gives a teammate a heartbeat at all."""

    SESSION = "sess-prompt"
    STALE_AT = 1_000.0

    def _seed_stale(self) -> None:
        with patch.dict(os.environ, _env()):
            hook_liveness.write_heartbeat(
                self.smm_dir, session_id=self.SESSION, now=self.STALE_AT
            )

    def _run(self, prompt: str) -> None:
        with patch.dict(os.environ, _env()):
            user_prompt_log.run(
                {"session_id": self.SESSION, "prompt": prompt},
                smm_dir=self.smm_dir,
            )

    def _customer_inputs(self) -> list[dict]:
        return [e for e in self._read_events() if e.get("type") == "customer_input"]

    def test_stale_heartbeat_is_refreshed_to_current(self):
        self._seed_stale()
        before = time.time()
        self._run("please carry on")
        data = self._payload(self.SESSION)
        assert isinstance(data, dict)
        self.assertGreaterEqual(data["written_at"], before)

    def test_refresh_does_not_swallow_the_prompt_event(self):
        """Same AC, second half. The heartbeat is a side effect bolted onto a
        hook with a job of its own, and the job must survive it."""
        self._seed_stale()
        self._run("please carry on")
        self.assertEqual(
            [e["content"] for e in self._customer_inputs()], ["please carry on"]
        )

    def test_first_prompt_of_a_session_writes_one_from_nothing(self):
        """A teammate's whole liveness story: it never takes the main
        SessionStart path, so this is the only write it gets."""
        self._run("implement the story")
        self.assertTrue(self._wrote(self.SESSION))

    def test_the_refreshed_heartbeat_reads_back_as_live(self):
        self._seed_stale()
        self._run("please carry on")
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.SESSION)):
            result = hook_liveness.check_liveness(self.smm_dir)
        self.assertTrue(result.live, result.reason)


class TestUserPromptSubmitWritesOnEveryTurn(_HeartbeatWriterTestCase):
    """AC#2 edge. The heartbeat records that the hook RAN — which is the whole
    claim — so it must land ahead of every early return that means "this
    particular prompt is not worth logging". A task notification is not
    customer input; the hook still fired."""

    SESSION = "sess-non-input"

    def _run(self, prompt: str) -> None:
        with patch.dict(os.environ, _env()):
            user_prompt_log.run(
                {"session_id": self.SESSION, "prompt": prompt},
                smm_dir=self.smm_dir,
            )

    def test_task_notification_still_writes_a_heartbeat(self):
        self._run("<task-notification>agent finished</task-notification>")
        self.assertTrue(self._wrote(self.SESSION))

    def test_task_notification_still_logs_no_customer_input(self):
        """The pre-existing contract this must not disturb: a notification
        creates a false loop boundary, so it stays out of the event log."""
        self._run("<task-notification>agent finished</task-notification>")
        self.assertEqual(self._read_events(), [])

    def test_blank_prompt_still_writes_a_heartbeat(self):
        for prompt in ("", "   \n\t "):
            with self.subTest(prompt=repr(prompt)):
                self._run(prompt)
                self.assertTrue(self._wrote(self.SESSION))
                markers.marker_consume(
                    self.smm_dir, hook_liveness.heartbeat_marker(self.SESSION)
                )

    def test_missing_prompt_key_still_writes_a_heartbeat(self):
        with patch.dict(os.environ, _env()):
            user_prompt_log.run({"session_id": self.SESSION}, smm_dir=self.smm_dir)
        self.assertTrue(self._wrote(self.SESSION))

    def test_xp_agent_writes_no_heartbeat(self):
        with patch.dict(os.environ, _env()):
            user_prompt_log.run(
                {
                    "session_id": self.SESSION,
                    "prompt": "hi",
                    "agent_type": "xp-code-reviewer",
                },
                smm_dir=self.smm_dir,
            )
        self.assertFalse(self._wrote(self.SESSION))


class TestSessionIdNormalisation(_HeartbeatWriterTestCase):
    """Which id keys the marker, at BOTH call sites.

    The payload is the runtime's own answer, so it wins over an inference from
    the environment. But `write_heartbeat` consults the candidate chain only
    for None: an empty string or a non-str is truthy-enough to skip the
    fallback and key a marker on the hash of a value no reader ever addresses
    — a heartbeat that exists on disk and is invisible to every check, which
    is worse than none at all because it also silences the reaper.
    """

    ENV_ID = "id-from-env"
    PAYLOAD_ID = "id-from-payload"

    # A falsy or wrong-typed payload id must reach the env chain, not the hash
    # of itself. `0` and `False` are the truthiness traps; `123` and `None` are
    # the type traps.
    FALSY_OR_NON_STR = ("", "   ", "\t\n", 0, False, 123, None, [], {})

    def _start(self, session_id: object) -> None:
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.ENV_ID)):
            session_start.run(
                {"session_id": session_id, "source": "startup"},
                smm_dir=self.smm_dir,
            )

    def _prompt(self, session_id: object) -> None:
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.ENV_ID)):
            user_prompt_log.run(
                {"session_id": session_id, "prompt": "go"}, smm_dir=self.smm_dir
            )

    def _writers(self):
        return (("session_start", self._start), ("user_prompt_submit", self._prompt))

    def _clear(self) -> None:
        for marker in (
            hook_liveness.heartbeat_marker(self.ENV_ID),
            hook_liveness.heartbeat_marker(self.PAYLOAD_ID),
        ):
            markers.marker_consume(self.smm_dir, marker)

    def test_payload_id_wins_over_the_environment(self):
        for name, write in self._writers():
            with self.subTest(writer=name):
                self._clear()
                write(self.PAYLOAD_ID)
                self.assertTrue(self._wrote(self.PAYLOAD_ID))
                self.assertFalse(self._wrote(self.ENV_ID))

    def test_falsy_or_non_str_payload_id_falls_back_to_the_chain(self):
        for name, write in self._writers():
            for session_id in self.FALSY_OR_NON_STR:
                with self.subTest(writer=name, session_id=repr(session_id)):
                    self._clear()
                    write(session_id)
                    self.assertTrue(
                        self._wrote(self.ENV_ID),
                        "a falsy payload id must reach the candidate chain",
                    )

    def test_a_falsy_payload_id_keys_no_marker_of_its_own(self):
        """The specific corruption: a marker at hash("") that no check reads."""
        for name, write in self._writers():
            with self.subTest(writer=name):
                self._clear()
                write("")
                self.assertFalse(self._wrote(""))

    def test_missing_session_id_key_falls_back_to_the_chain(self):
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.ENV_ID)):
            session_start.run({"source": "startup"}, smm_dir=self.smm_dir)
            user_prompt_log.run({"prompt": "go"}, smm_dir=self.smm_dir)
        self.assertTrue(self._wrote(self.ENV_ID))

#!/usr/bin/env python3
"""AC#4: the heartbeat survives a real hook pipeline.

The unit suite (tests/hooks/test_heartbeat_writers.py) calls `run()` in
process, which proves the placement but not the plumbing. This drives both
hooks as the platform does — a separate `python3` per hook, JSON on stdin,
resolving the SMM for itself — because that is where the failures the feature
exists to catch actually live: an import that only resolves under the test
runner's sys.path, or a heartbeat written somewhere no other process looks.

The verdict is read back through the shipped CLI rather than by inspecting
the marker. A file on disk is not the claim; the claim is that a fresh
process asking "are hooks running" gets yes.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import hook_liveness
import markers
from _heartbeat_fixtures import env as _env
from conftest import _IntegrationTestCase

_HOOK_LIVENESS_PY = Path(__file__).parent.parent.parent / "scripts" / "hook_liveness.py"


class TestHeartbeatPipeline(_IntegrationTestCase):
    SESSION = "pipeline-session"

    def _hook_env(self) -> dict:
        """Hook env with every session-id candidate blanked.

        The runner may itself be inside a live session, and an inherited id
        would put the CLI's read and the hooks' writes on different markers —
        the check would then pass or fail for a reason this test never set up.
        """
        return {**self._env_with_plugin_root(), **_env()}

    def _run_hook(self, script: str, payload: dict) -> subprocess.CompletedProcess:
        """Run one hook as its own process, through the shared driver.

        `_hook_env()` is passed whole rather than just the session blanks: it is
        already `_test_env` plus its own keys, so merging it as overrides is the
        same env, not a near one.
        """
        result = self._run_script_with_env(script, payload, self._hook_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _status(self, session_id: str) -> subprocess.CompletedProcess:
        """The real acceptance signal, run the way a user would run it."""
        return subprocess.run(
            [
                "python3",
                str(_HOOK_LIVENESS_PY),
                "--smm-dir",
                str(self.smm_dir),
                "status",
            ],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env={**self._hook_env(), "CLAUDE_CODE_SESSION_ID": session_id},
        )

    def _marker_payload(self, session_id: str) -> dict:
        data = markers.marker_read(
            self.smm_dir, hook_liveness.heartbeat_marker(session_id)
        )
        assert isinstance(data, dict)
        return data

    def test_status_refuses_before_any_hook_has_run(self):
        """Without this the rest of the suite cannot distinguish a working
        pipeline from a check that says yes unconditionally."""
        result = self._status(self.SESSION)
        self.assertEqual(result.returncode, hook_liveness.EXIT_NOT_LIVE)
        self.assertIn("not loaded", result.stdout)

    def test_session_start_then_user_prompt_leaves_a_live_verdict(self):
        self._run_hook(
            "session_start.py", {"session_id": self.SESSION, "source": "startup"}
        )
        after_start = self._status(self.SESSION)
        self.assertEqual(after_start.returncode, hook_liveness.EXIT_LIVE, after_start)
        self.assertIn("live", after_start.stdout)

        self._run_hook(
            "user_prompt_log.py", {"session_id": self.SESSION, "prompt": "ship it"}
        )
        after_prompt = self._status(self.SESSION)
        self.assertEqual(after_prompt.returncode, hook_liveness.EXIT_LIVE, after_prompt)

    def test_the_prompt_hook_moves_the_timestamp_forward(self):
        """Both hooks write; the second is a refresh, not a no-op. Without
        this the pipeline could pass on SessionStart's write alone."""
        self._run_hook(
            "session_start.py", {"session_id": self.SESSION, "source": "startup"}
        )
        at_start = self._marker_payload(self.SESSION)["written_at"]
        self._run_hook(
            "user_prompt_log.py", {"session_id": self.SESSION, "prompt": "ship it"}
        )
        self.assertGreater(self._marker_payload(self.SESSION)["written_at"], at_start)

    def test_the_prompt_hook_alone_is_enough(self):
        """A teammate's path: no main-path SessionStart ever runs for it, so
        the prompt hook is its only writer. If this regresses, every skill a
        teammate invokes refuses."""
        self._run_hook(
            "user_prompt_log.py", {"session_id": self.SESSION, "prompt": "implement"}
        )
        result = self._status(self.SESSION)
        self.assertEqual(result.returncode, hook_liveness.EXIT_LIVE, result)

    def test_the_pipeline_still_logs_the_prompt(self):
        self._run_hook(
            "session_start.py", {"session_id": self.SESSION, "source": "startup"}
        )
        self._run_hook(
            "user_prompt_log.py", {"session_id": self.SESSION, "prompt": "ship it"}
        )
        contents = [
            e["content"] for e in self._read_events() if e["type"] == "customer_input"
        ]
        self.assertEqual(contents, ["ship it"])

    def test_marker_carries_the_payload_id_not_the_hooks_environment(self):
        """The env is blanked here, so a marker keyed on the payload id proves
        the hooks used what the runtime handed them across a process boundary
        rather than re-deriving it."""
        self._run_hook(
            "session_start.py", {"session_id": self.SESSION, "source": "startup"}
        )
        self.assertEqual(self._marker_payload(self.SESSION)["session_id"], self.SESSION)
        self.assertTrue(self._marker_payload(self.SESSION)["plugin_version"])

    def test_a_reader_on_a_different_id_is_not_live_off_our_heartbeat(self):
        """The disagreement arm: a heartbeat a reader cannot address is not
        evidence about that reader.

        The mismatch verdict is pinned in-process elsewhere, but only from
        writers handed an explicit id. What is observable only here is the
        COMPOSITION discovery `d49c2d1fb85b` is about: a real hook process
        keying the marker off its PAYLOAD id while a separate reader process
        resolves from its ENVIRONMENT.

        The reason is asserted, not just the verdict, because two other refusals
        also land on exit 1 — a stale own marker, and `CODE_NO_MARKER` for a
        reader that resolves no id at all. The negative assertion excludes the
        second: reaching the session-mismatch prose proves an id resolved and
        simply did not name our heartbeat.
        """
        self._run_hook(
            "session_start.py", {"session_id": self.SESSION, "source": "startup"}
        )
        foreign = self._status("a-reader-that-is-not-us")
        self.assertEqual(
            foreign.returncode, hook_liveness.EXIT_NOT_LIVE, foreign.stdout
        )
        self.assertIn("No hook has run in this session", foreign.stdout)
        self.assertNotIn(
            "addressable from here",
            foreign.stdout,
            "refused for want of ANY id, so this proves nothing about a mismatch",
        )

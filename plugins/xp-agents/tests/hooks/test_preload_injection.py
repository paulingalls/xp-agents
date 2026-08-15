#!/usr/bin/env python3
"""Tests for preload_injection.py — the hook that delivers a skill's state.

Every requirement this handler exists to satisfy fails QUIETLY: exit 0, no
error, and an injection that looks successful. So each test below pins a
property that has no other symptom — the preload ran in the wrong directory,
against the wrong command, before the heartbeat, or with a failure stream
injected as though it were state.

The preload is faked with a temp script in most tests, deliberately. Driving a
real shipped preload through this handler has side effects — the close preloads
ARM a close cycle by running, which is how a measurement session once left four
orphaned cycles behind — and none of the properties here need a real one. The
one thing a fake cannot show, that the resolver reaches a real shipped script,
is pinned separately and without running it.
"""

import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import preload_injection
import skill_preload_map
from conftest import _HookTestCase

_HEARTBEAT_NAME = ".hook-heartbeat"


def _write_script(path: Path, body: str) -> Path:
    """A fake preload: a shell script that is executable and prints something."""
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestSkillIdentityFromPayload(unittest.TestCase):
    """The first harness names the skill in the tool call itself."""

    def test_our_namespace_is_stripped(self):
        payload = {"tool_input": {"skill": "xp-agents:xp-accept"}}
        self.assertEqual(preload_injection.skill_from_payload(payload), "xp-accept")

    def test_bare_name_survives(self):
        payload = {"tool_input": {"skill": "xp-accept"}}
        self.assertEqual(preload_injection.skill_from_payload(payload), "xp-accept")

    def test_absent_skill_is_none(self):
        self.assertIsNone(preload_injection.skill_from_payload({"tool_input": {}}))
        self.assertIsNone(preload_injection.skill_from_payload({}))


class TestResolverIsTheSoleSourceOfTheCommand(unittest.TestCase):
    """Requirement 2, and the reason an arbitrary-command vector is unreachable.

    A hardcoded `preload.sh` would be right on fourteen shipped skills and WRONG
    on two — one takes an extra flag, one names a different script — so the pin
    is that the handler asks the resolver rather than that it finds some script.
    Asserted WITHOUT running anything: a real close preload arms a close cycle by
    running, and this property needs no execution to observe.
    """

    def test_a_shipped_skill_resolves_to_a_real_executable_script(self):
        invocation = skill_preload_map.resolve_preload("xp-schedule")
        assert invocation is not None
        self.assertTrue(Path(invocation.argv[0]).is_file())

    def test_the_outlier_skills_are_reached_through_the_resolver(self):
        """The two the hardcoded default would have got wrong."""
        kickoff = skill_preload_map.resolve_preload("xp-kickoff")
        assert kickoff is not None
        self.assertEqual(Path(kickoff.argv[0]).name, "check_session_needs.sh")

        assign = skill_preload_map.resolve_preload("xp-assign")
        assert assign is not None
        self.assertEqual(assign.argv[1:], ["--consume-gate"])

    def test_a_skill_we_do_not_ship_injects_nothing(self):
        """A third-party or built-in skill reaches this handler routinely; the
        resolver raises for it and the handler must treat that as 'not ours',
        not as an error."""
        self.assertIsNone(preload_injection.run_preload("code-review", ""))

    def test_a_shipped_skill_with_no_preload_injects_nothing(self):
        self.assertIsNone(preload_injection.run_preload("xp-stage-migration", ""))


class TestPreloadExecution(_HookTestCase):
    """The four quiet failures in actually running the thing."""

    def setUp(self):
        super().setUp()
        self.work = Path(self.smm_dir) / "work"
        self.work.mkdir()

    def _fake(self, body: str, env: dict | None = None):
        script = _write_script(self.work / "fake_preload.sh", body)
        return patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(
                argv=[str(script)], env=env or {}
            ),
        )

    def test_output_is_returned_as_the_injected_context(self):
        with self._fake('echo "STATE=here"'):
            self.assertEqual(
                preload_injection.run_preload("xp-accept", str(self.work)),
                "STATE=here\n",
            )

    def test_it_runs_in_the_session_cwd_not_the_skill_dir(self):
        """Requirement 1. Resolving elsewhere silently yields ANOTHER PROJECT's
        state — the injection succeeds and the content is wrong, which no exit
        status reports."""
        session_cwd = Path(self.smm_dir) / "session"
        session_cwd.mkdir()
        with self._fake("pwd"):
            output = preload_injection.run_preload("xp-accept", str(session_cwd))
        assert output is not None
        self.assertEqual(Path(output.strip()).resolve(), session_cwd.resolve())

    def test_declared_env_reaches_the_preload(self):
        fake = self._fake(
            'echo "DATA=$CLAUDE_PLUGIN_DATA"', env={"CLAUDE_PLUGIN_DATA": "/x"}
        )
        with fake:
            self.assertEqual(
                preload_injection.run_preload("xp-accept", str(self.work)),
                "DATA=/x\n",
            )

    def test_a_failing_preload_injects_nothing(self):
        """Requirement 4. The partial stream a failed preload printed before
        dying is not state, and injecting it is indistinguishable from success."""
        with self._fake('echo "half a table"; exit 1'):
            self.assertIsNone(
                preload_injection.run_preload("xp-accept", str(self.work))
            )

    def test_an_empty_preload_injects_nothing(self):
        with self._fake("true"):
            self.assertIsNone(
                preload_injection.run_preload("xp-accept", str(self.work))
            )

    def test_a_wedged_preload_times_out_and_injects_nothing(self):
        """It must degrade to 'no state', never hang the tool call."""
        with (
            self._fake("sleep 5; echo late"),
            patch.object(preload_injection, "_PRELOAD_TIMEOUT_SECONDS", 1),
        ):
            self.assertIsNone(
                preload_injection.run_preload("xp-accept", str(self.work))
            )

    def test_an_unexecutable_preload_injects_nothing(self):
        script = self.work / "not_executable.sh"
        script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        script.chmod(0o600)
        with patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(argv=[str(script)]),
        ):
            self.assertIsNone(
                preload_injection.run_preload("xp-accept", str(self.work))
            )


class TestHeartbeatIsWrittenBeforeTheRun(_HookTestCase):
    """Requirement 3, and the ORDER is the whole property.

    The preload scripts carry their own liveness check and emit a refusal banner
    INSTEAD OF STATE when no fresh heartbeat exists. A heartbeat written after
    the run would therefore inject that banner while every exit status said
    success. Proven by having the fake preload look for the heartbeat itself, so
    the assertion is about what the preload SAW — a test that merely checked the
    file exists afterwards would pass with the write in the wrong place.
    """

    def test_the_preload_sees_the_heartbeat_already_written(self):
        work = Path(self.smm_dir) / "work"
        work.mkdir()
        # Globbed, not an exact name: the heartbeat is written session-suffixed
        # (`.hook-heartbeat-<id>`), one file per session, because the SMM dir is
        # shared across worktrees and windows. Asserting the bare stem passed
        # nothing and failed this test for the wrong reason.
        script = _write_script(
            work / "fake_preload.sh",
            f'if ls "{self.smm_dir}/{_HEARTBEAT_NAME}"* >/dev/null 2>&1; '
            "then echo SAW_HEARTBEAT; else echo NO_HEARTBEAT; fi",
        )
        with patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(argv=[str(script)]),
        ):
            output = preload_injection.run(
                {"tool_input": {"skill": "xp-agents:xp-accept"}, "cwd": str(work)}
            )
        self.assertEqual(output, "SAW_HEARTBEAT\n")

    def test_the_same_probe_says_no_heartbeat_when_the_write_is_removed(self):
        """Non-vacuity for the pin above: with the heartbeat write suppressed,
        the identical probe must report NO_HEARTBEAT. Without this, a probe that
        silently always printed SAW_HEARTBEAT would pass forever."""
        work = Path(self.smm_dir) / "work2"
        work.mkdir()
        script = _write_script(
            work / "fake_preload.sh",
            f'if ls "{self.smm_dir}/{_HEARTBEAT_NAME}"* >/dev/null 2>&1; '
            "then echo SAW_HEARTBEAT; else echo NO_HEARTBEAT; fi",
        )
        with (
            patch.object(
                skill_preload_map,
                "resolve_preload",
                return_value=skill_preload_map.PreloadInvocation(argv=[str(script)]),
            ),
            patch.object(
                preload_injection, "_refresh_heartbeat", lambda _payload: None
            ),
        ):
            output = preload_injection.run(
                {"tool_input": {"skill": "xp-agents:xp-accept"}, "cwd": str(work)}
            )
        self.assertEqual(output, "NO_HEARTBEAT\n")


class TestRecursionGuard(_HookTestCase):
    """Our own xp- subagents must not re-trigger the injection.

    Every command hook gating an agent hook checks this; without it a subagent
    invoking a skill re-enters the mechanism.
    """

    def test_our_own_agent_injects_nothing(self):
        work = Path(self.smm_dir) / "work"
        work.mkdir()
        script = _write_script(work / "fake_preload.sh", 'echo "STATE=here"')
        payload = {
            "tool_input": {"skill": "xp-agents:xp-accept"},
            "cwd": str(work),
            "agent_type": "xp-code-reviewer",
        }
        with patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(argv=[str(script)]),
        ):
            self.assertIsNone(preload_injection.run(payload))


class TestHandlerRunsAsAHook(_HookTestCase):
    """E2E over the process boundary: the shape the harness actually invokes.

    Every test above calls `run()` in-process, which never exercises stdin
    parsing, the `hookSpecificOutput` envelope, or the exit status. A hook that
    emitted the right string on the wrong envelope would deliver nothing, and
    an import-only suite would stay green through it.
    """

    def test_stdin_payload_produces_a_hookspecificoutput_envelope(self):
        work = Path(self.smm_dir) / "work"
        work.mkdir()

        # A real subprocess cannot see a patched resolver, so the fake is
        # installed the way the resolver itself reads the tree: point the
        # plugin root at a scratch tree carrying one skill.
        fake_root = Path(self.smm_dir) / "plugin"
        skill_scripts = fake_root / "skills" / "xp-accept" / "scripts"
        skill_scripts.mkdir(parents=True)
        _write_script(skill_scripts / "preload.sh", 'echo "MARKER=delivered"')

        env = {
            **os.environ,
            "CLAUDE_PLUGIN_ROOT": str(fake_root),
            "SMM_DIR": str(self.smm_dir),
        }
        payload = json.dumps(
            {"tool_input": {"skill": "xp-agents:xp-accept"}, "cwd": str(work)}
        )
        completed = subprocess.run(
            [sys.executable, str(Path(preload_injection.__file__))],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("hookSpecificOutput", completed.stdout)
        self.assertIn("additionalContext", completed.stdout)
        self.assertIn("MARKER=delivered", completed.stdout)


if __name__ == "__main__":
    unittest.main()

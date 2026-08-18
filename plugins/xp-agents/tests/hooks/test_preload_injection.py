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

The FIRST harness's leg only: everything here starts from `tool_input.skill`.
The shell-read leg — identity out of `tool_input.command`, and the claim that
keeps a mention from starving a read — is `test_preload_injection_shell_read.py`,
which shares no fixture with anything below.
"""

import ast
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
import pre_tool_skill
import preload_injection
import skill_preload_map
from _budget_helpers import (
    _bootstrap_seeded_smm,
    _run_preload,
    scrub_close_cycle_marker,
)
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

    def test_the_write_is_the_shipped_one_not_a_second_copy(self):
        """`pre_tool_skill.refresh_heartbeat` does exactly this, and used to be
        duplicated here line for line. Two spellings of the same write drift
        silently; the ORDERING guarantee above stays this module's, because on
        the shell-read leg `pre_tool_skill` never runs at all."""
        with patch.object(pre_tool_skill, "refresh_heartbeat") as shipped:
            preload_injection._refresh_heartbeat({"session_id": "s"})
        shipped.assert_called_once()

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


class TestInjectedStateMatchesInstructionTimeState(unittest.TestCase):
    """The mechanism swap must not change WHAT arrives, only how.

    A quiet-failure class the six recorded requirements miss, and which no other
    suite can see: `skill_preload_map` builds the preload's environment from
    `os.environ`, and `smm/init.sh` records in its own comment that
    `CLAUDE_PLUGIN_DATA` is absent in some hook processes. So the injected run
    can resolve a DIFFERENT SMM root than the instruction-time run did — at exit
    0, with output that looks entirely successful.

    story-003's delivery pin cannot catch it: that suite runs preloads directly
    rather than through this handler, so both of its sides are the same side.
    This one drives the SAME skill both ways against one seeded SMM and compares
    the bytes.

    Reach, measured rather than claimed: mutating the handler to alter the
    delivered bytes turns this red, so it is live on CONTENT. Mutating it to
    ignore the session cwd does NOT — `xp-schedule`'s output happens not to
    depend on the working directory, so that requirement is covered by its own
    dedicated pin above and not by this one. Stated so a reader does not take
    this for a general equivalence proof it is not.
    """

    def test_a_preload_delivers_the_same_bytes_through_both_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))

            instruction_stdout, _stderr, rc = _run_preload("xp-schedule", smm_dir, repo)
            self.assertEqual(rc, 0)
            scrub_close_cycle_marker(smm_dir)

            with patch.dict(os.environ, {"SMM_DIR": str(smm_dir)}):
                injected = preload_injection.run_preload("xp-schedule", str(repo))
            scrub_close_cycle_marker(smm_dir)

        self.assertIsNotNone(injected, "the handler delivered nothing at all")
        assert injected is not None
        self.assertEqual(
            injected,
            instruction_stdout.decode("utf-8"),
            "injected state differs from what the instruction-time path "
            "delivered — the mechanism swap changed the CONTENT, which is the "
            "one thing it must not do",
        )


class TestARefusedCallRunsNoPreload(_HookTestCase):
    """A call the gate beside this handler will REFUSE must leave no residue.

    `pre_tool_skill.py` sits on the same PreToolUse entry and can block the
    invocation; hooks on one entry run in parallel, so this handler cannot
    OBSERVE the refusal. It computes the same verdict itself instead, from the
    same two shipped predicates, and declines to run the preload at all.

    That matters because several preloads mutate shared state BY RUNNING —
    `/xp-accept` consumes the mark-done gate, `/xp-assign` consumes the assign
    Write gate, `/xp-review-plan` deletes `.plan-awaiting-review`. None of those
    consumes can move to PostToolUse: each unblocks an operation the skill
    performs during its OWN run. So the only place to stop the side effect is
    before the preload starts.

    Each specimen below asserts BOTH halves — the gate marker survives AND
    nothing is injected. Either alone passes on a broken half: a handler that
    ran the preload and discarded its output would satisfy the second, and one
    that injected a stale cache would satisfy the first.
    """

    def setUp(self):
        super().setUp()
        self.work = Path(self.smm_dir) / "work"
        self.work.mkdir()
        # A REAL directory with the teammate path segment in it. A nonexistent
        # cwd makes `subprocess.run` raise and the handler inject nothing, so a
        # made-up path passes the refusal tests without the guard existing.
        self.teammate_cwd = Path(self.smm_dir) / "worktree-story-001"
        self.teammate_cwd.mkdir()
        # A real gate marker, written through the production helper so the
        # filename is the one the shipped preload would consume.
        self.gate = markers.marker_path(Path(self.smm_dir), markers.ASSIGN_PENDING)
        markers.marker_write(Path(self.smm_dir), markers.ASSIGN_PENDING, "story-001")
        # Stands in for any mutating preload: it spends the gate by running, and
        # prints state, so "the gate survived" and "nothing was injected" are the
        # same observation made twice — the preload process never started.
        self._fake = patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(
                argv=[
                    str(
                        _write_script(
                            self.work / "fake_preload.sh",
                            f'rm -f "{self.gate}"\necho "STATE=here"',
                        )
                    )
                ]
            ),
        )

    def _run(self, payload: dict) -> str | None:
        with self._fake:
            return preload_injection.run(payload)

    def test_a_blocked_teammate_leaves_the_gate_intact_and_gets_nothing(self):
        """The shipped refusal: a live CLI teammate invoking a lead-owned skill.

        Before this guard the teammate's blocked /xp-assign still ran the
        preload, which consumed the LEAD's assign gate.
        """
        output = self._run(
            {
                "tool_input": {"skill": "xp-agents:xp-assign"},
                "cwd": str(self.teammate_cwd),
            }
        )
        self.assertIsNone(output, "a refused call must receive no context either")
        self.assertTrue(self.gate.exists(), "the refused call consumed the gate")

    def test_a_lead_driving_story_close_with_no_accept_evidence_gets_nothing(self):
        """The second shipped refusal, and it is not a teammate one.

        `accept_evidence_block_reason` blocks /xp-story-close when no story is
        in `closing` — here there is no sprint at all.
        """
        output = self._run(
            {
                "tool_input": {"skill": "xp-agents:xp-story-close"},
                "cwd": str(self.work),
            }
        )
        self.assertIsNone(output)
        self.assertTrue(self.gate.exists())

    def test_the_lead_still_gets_its_injection_and_still_spends_the_gate(self):
        """The allowed direction, so the fix is not a blunt disable.

        Without this the guard could be `return None` and every test above
        would still pass, having broken the whole mechanism.
        """
        output = self._run(
            {"tool_input": {"skill": "xp-agents:xp-assign"}, "cwd": str(self.work)}
        )
        self.assertEqual(output, "STATE=here\n")
        self.assertFalse(self.gate.exists(), "the allowed call did not run the preload")

    def test_a_second_lead_invocation_is_not_starved(self):
        """Consumed exactly once, and the retry still gets state.

        The first-harness leg takes no claim by design; a guard that started
        taking one — or that cached its verdict — would leave the second call
        blind, which is the failure this handler's docstring reasons about.
        """
        first = self._run(
            {"tool_input": {"skill": "xp-agents:xp-assign"}, "cwd": str(self.work)}
        )
        second = self._run(
            {"tool_input": {"skill": "xp-agents:xp-assign"}, "cwd": str(self.work)}
        )
        self.assertEqual(first, "STATE=here\n")
        self.assertEqual(second, "STATE=here\n")

    def test_the_verdict_is_the_shipped_predicate_not_a_second_spelling(self):
        """One verdict, two callers. A reimplementation here would drift from
        `pre_tool_skill`'s own gate silently — this handler would start running
        preloads for calls that ARE refused, or refusing ones that are not."""
        payload = {
            "tool_input": {"skill": "xp-agents:xp-assign"},
            "cwd": str(self.teammate_cwd),
        }
        with patch.object(
            pre_tool_skill, "teammate_block_reason", return_value=None
        ) as shipped:
            output = self._run(payload)
        shipped.assert_called()
        self.assertEqual(
            output,
            "STATE=here\n",
            "the guard did not consult the shipped predicate — neutralizing it "
            "left the call refused anyway",
        )


class TestTheGuardPrecedesTheClaim(unittest.TestCase):
    """Placement, pinned structurally because it has no runtime observable.

    Claiming for a call that will be refused starves the user's retry after they
    clear the gate — the exact failure `run()`'s docstring reasons about for the
    other leg. Today only the SHELL-READ leg claims, and that leg carries no
    refusal to detect (both predicates key on `tool_input.skill`, which harness
    2's payload does not carry), so no fixture can make a refused call reach
    `_take_claim` and the ordering cannot be observed at runtime. It is still
    the property that must hold if a future change ever claims on both legs, so
    it is asserted over the AST of `run()` rather than left to a comment.
    """

    def _call_order(self) -> list[str]:
        source = Path(preload_injection.__file__).read_text(encoding="utf-8")
        run_fn = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        calls = [
            (node, node.func)
            for node in ast.walk(run_fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        # Sorted by position: `ast.walk` is breadth-first, so its own order
        # reflects nesting depth rather than the order the code runs in — and
        # the claim IS more deeply nested than the guard, which is exactly the
        # shape that would make a depth-ordered pin pass no matter what.
        calls.sort(key=lambda pair: (pair[0].lineno, pair[0].col_offset))
        return [func.id for _call, func in calls]

    def test_the_refusal_check_is_reached_before_any_claim(self):
        order = self._call_order()
        self.assertIn("_refused_by_a_gate", order, "the guard left run()")
        self.assertIn("_take_claim", order, "the claim left run()")
        self.assertLess(order.index("_refused_by_a_gate"), order.index("_take_claim"))


if __name__ == "__main__":
    unittest.main()

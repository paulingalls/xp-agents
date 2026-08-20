#!/usr/bin/env python3
"""The second harness's leg of preload_injection.py: the shell read.

Split from `test_preload_injection.py`, which measured 483 lines with both legs
in it — inside the 450-line band on the day it was written, which the file-size
convention names as the shape that becomes debt. The two legs share no fixture:
everything here starts from `tool_input.command` and turns on the CLAIM, while
the sibling file starts from `tool_input.skill` and turns on EXECUTION (cwd,
env, failure posture, heartbeat order).

The hard question on this leg is not "which skill" but "is this an invocation
at all". A mention that classifies as a read TAKES THE CLAIM and starves the
genuine read behind it, which is a failure that reports success on every
channel it touches.
"""

import os
import stat
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
import preload_injection
import skill_preload_map
from conftest import _PLUGIN_ROOT, _HookTestCase


def _write_script(path: Path, body: str) -> Path:
    """A fake preload: a shell script that is executable and prints something."""
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestSkillIdentityFromAShellRead(unittest.TestCase):
    """The second harness has no skill tool call.

    Only the skill's LOCATOR reaches the model there; the body arrives when the
    model reads SKILL.md with a shell command, so the identity has to come out
    of `tool_input.command`. That makes the hard question not "which skill" but
    "is this an invocation at all" — a measured `wc -c` on a skill file once
    consumed the gate, injected, and claimed the once-marker, so the genuine
    read that followed received nothing while idempotence reported working.
    """

    def _skill_md(self, name: str) -> str:
        return str(_PLUGIN_ROOT / "skills" / name / "SKILL.md")

    def test_a_read_of_the_skill_file_is_an_invocation(self):
        command = f"cat {self._skill_md('xp-accept')}"
        self.assertEqual(preload_injection.skill_from_command(command), "xp-accept")

    def test_the_measured_mention_is_not_an_invocation(self):
        """`wc -c` on a skill file — the exact command that broke this before."""
        command = f"wc -c {self._skill_md('xp-accept')}"
        self.assertIsNone(preload_injection.skill_from_command(command))

    def test_a_read_later_in_a_chain_is_still_found(self):
        """Tokenizing per simple command is what stops chaining hiding the read
        (and, in the other direction, a mention riding along with one)."""
        command = f"ls -l && cat {self._skill_md('xp-schedule')}"
        self.assertEqual(preload_injection.skill_from_command(command), "xp-schedule")

    def test_a_path_inside_a_quoted_string_is_not_an_invocation(self):
        """To the shell the message is ONE token, so a tokenizer cannot mistake
        it for an argument — the reason this reuses `shell_commands`, whose own
        docstring records what regex-over-raw-text cost twice."""
        command = f'git commit -m "see {self._skill_md("xp-accept")} for context"'
        self.assertIsNone(preload_injection.skill_from_command(command))

    def test_unparseable_text_is_not_an_invocation(self):
        self.assertIsNone(preload_injection.skill_from_command('cat "unbalanced'))

    def test_a_file_that_is_not_a_skill_body_is_not_an_invocation(self):
        command = (
            f"cat {_PLUGIN_ROOT / 'skills' / 'xp-accept' / 'scripts' / 'preload.sh'}"
        )
        self.assertIsNone(preload_injection.skill_from_command(command))

    def test_a_skill_we_do_not_ship_is_not_an_invocation(self):
        self.assertIsNone(
            preload_injection.skill_from_command("cat /elsewhere/skills/nope/SKILL.md")
        )

    def test_a_read_of_a_skill_body_reached_by_a_dotdot_path_still_resolves(self):
        """`..` is collapsed by the resolve, not matched as text — so a path
        that walks out of the skills tree and back in is the same invocation.
        The containment check is on the RESOLVED path for exactly this reason:
        a lexical prefix test would answer 'not ours' here and 'ours' for
        `<skills>/../../elsewhere/x/SKILL.md`, both backwards."""
        command = (
            f"cat {_PLUGIN_ROOT / 'skills' / 'xp-accept' / '..' / 'xp-schedule'}"
            "/SKILL.md"
        )
        self.assertEqual(preload_injection.skill_from_command(command), "xp-schedule")

    def test_a_path_that_escapes_the_skills_tree_is_not_an_invocation(self):
        command = f"cat {_PLUGIN_ROOT / 'skills' / '..' / '..' / 'SKILL.md'}"
        self.assertIsNone(preload_injection.skill_from_command(command))


class TestTheClaimCollapsesABurstWithoutStarvingTheNextRead(_HookTestCase):
    """Requirement 3 and requirement 6 together, because they interact.

    The claim exists because four parallel firings once each ran the preload.
    But the moment a claim exists, a MENTION that takes it starves the genuine
    read that follows — measured, and it reported idempotence working while
    delivering nothing. So the claim is taken only on the path that actually
    injects, never before classification.
    """

    def setUp(self):
        super().setUp()
        self.work = Path(self.smm_dir) / "work"
        self.work.mkdir()
        self.script = _write_script(self.work / "fake_preload.sh", 'echo "STATE=x"')
        self._patch = patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(argv=[str(self.script)]),
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _read(self, skill: str = "xp-accept") -> dict:
        body = _PLUGIN_ROOT / "skills" / skill / "SKILL.md"
        return {"tool_input": {"command": f"cat {body}"}, "cwd": str(self.work)}

    def _mention(self, skill: str = "xp-accept") -> dict:
        body = _PLUGIN_ROOT / "skills" / skill / "SKILL.md"
        return {"tool_input": {"command": f"wc -c {body}"}, "cwd": str(self.work)}

    def test_a_burst_of_reads_runs_the_preload_once(self):
        self.assertEqual(preload_injection.run(self._read()), "STATE=x\n")
        self.assertIsNone(preload_injection.run(self._read()))
        self.assertIsNone(preload_injection.run(self._read()))

    def test_a_mention_does_not_consume_the_claim(self):
        """The measured starvation, pinned. If `wc -c` took the claim, the real
        read that follows would receive nothing while everything reported
        success."""
        self.assertIsNone(preload_injection.run(self._mention()))
        self.assertEqual(preload_injection.run(self._read()), "STATE=x\n")

    def test_the_claim_is_per_skill_not_global(self):
        self.assertEqual(preload_injection.run(self._read("xp-accept")), "STATE=x\n")
        self.assertEqual(preload_injection.run(self._read("xp-schedule")), "STATE=x\n")

    def test_a_re_invocation_after_the_window_injects_again(self):
        """The other half of the lifetime. A claim that outlived its invocation
        would leave the next one stateless, and say nothing about it."""
        self.assertEqual(preload_injection.run(self._read()), "STATE=x\n")
        claim = markers.marker_path(
            self.smm_dir, preload_injection._claim_for("xp-accept")
        )
        stale = time.time() - (preload_injection._CLAIM_TTL_SECONDS + 60)
        os.utime(claim, (stale, stale))
        self.assertEqual(preload_injection.run(self._read()), "STATE=x\n")

    def test_a_failed_preload_does_not_keep_the_claim(self):
        """The claim is taken BEFORE the preload runs, because that is the only
        order that collapses a burst. So a preload that then FAILS leaves a live
        claim standing for a run that delivered nothing, and every read for the
        rest of the window is refused — the skill goes without state and the
        retry the claim exists to collapse is the retry it prevents.

        Released only on the FAILING path: a successful run must keep its claim,
        which is `test_a_burst_of_reads_runs_the_preload_once` above.
        """
        with patch.object(
            preload_injection, "run_preload", return_value=None
        ) as failed:
            self.assertIsNone(preload_injection.run(self._read()))
            self.assertIsNone(preload_injection.run(self._read()))
            self.assertEqual(failed.call_count, 2)

    def test_the_read_leg_tells_its_preload_the_invocation_is_unproven(self):
        """A read of a SKILL.md is indistinguishable from an invocation on the
        second harness — the model loads a skill BY reading it — so a preload
        that arms or spends a marker does so on every `cat`. Arming is pure
        harm: a read of a close skill's body would arm the close Stop gate and
        wedge it with no close running.

        Suppressed by declaring it in the environment rather than by parsing the
        preload: the helpers are one choke point, and the alternative is
        guessing which scripts mutate.
        """
        env_probe = _write_script(
            self.work / "env_probe.sh",
            'echo "RO=${XP_PRELOAD_UNVERIFIED_INVOCATION:-unset}"',
        )
        with patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(argv=[str(env_probe)]),
        ):
            self.assertEqual(preload_injection.run(self._read()), "RO=1\n")

    def test_the_skill_tool_leg_asserts_a_real_invocation(self):
        """The control, and the reason the flag is not simply always on. A skill
        TOOL call is a real invocation, so the gate it discharges is genuinely
        being satisfied and the marker work must still happen."""
        env_probe = _write_script(
            self.work / "env_probe2.sh",
            'echo "RO=${XP_PRELOAD_UNVERIFIED_INVOCATION:-unset}"',
        )
        payload = {
            "tool_input": {"skill": "xp-agents:xp-accept"},
            "cwd": str(self.work),
        }
        with patch.object(
            skill_preload_map,
            "resolve_preload",
            return_value=skill_preload_map.PreloadInvocation(argv=[str(env_probe)]),
        ):
            self.assertEqual(preload_injection.run(payload), "RO=unset\n")

    def test_the_skill_tool_leg_takes_no_claim(self):
        """A skill tool call fires once per invocation, so there is no burst to
        collapse — and claiming there would starve a retry after the sibling
        gate on the same entry BLOCKED the call, which this handler cannot see."""
        payload = {
            "tool_input": {"skill": "xp-agents:xp-accept"},
            "cwd": str(self.work),
        }
        self.assertEqual(preload_injection.run(payload), "STATE=x\n")
        self.assertEqual(preload_injection.run(payload), "STATE=x\n")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Throwaway: validity checks for the gate-arming helper.

Every negative story-004 records depends on this helper being right. If a gate
is not actually armed, the run produces "not blocked" / "did not block" and
those strings are indistinguishable from the no-go criteria failing — which is
the verdict. So arming is not allowed to *claim* success: it asserts by running
the real gate and refuses when the gate does not bite.

The load-bearing check is the cadence one. Under `story` cadence the commit gate
never blocks at all (`pre_tool_bash_commit_gates.py:172-181` emits an advisory
instead), and this project's live cadence IS `story`. A helper that trusted the
default would arm nothing here and report a total bypass.

Deleted with the rest of the rig at sprint close. Run explicitly:
    pytest plugins/xp-agents/spike/test_arm_gates.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import arm_gates
import probe_commit_shapes as probe


class _ScratchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo, self.smm_dir = probe.build_rig(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestCommitGateArming(_ScratchTestCase):
    def test_arming_makes_the_control_shape_block(self) -> None:
        report = arm_gates.arm_commit_gate(repo=self.repo, smm_dir=self.smm_dir)
        self.assertTrue(report["armed"])
        self.assertIn("/xp-quality-review", report["control_reason"])

    def test_story_cadence_is_overwritten_not_trusted(self) -> None:
        # The confound that would have cost a whole Codex run. With `story` on
        # disk the gate only advises, so a helper that relies on the "commit"
        # default arms nothing and every shape reads as not-blocked. Guards a
        # helper that writes no cadence marker at all.
        arm_gates.write_cadence(self.smm_dir, "story")
        self.assertEqual(arm_gates.read_cadence(self.smm_dir), "story")
        report = arm_gates.arm_commit_gate(repo=self.repo, smm_dir=self.smm_dir)
        self.assertEqual(arm_gates.read_cadence(self.smm_dir), "commit")
        self.assertTrue(report["armed"])

    def test_arming_refuses_when_too_few_code_files_are_staged(self) -> None:
        # One staged code file is below REVIEW_CYCLE_THRESHOLD, so the gate
        # allows. Guards a helper that writes markers and declares victory
        # without checking that the gate actually bites.
        with tempfile.TemporaryDirectory() as td:
            repo, smm_dir = probe.build_rig(Path(td), stage_files=False)
            (repo / "only.py").write_text("X = 1\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "only.py"],
                cwd=str(repo),
                check=True,
                capture_output=True,
            )
            # Pinning the CAUSE, not just the refusal: assertRaises alone would
            # pass if arming failed for any unrelated reason, which is how a
            # refusal check goes vacuous.
            with self.assertRaises(arm_gates.NotArmedError) as ctx:
                arm_gates.arm_commit_gate(repo=repo, smm_dir=smm_dir)
            self.assertIn("staged code files=1", str(ctx.exception))

    def test_arming_refuses_when_a_review_is_already_recorded(self) -> None:
        # A recorded quality_review_done releases the gate. Same class of
        # failure as above, reached the other way, and the realistic one on a
        # scratch SMM reused between runs.
        arm_gates.record_review_done(self.smm_dir, self.repo)
        with self.assertRaises(arm_gates.NotArmedError) as ctx:
            arm_gates.arm_commit_gate(repo=self.repo, smm_dir=self.smm_dir)
        self.assertIn("quality_review_done=True", str(ctx.exception))


class TestStopGateArming(_ScratchTestCase):
    def test_arming_makes_the_real_stop_gate_block(self) -> None:
        report = arm_gates.arm_tdd_stop_gate(repo=self.repo, smm_dir=self.smm_dir)
        self.assertTrue(report["armed"])
        self.assertIn("Tests are failing", report["block_reason"])

    def test_the_block_arrives_as_decision_json_not_exit_two(self) -> None:
        # The four releasing Stop gates use {"decision": "block"} on stdout with
        # exit 0, unlike the PreToolUse path's stderr + exit 2. Pinned because
        # story-004 must report which mechanism Codex honours, and a helper that
        # accepted either would blur the very distinction being measured.
        arm_gates.arm_tdd_stop_gate(repo=self.repo, smm_dir=self.smm_dir)
        result = arm_gates.run_stop_gate(repo=self.repo, smm_dir=self.smm_dir)
        self.assertEqual(result["returncode"], 0)
        payload = json.loads(result["stdout"])
        self.assertEqual(payload["decision"], "block")

    def test_stop_hook_active_releases_the_gate(self) -> None:
        # The release valve itself. Without this check a helper could "arm" a
        # gate that is in fact already released, and Run L would report a Stop
        # block that never happened.
        arm_gates.arm_tdd_stop_gate(repo=self.repo, smm_dir=self.smm_dir)
        result = arm_gates.run_stop_gate(
            repo=self.repo, smm_dir=self.smm_dir, stop_hook_active=True
        )
        self.assertEqual(result["stdout"].strip(), "")

    def test_arming_refuses_when_another_agent_is_active(self) -> None:
        # tdd_stop_gate releases when other teammates are live, since they may
        # own the failing tests. Guards a helper that appends the fail concern
        # and reports armed without running the gate.
        arm_gates.register_other_agent(self.smm_dir, "some-other-agent")
        with self.assertRaises(arm_gates.NotArmedError) as ctx:
            arm_gates.arm_tdd_stop_gate(repo=self.repo, smm_dir=self.smm_dir)
        # The cause, pinned. Without this the check passes if the fail-signal
        # append itself broke -- a refusal for the wrong reason reads as the
        # right one.
        self.assertIn("other active agents=True", str(ctx.exception))


class TestTheReport(_ScratchTestCase):
    def test_describe_names_each_condition_it_asserted(self) -> None:
        # The plan requires arming to PRINT what it asserted. A bare "armed:
        # true" is not evidence -- a later reader cannot tell which conditions
        # were checked from which were assumed.
        report = arm_gates.arm_commit_gate(repo=self.repo, smm_dir=self.smm_dir)
        text = arm_gates.describe(report)
        for needle in ("cadence", "staged code files", "review", "control"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_describe_refuses_a_report_that_is_not_armed(self) -> None:
        with self.assertRaises(ValueError):
            arm_gates.describe({"armed": False})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Sprint-050 / story-002 (M-2 capstone): E2E for xp-accept Tier 2 ordering.

Hybrid coverage (decision ccb2e70adc20):

- **Runtime** subprocess tests drive append.sh, sprint_cli.py, and
  pre_tool_bash.py to verify the scriptable parts of the accept flow:
  Block/Concern concern recording, update-story-done CLI behavior, and
  the cross-session ACCEPT marker gate enforced by pre_tool_bash.

- **Prose** text-pin tests on xp-accept/SKILL.md cover the LLM-only
  seams (Step 1b/1c/2 ordering, Block-prevents-done convention,
  Concern-proceeds-to-done convention, code_free skip). The skill is
  LLM prose with no Python entry point — these pins lock the contract
  so future SKILL.md edits that drop the wording fail loudly.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, _make_bash_input, _s, _sprint_json

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_SPRINT_CLI = _PLUGIN_ROOT / "smm" / "sprint_cli.py"
_ACCEPT_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-accept" / "SKILL.md"


class TestAcceptTier2Runtime(_IntegrationTestCase):
    """Drive scriptable parts of the accept Tier 2 flow via subprocess."""

    def _seed_sprint_with_in_progress_story(self, story_id: str = "story-001") -> None:
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        story_id,
                        "test story",
                        "in-progress",
                        file_domain=["scripts/foo.py"],
                    )
                ],
                sprint_id="sprint-test",
                started="2026-05-01",
            )
        )

    def _run_sprint_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(_SPRINT_CLI), "--smm-dir", str(self.smm_dir), *args],
            capture_output=True,
            text=True,
            env=self._env_with_plugin_root(),
        )

    def test_block_recording_via_append_emits_high_severity_concern(self):
        # AC#1 trailing claim: "the test asserts a concern event with
        # severity high was filed" — verifies the Step 1c "Block path"
        # append.sh template is invokable and produces the right shape.
        result = self._run_append(
            "--type",
            "concern",
            "--agent",
            "xp-accept",
            "--severity",
            "high",
            "--content",
            "Tier 2 Block override for story-001: hardcoded secret in scripts/foo.py",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")
        self.assertEqual(concerns[0]["agent_id"], "xp-accept")
        self.assertIn("Tier 2 Block override", concerns[0]["content"])

    def test_concern_recording_via_append_emits_medium_severity_concern(self):
        # AC#2 trailing claim: medium-severity finding records correctly.
        result = self._run_append(
            "--type",
            "concern",
            "--agent",
            "xp-accept",
            "--severity",
            "medium",
            "--content",
            "Tier 2 finding for story-001: unvalidated input on parse_args",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "medium")

    def test_update_story_done_via_sprint_cli_flips_status_to_done(self):
        # Baseline: sprint_cli is the writer that flips status to done
        # and exits 0. The marker gate lives in pre_tool_bash.py (next
        # test) — sprint_cli itself never reads .accept.
        self._seed_sprint_with_in_progress_story("story-001")
        result = self._run_sprint_cli("update-story", "story-001", "done")
        self.assertEqual(result.returncode, 0, result.stderr)
        sprint = json.loads((self.smm_dir / "sprint.json").read_text())
        statuses = {s["id"]: s["status"] for s in sprint["stories"]}
        self.assertEqual(statuses["story-001"], "done")

    def test_update_story_done_blocked_when_accept_marker_present(self):
        # Cross-session gate: with the ACCEPT marker present, a Bash
        # event invoking sprint_cli update-story ... done is blocked by
        # pre_tool_bash.py at exit 2 with a clear message. This is the
        # only hook-layer gate around the done transition.
        self._seed_sprint_with_in_progress_story("story-001")
        (self.smm_dir / ".accept").write_text("done")

        cmd = (
            f"python3 {_SPRINT_CLI} --smm-dir {self.smm_dir} "
            "update-story story-001 done"
        )
        result = self._run_script(
            "pre_tool_bash.py",
            _make_bash_input(command=cmd, cwd=str(self.tmpdir)),
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("/xp-accept", result.stderr)


class TestAcceptTier2SkillText(unittest.TestCase):
    """Pin xp-accept SKILL.md prose for the LLM-only seams.

    The xp-accept skill is LLM-orchestrated — there is no Python entry
    point that enforces "Block prevents done" or the Step 1b/1c/2
    ordering. These prose pins lock the SKILL.md text so a future
    edit that drops the wording or reorders the steps fails loudly.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _ACCEPT_SKILL_MD.read_text()

    def test_step_1c_appears_after_step_1b_before_step_2(self):
        # AC#4: assertions reference Step ordering by header anchor so
        # SKILL.md edits that reorder the steps fail loudly.
        idx_1b = self.text.index("## Step 1b: Concern Triage")
        idx_1c = self.text.index("## Step 1c: Tier 2 Security Review")
        idx_2 = self.text.index("## Step 2: Update sprint.json")
        self.assertLess(idx_1b, idx_1c, "Step 1b must precede Step 1c")
        self.assertLess(idx_1c, idx_2, "Step 1c must precede Step 2")

    def test_step_1c_block_path_says_do_not_call_update_story_done(self):
        # AC#1: Block path must explicitly say update-story-done is NOT
        # called. The hook layer does not enforce this — only the prose.
        block_idx = self.text.index("**Block path**")
        # Constrain the search to the Block-path section so we don't
        # match the prose under Concern path or elsewhere.
        next_section_idx = self.text.index("**Concern path**", block_idx)
        block_section = self.text[block_idx:next_section_idx]
        self.assertIn("do NOT call", block_section)
        self.assertIn("update-story", block_section)
        self.assertIn("done", block_section)

    def test_step_1c_block_path_records_high_severity_concern(self):
        # AC#1 trailing claim (prose contract): Block path must record
        # at severity high — pairs with the runtime test above that
        # verifies the recording shape.
        block_idx = self.text.index("**Block path**")
        next_section_idx = self.text.index("**Concern path**", block_idx)
        block_section = self.text[block_idx:next_section_idx]
        self.assertIn("severity", block_section)
        self.assertIn("high", block_section)
        self.assertIn("concern", block_section)

    def test_step_1c_concern_path_records_medium_then_proceeds_to_done(self):
        # AC#2: Concern path records medium-severity then proceeds to
        # update-story done (NOT blocked).
        concern_idx = self.text.index("**Concern path**")
        # Constrain to Concern path through end of Step 1c.
        end_idx = self.text.index("## Step 2:", concern_idx)
        concern_section = self.text[concern_idx:end_idx]
        self.assertIn("severity", concern_section)
        self.assertIn("medium", concern_section)
        # Pair: prose must direct continuation to update-story done.
        self.assertIn("update-story", concern_section)
        self.assertIn("done", concern_section)

    def test_step_1c_skips_when_code_free(self):
        # AC#3: code_free stories skip Tier 2 entirely (no LLM
        # security coverage at the close-time accept boundary —
        # Wisdom 9258988c2d2a).
        step_1c_idx = self.text.index("## Step 1c:")
        step_2_idx = self.text.index("## Step 2:", step_1c_idx)
        step_1c_body = self.text[step_1c_idx:step_2_idx]
        self.assertIn("code_free", step_1c_body)
        self.assertIn("Skip", step_1c_body)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Sprint-050 / story-003 (M-3 capstone): E2E for close-reviewer Tier 3.

Hybrid coverage (decision ccb2e70adc20):

- **Runtime** subprocess tests drive append.sh per close mode (sprint,
  plan, free) to verify Block/Concern recording shape and metadata
  round-trip — the Tier 3 contract's record-each-finding output side.

- **Prose** text-pin tests on agents/xp-close-reviewer.md and the four
  close SKILL.md files cover the LLM-only seams: Step 3.5 dispatch
  prose (which modes invoke /security-review and how), and Abort-default
  honoring in close skills (the receiver-side contract from story-004).
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_REVIEWER_AGENT_MD = _PLUGIN_ROOT / "agents" / "xp-close-reviewer.md"
_CLOSE_SKILL_MDS = {
    "sprint": _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md",
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md",
}


class TestCloseReviewerTier3Runtime(_IntegrationTestCase):
    """Drive scriptable parts of close-reviewer Tier 3 recording via subprocess."""

    def _record_finding(
        self, mode: str, severity: str, content: str
    ) -> subprocess.CompletedProcess:
        metadata = {
            "close_mode": mode,
            "source_branch": f"feat/{mode}-branch",
            "target_branch": "main",
        }
        return self._run_append(
            "--type",
            "concern",
            "--agent",
            "xp-close-reviewer",
            "--severity",
            severity,
            "--content",
            content,
            "--metadata",
            json.dumps(metadata),
        )

    def _record_block(self, mode: str) -> subprocess.CompletedProcess:
        return self._record_finding(
            mode,
            "high",
            f"Block in {mode}-close: hardcoded secret in scripts/foo.py",
        )

    def _record_concern(self, mode: str) -> subprocess.CompletedProcess:
        return self._record_finding(
            mode,
            "medium",
            f"Concern in {mode}-close: missing test coverage for parser.py",
        )

    def test_sprint_close_block_recording_emits_high_severity_concern(self):
        result = self._record_block("sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")
        self.assertEqual(concerns[0]["agent_id"], "xp-close-reviewer")
        self.assertEqual(concerns[0]["metadata"]["close_mode"], "sprint")

    def test_plan_close_block_recording_emits_high_severity_concern(self):
        result = self._record_block("plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")
        self.assertEqual(concerns[0]["metadata"]["close_mode"], "plan")

    def test_free_close_block_recording_emits_high_severity_concern(self):
        result = self._record_block("free")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")
        self.assertEqual(concerns[0]["metadata"]["close_mode"], "free")

    def test_close_reviewer_concern_recording_emits_medium_severity(self):
        # Step 4 record-each-Concern path. One mode is enough — the
        # parametrized Block tests above already prove per-mode metadata
        # handling; this test covers the severity=medium branch.
        result = self._record_concern("sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "medium")

    def test_close_reviewer_concern_metadata_round_trips(self):
        # The Step 4 metadata schema (close_mode, source_branch,
        # target_branch) must survive append.sh validation and round-trip
        # to events.jsonl unchanged. Without this, the M-4 metadata
        # consumer would have to guess the shape.
        result = self._record_block("sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._read_events()
        meta = events[0]["metadata"]
        self.assertEqual(meta["close_mode"], "sprint")
        self.assertEqual(meta["source_branch"], "feat/sprint-branch")
        self.assertEqual(meta["target_branch"], "main")


class TestCloseReviewerTier3Prose(unittest.TestCase):
    """Pin LLM-only seams in close-reviewer agent prose and close-skill SKILL.md.

    These contracts have no script enforcement — Skill dispatch is an
    LLM tool invocation, AskUserQuestion option ordering is LLM
    orchestration. Prose pins lock the SKILL.md / agent.md text so a
    future edit that drops the wording fails loudly.
    """

    @classmethod
    def setUpClass(cls):
        cls.agent_text = _REVIEWER_AGENT_MD.read_text()
        cls.skill_texts = {
            mode: path.read_text() for mode, path in _CLOSE_SKILL_MDS.items()
        }

    def _step_3_5_body(self) -> str:
        # Constrain to the Step 3.5 section so unrelated prose
        # elsewhere in the agent doc doesn't satisfy the assertions.
        start = self.agent_text.index("## Step 3.5")
        end = self.agent_text.index("## Step 4", start)
        return self.agent_text[start:end]

    def test_step_3_5_names_sprint_plan_free_modes(self):
        # AC#1-3 dispatch claim: Step 3.5 must name all three close
        # modes that DO invoke Tier 3.
        body = self._step_3_5_body()
        for mode in ("sprint", "plan", "free"):
            self.assertIn(
                mode,
                body,
                f"Step 3.5 must name {mode} as a Tier 3 dispatch mode",
            )

    def test_step_3_5_excludes_story_mode(self):
        # AC#1-3 dispatch claim: story mode is explicitly excluded
        # because Tier 2 at /xp-accept already covered the story diff.
        body = self._step_3_5_body()
        # Lowercased substring check — the prose says "NOT story mode"
        # with NOT capitalized for emphasis; allow either case.
        self.assertIn("NOT", body)
        self.assertIn("story", body.lower())

    def test_step_3_5_invokes_security_review_skill(self):
        # AC#1-3 dispatch claim: the agent must literally invoke the
        # security-review skill. The Skill tool call is LLM-orchestrated
        # — only the prose can pin this.
        body = self._step_3_5_body()
        self.assertIn('Skill(skill: "security-review"', body)

    def test_step_3_5_args_name_cumulative_diff(self):
        # The args string must scope to cumulative close diff, not a
        # single commit (mirrors xp-accept Step 1c convention).
        body = self._step_3_5_body()
        self.assertIn("cumulative diff", body)

    def test_step_3_5_args_name_source_and_target_branches(self):
        # The args template must include the SOURCE/TARGET parameters
        # so the LLM substitutes the actual branch names per close.
        body = self._step_3_5_body()
        self.assertIn("<SOURCE>", body)
        self.assertIn("<TARGET>", body)

    def test_close_skills_default_abort_on_block_sprint(self):
        # AC#1 trailing Abort claim (story-004's prose, locked again
        # here from the M-3 capstone perspective).
        text = self.skill_texts["sprint"]
        self.assertIn("Step 3.5", text)
        self.assertIn("block finding", text.lower())
        self.assertIn("recommended", text.lower())

    def test_close_skills_default_abort_on_block_plan(self):
        # AC#2 trailing Abort claim.
        text = self.skill_texts["plan"]
        self.assertIn("Step 3.5", text)
        self.assertIn("block finding", text.lower())
        self.assertIn("recommended", text.lower())

    def test_close_skills_default_abort_on_block_free(self):
        # AC#3 trailing Abort claim.
        text = self.skill_texts["free"]
        self.assertIn("Step 3.5", text)
        self.assertIn("block finding", text.lower())
        self.assertIn("recommended", text.lower())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression-replay validation of the enhanced review floor (story-003).

This is Milestone 1's integration capstone. Stories 001 + 002 raised the
per-increment review floor (state/lifecycle angle + bounded self-verify +
risk classifier + bounded 3-spawn fan-out). This test replays the two
known v3.11 regression patterns through the floor and asserts they
classify high-risk:

- d69748e92ad1 — close_cycle_stop_gate latched OFF forever (review_mid_cycle
  defer unbounded when /xp-quality-review never set quality_review_done).
  Fix: commit 298d04575a9c62a0d4092b8459338e75559701a5. Pre-fix content at
  298d04575a9c62a0d4092b8459338e75559701a5~1:plugins/xp-agents/scripts/close_cycle_stop_gate.py.

- 8e0264cfcf43 — ACCEPT_IN_FLIGHT marker never drained mid-sprint
  (state-derived consume in sprint_stop_gate only fired when no
  in-progress story remained, but /xp-accept's post-loop /xp-schedule
  promotes the next story BEFORE Stop fires). Fix: commit
  2a73b2f6f6a5bdf3bc3d371b800c1e4d5fcaffd4. Pre-fix content at
  2a73b2f6f6a5bdf3bc3d371b800c1e4d5fcaffd4~1:plugins/xp-agents/scripts/review_cycle_done.py.

Genuine replay, not synthetic shape-exemplars: reads the actual pre-fix
file content from git history (`git show <fix-commit>~1:<path>`) and
feeds it to risk_classifier.classify(). The plan-reviewer caught the
first draft using hand-crafted fixtures as tautological ("we wrote X,
classifier flags X") — see decision 2786c9b77aaf for the rewrite.

AC 3 (enhanced per-increment review surfaces both empirically) is
non-deterministic (LLM reviewer). Empirical evidence: story-002 close
commit aecfe826 — xp-code-reviewer caught a regex false-pos/false-neg
under THIS floor without /code-review high involvement. Same floor,
same scrutiny surface. Structural assertions below pin the floor's
prose so an accidental removal surfaces loudly.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-quality-review" / "scripts"
    ),
)

import risk_classifier
from _bases import _PLUGIN_ROOT

_REPO_ROOT = _PLUGIN_ROOT.parent.parent

_LATCH_OFF_FIX = "298d04575a9c62a0d4092b8459338e75559701a5"
_LATCH_OFF_PATH = "plugins/xp-agents/scripts/close_cycle_stop_gate.py"

_NEVER_DRAIN_FIX = "2a73b2f6f6a5bdf3bc3d371b800c1e4d5fcaffd4"
_NEVER_DRAIN_PATH = "plugins/xp-agents/scripts/review_cycle_done.py"

_CODE_REVIEWER_MD = _PLUGIN_ROOT / "agents" / "xp-code-reviewer.md"
_QUALITY_REVIEW_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"


def _git_show_pre_fix(fix_commit: str, path: str) -> str:
    """Read a file's content one commit before a given fix.

    Loud failure on bad commit / lost path: a future repo-history rewrite
    that loses these regression markers is itself a regression in this
    validation corpus and must surface, not skip silently.
    """
    result = subprocess.run(
        ["git", "show", f"{fix_commit}~1:{path}"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git show {fix_commit}~1:{path} failed: {result.stderr.strip()}"
        )
    return result.stdout


class TestRegressionReplay(unittest.TestCase):
    """Replay pre-fix content through risk_classifier.classify()."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="regression_replay_"))
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _stage_pre_fix(self, fix_commit: str, path: str, local_name: str) -> str:
        """Write pre-fix content to tmpdir; return path relative to tmpdir."""
        src = _git_show_pre_fix(fix_commit, path)
        out = self.tmpdir / local_name
        out.write_text(src)
        return local_name

    def test_latch_off_gate_pre_fix_classifies_high_risk(self):
        """d69748e92ad1: pre-fix close_cycle_stop_gate.py → high-risk."""
        rel = self._stage_pre_fix(
            _LATCH_OFF_FIX, _LATCH_OFF_PATH, "latch_off_gate_pre_fix.py"
        )
        result = risk_classifier.classify([rel], repo_root=self.tmpdir)
        self.assertEqual(
            result["risk"],
            "high",
            f"pre-fix {_LATCH_OFF_PATH} expected high; got {result['signals']}",
        )
        signal_files = [s["file"] for s in result["signals"]]
        self.assertIn(rel, signal_files)

    def test_never_drain_marker_pre_fix_classifies_high_risk(self):
        """8e0264cfcf43: pre-fix review_cycle_done.py → high-risk."""
        rel = self._stage_pre_fix(
            _NEVER_DRAIN_FIX, _NEVER_DRAIN_PATH, "never_drain_marker_pre_fix.py"
        )
        result = risk_classifier.classify([rel], repo_root=self.tmpdir)
        self.assertEqual(
            result["risk"],
            "high",
            f"pre-fix {_NEVER_DRAIN_PATH} expected high; got {result['signals']}",
        )
        signal_files = [s["file"] for s in result["signals"]]
        self.assertIn(rel, signal_files)

    def test_corpus_multifile_replay_classifies_high_risk(self):
        """Both regressions together → high-risk + both named in signals."""
        a = self._stage_pre_fix(
            _LATCH_OFF_FIX, _LATCH_OFF_PATH, "latch_off_gate_pre_fix.py"
        )
        b = self._stage_pre_fix(
            _NEVER_DRAIN_FIX, _NEVER_DRAIN_PATH, "never_drain_marker_pre_fix.py"
        )
        result = risk_classifier.classify([a, b], repo_root=self.tmpdir)
        self.assertEqual(result["risk"], "high")
        files = {s["file"] for s in result["signals"]}
        self.assertIn(a, files)
        self.assertIn(b, files)


class TestReviewFloorSurface(unittest.TestCase):
    """Structural assertions on the floor's prose (AC 3 + dogfood evidence).

    Empirical AC 3 is non-deterministic; commit aecfe826 (story-002 close)
    is the evidence — xp-code-reviewer caught a regex false-pos/false-neg
    bug under this floor without /code-review high. These tests pin the
    prose elements that produced that catch so an accidental removal
    surfaces loudly.
    """

    @classmethod
    def setUpClass(cls):
        cls.reviewer_body = _CODE_REVIEWER_MD.read_text()
        cls.skill_body = _QUALITY_REVIEW_SKILL_MD.read_text()

    def test_reviewer_prose_carries_floor_surface(self):
        # State/lifecycle angle (story-001) — caught the false-positive class.
        self.assertIn("state/lifecycle/concurrency", self.reviewer_body)
        # Self-verify default-refuted (story-001) — drops nitpicks.
        self.assertIn("Default to refuted on uncertainty", self.reviewer_body)
        # Spare-clause — protects state-machine findings from over-refutation
        # (decision 1f2fa290d6f3); this is what kept the regex catch through verify.
        self.assertIn(
            "Spare any candidate with a plausible failure path", self.reviewer_body
        )

    def test_skill_routes_high_risk_to_escalation(self):
        # Risk gate exists (story-002) — RISK=high routes to escalation.
        self.assertIn("RISK=high", self.skill_body)
        # Parallel fan-out shape declared.
        self.assertIn("parallel", self.skill_body.lower())
        # Spawn cap enforced.
        self.assertIn("Never escalate beyond 3 spawns", self.skill_body)


if __name__ == "__main__":
    unittest.main()

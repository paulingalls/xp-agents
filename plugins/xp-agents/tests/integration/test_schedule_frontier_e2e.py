#!/usr/bin/env python3
"""Capstone E2E (story-007): the frontier-driven mode-selection loop composes.

Milestone 1 built the mechanism across stories 001-006 (ready-frontier query +
schedule_gate_active predicate, /xp-schedule skill + preload, narrowed
/xp-assign, teammate-only .assign-pending gate, state-derived write +
EnterPlanMode enforcement gates, rewired orchestration). This test walks the
full loop end-to-end via the real hook subprocesses + CLI primitives — no SKILL
prose — and fails loud if any seam regresses:

  scheduled sprint -> gates block writes + plan-entry -> /xp-schedule promotes a
  solo frontier -> gates self-clear AND no .assign-pending -> (teammate frontier
  arms the assign gate instead) -> close merges without promoting -> /xp-schedule
  promotes the next frontier off the merged tip.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_store
from _bases import _PLUGIN_ROOT
from _branching_fixtures import (
    branch_exists,
    get_current_branch_at,
    make_commit,
    merge_teammate_branch,
    write_system_context,
)
from conftest import _extract_preload_var, _IntegrationTestCase
from conftest import make_sprint_dict as _make_sprint
from conftest import make_story_dict as _make_story

_SCHEDULE_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-schedule" / "scripts" / "preload.sh"
_BRANCHING = _PLUGIN_ROOT / "scripts" / "branching.py"


class TestScheduleFrontierE2E(_IntegrationTestCase):
    def setUp(self):
        # The class-shared git repo accumulates branches + merge commits across
        # methods (test_close merges into main). The base setUp scrubs the
        # working tree but leaves committed-then-deleted files dirty; force a
        # clean main tree so branching.py create's dirty-tree guard doesn't trip
        # on a sibling method's merge.
        super().setUp()
        for args in (["checkout", "-f", "main"], ["reset", "--hard", "HEAD"]):
            subprocess.run(
                ["git", *args], cwd=self.tmpdir, capture_output=True, check=False
            )

    # -- helpers ----------------------------------------------------------

    def _write_sprint(self, stories) -> None:
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=stories))
        )

    def _write_input(self) -> dict:
        return {
            "session_id": "cap",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.py", "content": "x = 1"},
            "agent_id": "main",
            "cwd": str(self.tmpdir),
        }

    def _plan_input(self) -> dict:
        return {
            "session_id": "cap",
            "tool_name": "EnterPlanMode",
            "tool_input": {},
            "agent_id": "main",
            "cwd": str(self.tmpdir),
        }

    def _reviewer_input(self) -> dict:
        return {
            "session_id": "cap",
            "agent_id": "plan-reviewer-1",
            "agent_type": "xp-plan-reviewer",
            "last_assistant_message": "Plan reviewed.",
        }

    def _schedule_preload(self):
        out = self._run_preload(_SCHEDULE_PRELOAD)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def _branching_create(self, story_id: str, slug: str, base: str) -> None:
        r = subprocess.run(
            [
                sys.executable,
                str(_BRANCHING),
                "--smm-dir",
                str(self.smm_dir),
                "create",
                "--cwd",
                str(self.tmpdir),
                "--story",
                story_id,
                "--slug",
                slug,
                "--base",
                base,
            ],
            cwd=str(self.tmpdir),
            env=self._test_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def _assign_pending(self) -> bool:
        return (self.smm_dir / ".assign-pending").exists()

    # -- AC #1: solo frontier — gates block, then self-clear, no assign gate

    def test_solo_frontier_gates_then_clears(self):
        write_system_context(self.smm_dir, 2)
        base = get_current_branch_at(self.tmpdir)
        self._write_sprint(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                )
            ]
        )

        # The frontier is a single solo story.
        out = self._schedule_preload()
        self.assertEqual(_extract_preload_var(out, "FRONTIER_COUNT"), "1")
        self.assertEqual(_extract_preload_var(out, "FRONTIER_IDS"), "story-001")
        self.assertEqual(_extract_preload_var(out, "PARALLELIZABLE"), "false")

        # Pre-promotion window: both gates block, pointing at /xp-schedule.
        wb = self._run_script("pre_tool_write.py", self._write_input())
        self.assertEqual(wb.returncode, 2, wb.stderr)
        self.assertIn("xp-schedule", wb.stderr)
        pb = self._run_script("pre_tool_plan_mode.py", self._plan_input())
        self.assertEqual(pb.returncode, 2, pb.stderr)
        self.assertIn("xp-schedule", pb.stderr)

        # /xp-schedule solo promotion: in-progress + execution_mode=solo + branch.
        sprint_store.update_story_status(self.smm_dir, "story-001", "in-progress")
        sprint_store.edit_story(self.smm_dir, "story-001", {"execution_mode": "solo"})
        self._branching_create("story-001", "cap-solo", base)

        # Both gates self-clear (none-in-progress flipped).
        wo = self._run_script("pre_tool_write.py", self._write_input())
        self.assertEqual(wo.returncode, 0, wo.stderr)
        po = self._run_script("pre_tool_plan_mode.py", self._plan_input())
        self.assertEqual(po.returncode, 0, po.stderr)

        # Plan review completes: solo skips the assign gate — no marker.
        ss = self._run_script("subagent_stop.py", self._reviewer_input())
        self.assertEqual(ss.returncode, 0, ss.stderr)
        self.assertFalse(self._assign_pending())

    # -- AC #2: teammate frontier — plan review ARMS the assign gate

    def test_teammate_frontier_arms_assign_gate(self):
        write_system_context(self.smm_dir, 2)
        self._write_sprint(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["b.py — y"],
                ),
            ]
        )

        out = self._schedule_preload()
        self.assertEqual(_extract_preload_var(out, "FRONTIER_COUNT"), "2")
        self.assertEqual(_extract_preload_var(out, "PARALLELIZABLE"), "true")

        # /xp-schedule parallel promotion: every frontier story -> teammate.
        for sid in ("story-001", "story-002"):
            sprint_store.update_story_status(self.smm_dir, sid, "in-progress")
            sprint_store.edit_story(self.smm_dir, sid, {"execution_mode": "teammate"})

        # Plan review completes: teammate mode arms .assign-pending for /xp-assign.
        ss = self._run_script("subagent_stop.py", self._reviewer_input())
        self.assertEqual(ss.returncode, 0, ss.stderr)
        self.assertTrue(self._assign_pending())

    # -- AC #3: close does not promote; /xp-schedule advances the next frontier

    def test_close_leaves_next_then_schedule_promotes(self):
        write_system_context(self.smm_dir, 2)
        base = get_current_branch_at(self.tmpdir)
        self._write_sprint(
            [
                _make_story(
                    id="story-001",
                    status="in-progress",
                    dependencies=[],
                    branch_name="cap-001-b",
                    execution_mode="solo",
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["b.py — y"],
                ),
            ]
        )

        # story-001 lands a commit then closes (merge).
        make_commit(str(self.tmpdir), "cap-001-b", "f1.txt", "x", "[story-001] f1")
        merge = merge_teammate_branch(
            str(self.tmpdir), "cap-001-b", base, self._test_env
        )
        self.assertEqual(merge.returncode, 0, merge.stderr)

        # Close did NOT promote the next story (story-006 ownership split).
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-002")["status"], "scheduled"
        )

        # Mark 001 done; the frontier now offers story-002.
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        out = self._schedule_preload()
        self.assertEqual(_extract_preload_var(out, "FRONTIER_IDS"), "story-002")

        # /xp-schedule promotes the next frontier off the merged tip.
        sprint_store.update_story_status(self.smm_dir, "story-002", "in-progress")
        self._branching_create("story-002", "cap-next", base)
        promoted = sprint_store.get_story(self.smm_dir, "story-002")
        self.assertEqual(promoted["status"], "in-progress")
        self.assertTrue(promoted.get("branch_name"))
        self.assertTrue(branch_exists(str(self.tmpdir), promoted["branch_name"]))


if __name__ == "__main__":
    import unittest

    unittest.main()

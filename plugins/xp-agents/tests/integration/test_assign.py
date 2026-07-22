#!/usr/bin/env python3
"""Integration tests for xp-assign: WorktreeCreate hook and shared helpers.

Preload tests in test_assign_preload.py, teammate tests in test_assign_team.py.
"""

import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from conftest import (
    _extract_preload_var,
    _IntegrationTestCase,
    _s,
    _sprint_json,
    cleanup_test_worktrees,
    make_event,
)
from event_schema import EVENT_TYPE_DECISION

_PRELOAD_SCRIPT = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"


class TestAssignForensicLogSurfacing(unittest.TestCase):
    """The /xp-assign SKILL must point mid-flight teammate diagnosis at the
    LIVE forensic `.log` (line-flushed by run_with_tee), not at the task
    `.output` capture — which is the filter's stdout and stays ~0 bytes until
    the teammate exits (the filter swallows stdin and prints one summary line
    at the end; it does NOT tee). story-005 surfaces the live-log `tail -f`
    target via `spawn_teammate.py --print-log-path` and corrects the docs.
    """

    @classmethod
    def setUpClass(cls):
        cls.skill = (_PLUGIN_ROOT / "skills" / "xp-assign" / "SKILL.md").read_text(
            encoding="utf-8"
        )

    def test_surfaces_live_log_tail_target(self):
        """The SKILL names the live-log tail target via --print-log-path + tail."""
        self.assertIn(
            "--print-log-path",
            self.skill,
            "SKILL must query the live forensic-log path via "
            "spawn_teammate.py --print-log-path",
        )
        self.assertRegex(
            self.skill.lower(),
            r"tail\b",
            "SKILL must instruct tailing the live forensic .log for mid-flight "
            "progress / stall diagnosis",
        )

    def test_no_false_filter_tee_claim(self):
        """The SKILL must not claim the output filter tees stdin->stdout — it
        doesn't; the task .output holds only the final summary."""
        self.assertNotIn(
            "tee'd it",
            self.skill,
            "SKILL must not claim teammate_output_filter.py 'tee'd' the task "
            "output — the filter swallows stdin and emits one summary at exit",
        )


class TestWorktreeCreateSubprocess(_IntegrationTestCase):
    """WorktreeCreate hook via subprocess with real git repo."""

    def test_creates_worktree_from_non_default_branch(self):
        """On a non-default branch, worktree is created from that branch."""
        # Create a feature branch
        subprocess.run(
            ["git", "checkout", "-b", "feature/v2"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        # Add a commit on the feature branch so it diverges
        (self.tmpdir / "v2.txt").write_text("v2 content")
        subprocess.run(
            ["git", "add", "v2.txt"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "v2 commit"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # Platform sends name only — hook generates path
        result = self._run_script(
            "worktree_create.py",
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": "test-wt",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        wt_path = result.stdout.strip()
        self.assertTrue(Path(wt_path).is_dir(), "Worktree should exist")

        # v2.txt should be present (branched from feature/v2, not main)
        self.assertTrue(
            (Path(wt_path) / "v2.txt").is_file(),
            "Worktree should contain v2.txt from feature branch",
        )

    def test_creates_worktree_on_default_branch(self):
        """On the default branch, worktree is created normally."""
        result = self._run_script(
            "worktree_create.py",
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": "default-wt",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        wt_path = result.stdout.strip()
        self.assertTrue(Path(wt_path).is_dir())

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        super().tearDown()


class TestAssignPerStorySpawnShape(_IntegrationTestCase):
    """story-003: the reshaped /xp-assign drives ONE spawn per invocation,
    forwarding the story's executor_model to spawn_teammate's --model flag
    (story-002 added the schema field; story-003 wires the consumer). These
    tests pin the component-level wire-up the SKILL.md prose orchestrates;
    the prose pins themselves live in tests/hooks/test_assign.py.
    """

    def setUp(self):
        super().setUp()
        # Seed a sprint with story-001 in-progress so spawn_teammate.main's
        # post-spawn CAS promotion (in-progress → reviewing) succeeds.
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Test story", "in-progress")],
                sprint_id="sprint-test",
                started="2026-06-28",
            )
        )

    def _spawn_with_captured_cmd(self, argv: list[str]) -> list[str]:
        """Run spawn_teammate.main(argv) with both side-effects mocked,
        returning the cmd list that would have been passed to claude -p.
        """
        import spawn_teammate

        captured: list[list[str]] = []

        def capture_cmd(cmd, **_kwargs):
            captured.append(list(cmd))

        prompt_file = Path(self.tmpdir) / f"prompt-{argv[1]}.txt"
        # argv[1] is the teammate name (worktree-story-NNN), so it carries the
        # story id — spawn refuses a prompt that does not name the story it is
        # spawning, since prompt files outlive their story (story-014).
        prompt_file.write_text(f"story prompt for {argv[1]}")
        argv_with_prompt = [*argv, "--prompt-file", str(prompt_file)]

        with (
            unittest.mock.patch.object(
                spawn_teammate, "create_worktree", return_value=str(self.tmpdir)
            ),
            unittest.mock.patch.object(
                spawn_teammate, "run_with_tee", side_effect=capture_cmd
            ),
        ):
            spawn_teammate.main(argv_with_prompt)

        self.assertEqual(len(captured), 1, "expected exactly one claude -p invocation")
        return captured[0]

    def test_spawn_forwards_executor_model_to_model_flag(self):
        """When /xp-assign reads executor_model='sonnet' from sprint.json and
        passes --model sonnet to spawn_teammate.main, the resulting claude -p
        command carries --model sonnet. Pins the contract story-002 + story-003
        depend on (executor_model schema slot -> --model spawn flag)."""
        cmd = self._spawn_with_captured_cmd(
            [
                "--name",
                "worktree-story-001",
                "--smm-dir",
                str(self.smm_dir),
                "--story-id",
                "story-001",
                "--model",
                "sonnet",
                "--plugin-dir",
                str(_PLUGIN_ROOT),
            ]
        )
        self.assertIn("--model", cmd)
        model_idx = cmd.index("--model")
        self.assertEqual(cmd[model_idx + 1], "sonnet")

    def test_spawn_omits_model_flag_when_executor_model_absent(self):
        """When the story has no executor_model, /xp-assign omits --model
        from the spawn call. The claude -p invocation must not carry --model."""
        cmd = self._spawn_with_captured_cmd(
            [
                "--name",
                "worktree-story-001",
                "--smm-dir",
                str(self.smm_dir),
                "--story-id",
                "story-001",
                "--plugin-dir",
                str(_PLUGIN_ROOT),
            ]
        )
        self.assertNotIn("--model", cmd)

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        super().tearDown()


class TestAssignMixedFrontierE2E(_IntegrationTestCase):
    """story-008 E2E: the frontier that actually blocked an assign this session.

    Six teammate stories in flight plus one pulled-forward solo hotfix. The
    preload used to suppress SOLO_TARGET whenever a batch existed, so the solo
    story was unassignable for as long as ANY teammate was live: /xp-assign
    resolved a teammate while the lead held the solo story's plan — the
    plan/story mispairing the SKILL itself warns about.

    The unit fixtures in test_assign_preload_tier_target.py use one teammate;
    this reproduces the real batch size, because the suppression scaled with the
    batch and "six teammates" is the state that has to stay routable.
    """

    def _write_sprint(self, sprint_json: str) -> None:
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def _blocked_frontier(self) -> str:
        """Six in-progress teammate stories + one in-progress solo story."""
        stories = [
            _s(
                f"story-{n:03d}",
                f"Teammate story {n}",
                "in-progress",
                execution_mode="teammate",
            )
            for n in range(1, 7)
        ]
        stories.append(
            _s(
                "story-008",
                "Pulled-forward solo fix",
                "in-progress",
                execution_mode="solo",
            )
        )
        return _sprint_json(stories, sprint_id="sprint-mixed", started="2026-07-01")

    def test_solo_story_is_the_target_despite_six_live_teammates(self):
        """AC: SOLO_TARGET names the solo story rather than being empty, and it
        is the tier-lookup target — so Step 0 applies the SOLO story's
        recommendation instead of a teammate's."""
        self._write_sprint(self._blocked_frontier())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "SOLO_TARGET"), "story-008"
        )
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-008"
        )
        # The batch is intact — solo-first reorders selection, it drops nothing.
        self.assertEqual(
            (_extract_preload_var(result.stdout, "TEAMMATE_STORY_IDS") or "").split(),
            [f"story-{n:03d}" for n in range(1, 7)],
        )

    def test_the_solo_storys_own_tier_recommendation_is_what_resolves(self):
        """The mispairing had a second half: even reaching the solo story, the
        lead would apply whatever tier the preload looked up. With
        recommendations seeded for BOTH a teammate and the solo story, the solo
        story's must win — otherwise Step 0's target-identity check trips and
        silently discards the plan-reviewer's pick."""
        self._write_sprint(self._blocked_frontier())
        self._seed_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    ts="2026-07-02T00:00:00+00:00",
                    metadata={
                        "recommended_model": "haiku",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                ),
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-008",
                    ts="2026-07-02T00:00:00+00:00",
                    metadata={
                        "recommended_model": "opus",
                        "story_id": "story-008",
                        "advisory": True,
                    },
                ),
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-008"
        )
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "opus"
        )


if __name__ == "__main__":
    unittest.main()

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
    _IntegrationTestCase,
    _s,
    _sprint_json,
    cleanup_test_worktrees,
)

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_preload_var(stdout: str, name: str) -> str | None:
    """Extract a VAR=value from preload stdout. Returns value or None."""
    prefix = f"{name}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1]
    return None


# ---------------------------------------------------------------------------
# Sprint fixture helpers for mode selection tests
# ---------------------------------------------------------------------------


def _multi_story_sprint_worktree() -> str:
    """Sprint with independent M/L stories and non-overlapping domains."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "User registration",
                "ready",
                file_domain=["src/auth/register.py", "tests/test_register.py"],
            ),
            _s(
                "story-002",
                "Admin dashboard",
                "ready",
                file_domain=["src/admin/dashboard.py", "tests/test_dashboard.py"],
            ),
        ],
        sprint_id="sprint-001",
        started="2026-04-01",
    )


def _multi_story_sprint_solo_deps() -> str:
    """Sprint with dependency chains (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "User model",
                "ready",
                file_domain=["src/models/user.py"],
            ),
            _s(
                "story-002",
                "User API",
                "ready",
                file_domain=["src/api/user.py"],
                dependencies=["story-001"],
            ),
        ],
        sprint_id="sprint-002",
        started="2026-04-01",
    )


def _multi_story_sprint_all_small() -> str:
    """Sprint with all S stories (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "Fix typo",
                "ready",
                file_domain=["src/ui/header.py"],
            ),
            _s(
                "story-002",
                "Update readme",
                "ready",
                file_domain=["docs/README.md"],
            ),
        ],
        sprint_id="sprint-003",
        started="2026-04-01",
    )


def _multi_story_sprint_no_domains() -> str:
    """Sprint with missing file domains (forces solo mode)."""
    return _sprint_json(
        [
            _s("story-001", "Feature A", "ready"),
            _s("story-002", "Feature B", "ready"),
        ],
        sprint_id="sprint-004",
        started="2026-04-01",
    )


def _multi_story_sprint_overlapping_domains() -> str:
    """Sprint with overlapping file domains (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "Auth flow",
                "ready",
                file_domain=["src/auth/login.py", "src/shared/utils.py"],
            ),
            _s(
                "story-002",
                "Password reset",
                "ready",
                file_domain=["src/auth/reset.py", "src/shared/utils.py"],
            ),
        ],
        sprint_id="sprint-005",
        started="2026-04-01",
    )


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


if __name__ == "__main__":
    unittest.main()

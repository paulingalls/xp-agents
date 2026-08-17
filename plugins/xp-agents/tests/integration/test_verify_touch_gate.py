#!/usr/bin/env python3
"""Capstone: M5 verify-touch lifecycle, end to end against real git.

Composes the three Milestone-5 seams over a real temp git repo (no mocked
git boundaries, unlike the per-story unit tests):
- the commit-time nudge (pre_tool_bash, story-002),
- the story-close gate (xp-story-close preload, story-003),
- the [verify-deferred] debt escape (bash_post_tool, story-002),
all over the verify_paths primitive (story-001).

Pure composition pin: passes when the seams are intact, fails if one breaks.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import pre_tool_bash
from _bases import _PLUGIN_ROOT
from _branching_fixtures import append_commit, make_commit, write_system_context
from conftest import _extract_preload_var, _IntegrationTestCase, _make_bash_input
from event_helpers import events_of_type

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"


class TestVerifyTouchLifecycle(_IntegrationTestCase):
    def _seed_story(self, acceptance_execution: dict | None = None) -> None:
        story = {
            "id": "story-001",
            "title": "t",
            "status": "in-progress",
            "dependencies": [],
            "milestone_ref": "",
            "design_sources": "",
            "context": "",
            "file_domain": [],
            "interface_contracts": [],
            "acceptance_criteria": [],
            "acceptance_execution": acceptance_execution
            or {"type": "pytest", "command": "pytest acc_test.py"},
        }
        # Cut the sprint branch too. A sprint seeded at stage 2 whose branch
        # does not exist is the unresolvable state story-008 taught the
        # resolver to refuse — the story-close preload then emits no
        # TARGET_BRANCH and skips the very gate these tests exercise. Pinned at
        # main's tip (with -f: the class shares one repo across tests), which
        # is where the old degraded primary pointed, so every verdict below is
        # unchanged.
        subprocess.run(
            ["git", "branch", "-f", "t/sprint-001-g", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(
                {
                    "sprint_id": "sprint-001",
                    "goal": "g",
                    "started": "2026-05-21",
                    "milestone": "",
                    "branch_name": "t/sprint-001-g",
                    "stories": [story],
                }
            )
        )

    def _story_branch(self, branch: str, filename: str, message: str) -> None:
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        make_commit(str(self.tmpdir), branch, filename, "x", message)

    def _commit_nudge(self, message: str = "wip") -> str | None:
        return pre_tool_bash.run(
            _make_bash_input(
                command=f"git commit -m '{message}'", cwd=str(self.tmpdir)
            ),
            smm_dir=self.smm_dir,
        )

    def _preload_vars(self) -> tuple[str | None, str | None]:
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (
            _extract_preload_var(result.stdout, "VERIFY_UNTOUCHED"),
            _extract_preload_var(result.stdout, "VERIFY_DEFERRED"),
        )

    def setUp(self) -> None:
        super().setUp()
        write_system_context(self.smm_dir, stage=2, integration_branch="main")
        self._seed_story()

    def test_commit_miss_fires_nudge_and_blocks_close(self):
        self._story_branch("u/story-001-a", "other.py", "wip")
        nudge = self._assert_not_none(self._commit_nudge())
        self.assertIn("acc_test.py", nudge)
        untouched, deferred = self._preload_vars()
        self.assertEqual(untouched, "acc_test.py")
        self.assertEqual(deferred, "false")

    def test_touch_clears_nudge_and_passes_close(self):
        self._story_branch("u/story-001-b", "acc_test.py", "add acceptance test")
        self.assertIsNone(self._commit_nudge())
        untouched, _ = self._preload_vars()
        self.assertEqual(untouched, "")

    def test_verify_deferred_suppresses_nudge_bypasses_close_records_debt(self):
        self._story_branch(
            "u/story-001-c", "other.py", "[verify-deferred] shipping under deadline"
        )
        # Nudge suppressed by the [verify-deferred] commit message.
        self.assertIsNone(self._commit_nudge("[verify-deferred] shipping"))
        # Close gate bypassed: a [verify-deferred] commit sits in history.
        _, deferred = self._preload_vars()
        self.assertEqual(deferred, "true")
        # The landed [verify-deferred] commit records a debt naming the path.
        msg = "[verify-deferred] shipping under deadline"
        bash_post_tool.run(
            _make_bash_input(
                command=f"git commit -m '{msg}'",
                stdout=f"[u/story-001-c abc1234] {msg}",
                cwd=str(self.tmpdir),
            ),
            smm_dir=self.smm_dir,
        )
        debts = events_of_type(self._read_events(), _common.DEBT)
        self.assertEqual(len(debts), 1)
        self.assertEqual(debts[0]["files"], ["acc_test.py"])

    def test_e2e_full_lifecycle(self):
        # Declare → commit-miss (nudge fires, close blocks) → touch (nudge
        # clears, close passes) on one branch.
        self._story_branch("u/story-001-e2e", "other.py", "wip")
        miss_nudge = self._assert_not_none(self._commit_nudge())
        self.assertIn("acc_test.py", miss_nudge)
        self.assertEqual(self._preload_vars(), ("acc_test.py", "false"))

        append_commit(str(self.tmpdir), "acc_test.py")
        self.assertIsNone(self._commit_nudge())
        untouched, _ = self._preload_vars()
        self.assertEqual(untouched, "")

    def test_bun_spec_untouched_fires_nudge_and_blocks_close(self):
        # story-001 (bun spec paths): a bun direct-runner acceptance command
        # names its spec file on the CLI, same as pytest — the gate must
        # name that path, not fall open to the whole-tree sentinel.
        self._seed_story(
            {"type": "bun", "command": "bun test packages/db/src/x.test.ts"}
        )
        self._story_branch("u/story-001-bun-a", "other.py", "wip")
        nudge = self._assert_not_none(self._commit_nudge())
        self.assertIn("packages/db/src/x.test.ts", nudge)
        untouched, deferred = self._preload_vars()
        self.assertEqual(untouched, "packages/db/src/x.test.ts")
        self.assertEqual(deferred, "false")

    def test_bun_spec_touch_clears_nudge_and_passes_close(self):
        self._seed_story(
            {"type": "bun", "command": "bun test packages/db/src/x.test.ts"}
        )
        (self.tmpdir / "packages" / "db" / "src").mkdir(parents=True, exist_ok=True)
        self._story_branch(
            "u/story-001-bun-b", "packages/db/src/x.test.ts", "add bun spec"
        )
        self.assertIsNone(self._commit_nudge())
        untouched, _ = self._preload_vars()
        self.assertEqual(untouched, "")

    def _stage_only(self, branch: str, filename: str) -> None:
        """Checkout a fresh story branch off main and `git add` a path with
        NO commit — base == HEAD with a populated index, the exact
        condition story-006 fixes. Deliberately NOT `_story_branch` /
        `make_commit`: those commit immediately, making base..HEAD
        non-empty and any such test green whether or not the fix exists.
        """
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        (self.tmpdir / filename).write_text("x")
        subprocess.run(
            ["git", "add", filename],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

    def test_first_commit_with_staged_acceptance_test_has_no_advisory(self):
        # AC 4: driven through the PreToolUse hook as a real subprocess
        # (unlike `_commit_nudge`'s in-process `pre_tool_bash.run` above) —
        # a green in-process test would not prove the subprocess claim.
        self._stage_only("u/story-001-first-commit", "acc_test.py")
        result = self._run_script(
            "pre_tool_bash.py",
            _make_bash_input(command="git commit -m 'wip'", cwd=str(self.tmpdir)),
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Verify-touch", result.stdout)
        self.assertNotIn("acc_test.py", result.stdout)


if __name__ == "__main__":
    unittest.main()

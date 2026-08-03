#!/usr/bin/env python3
"""Tests for scripts/verify_acceptance.py.

The CLI reads a story by ID from sprint.json, runs every command in
its `acceptance_execution` block in order, and exits non-zero on the
first failing command (naming it in stderr). Back-compat: a story
with the legacy `command: str` shape is treated as a one-element list.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import sprint_store
import verify_acceptance
from conftest import (
    _SMMTestCase,
    make_sprint_dict,
    make_story_dict,
    run_cli,
    verify_events,
)

_VERIFY_ACCEPTANCE = (
    Path(__file__).parent.parent.parent / "scripts" / "verify_acceptance.py"
)


class TestVerifyAcceptance(_SMMTestCase):
    def _save_sprint_with_story(self, ae: dict, story_id: str = "story-001") -> None:
        story = make_story_dict(id=story_id, acceptance_execution=ae)
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _verify(self, story_id: str):
        return run_cli(_VERIFY_ACCEPTANCE, ["--story", story_id], self.smm_dir)

    def test_all_green_exits_zero(self):
        self._save_sprint_with_story(
            {"type": "bash", "commands": ["true", "true", "true"]}
        )
        result = self._verify("story-001")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_red_exits_nonzero_and_names_command(self):
        self._save_sprint_with_story(
            {"type": "bash", "commands": ["true", "false", "true"]}
        )
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("false", result.stderr)

    def test_stops_at_first_failure(self):
        # The third command writes a sentinel; if the second's failure
        # didn't stop iteration, the file would exist.
        sentinel = self.smm_dir / "should-not-exist.txt"
        self._save_sprint_with_story(
            {
                "type": "bash",
                "commands": ["true", "false", f"touch {sentinel}"],
            }
        )
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(
            sentinel.exists(),
            "verify_acceptance kept running past the first failure",
        )

    def test_unknown_story_id_exits_nonzero(self):
        self._save_sprint_with_story({"type": "bash", "commands": ["true"]})
        result = self._verify("story-bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected an error message on stderr")

    def test_back_compat_single_command_string(self):
        # Story shape from before sprint-062: `command: str`.
        self._save_sprint_with_story({"type": "bash", "command": "true"})
        result = self._verify("story-001")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_back_compat_single_command_string_failure(self):
        self._save_sprint_with_story({"type": "bash", "command": "false"})
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("false", result.stderr)

    def test_multi_command_failure_names_index_and_command(self):
        self._save_sprint_with_story({"type": "bash", "commands": ["true", "false"]})
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commands[1]", result.stderr)
        self.assertIn("false", result.stderr)

    def test_single_command_failure_keeps_legacy_format(self):
        # Pinned bit-for-bit: downstream tooling greps for `command failed`.
        self._save_sprint_with_story({"type": "bash", "commands": ["false"]})
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("command failed", result.stderr)
        self.assertNotIn("commands[", result.stderr)

    def test_no_sprint_exits_nonzero(self):
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected an error message on stderr")

    def test_story_without_acceptance_execution_exits_nonzero(self):
        story = make_story_dict(id="story-001")
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())

    def test_smm_dir_visible_in_subprocess(self):
        # AC commands that reference $SMM_DIR (e.g. to read sprint state, append
        # a marker, etc.) must see it in the child env. The fix is for
        # verify_acceptance to inject it from its --smm-dir arg — relying on
        # the caller to have exported SMM_DIR is the bug (sister concern of
        # feedback_acceptance_command_path_drift).
        #
        # _SMMTestCase pins SMM_DIR in os.environ for test convenience, which
        # masks the production gap (callers like /xp-accept do NOT export it).
        # Strip it here to model the real-world parent env.
        self._save_sprint_with_story(
            {"type": "bash", "commands": ['test -n "$SMM_DIR"']}
        )
        env_no_smm = {k: v for k, v in os.environ.items() if k != "SMM_DIR"}
        with patch.dict(os.environ, env_no_smm, clear=True):
            result = self._verify("story-001")
        self.assertEqual(
            result.returncode,
            0,
            f"$SMM_DIR not propagated to AC subprocess; stderr={result.stderr!r}",
        )


class TestCmdTimeout(_SMMTestCase):
    """timeout=0 makes subprocess.run raise TimeoutExpired BEFORE the command
    runs at all, so every acceptance command would die "timed out after 0s"
    having never executed. Only a POSITIVE override is an override; zero,
    negative, and unparseable values express no runnable budget and fall
    back to the default (mirrors worktree_bootstrap._bootstrap_timeout)."""

    def _timeout(self, raw: str) -> int:
        with patch.dict(os.environ, {"VERIFY_CMD_TIMEOUT_S": raw}):
            return verify_acceptance._cmd_timeout()

    def test_positive_override_is_honoured(self):
        self.assertEqual(self._timeout("42"), 42)

    def test_default_bound_is_two_hours(self):
        # The bound guarantees "never hangs forever" — it is NOT a fail-fast
        # budget. One constant now serves BOTH the attended --story path and
        # the unattended --sprint batch, and a real acceptance suite can
        # legitimately run for an hour, so a tight default would convert a
        # slow-but-passing suite into a red. Per-project tuning stays on
        # VERIFY_CMD_TIMEOUT_S.
        with patch.dict(os.environ):
            os.environ.pop("VERIFY_CMD_TIMEOUT_S", None)
            self.assertEqual(verify_acceptance._cmd_timeout(), 7200)

    def test_zero_falls_back_to_the_default(self):
        self.assertEqual(self._timeout("0"), verify_acceptance._DEFAULT_CMD_TIMEOUT_S)

    def test_negative_falls_back_to_the_default(self):
        self.assertEqual(self._timeout("-5"), verify_acceptance._DEFAULT_CMD_TIMEOUT_S)

    def test_unparseable_falls_back_to_the_default(self):
        self.assertEqual(
            self._timeout("not-a-number"), verify_acceptance._DEFAULT_CMD_TIMEOUT_S
        )


class TestManualTypeStoryPath(_SMMTestCase):
    """verify_acceptance gates on command PRESENCE, not on type==manual. A
    manual block with only prose `steps` (no command) is N/A — its prose is
    never shelled. A manual block that DOES carry a runnable command runs it,
    and its exit code decides pass/fail (fixes the N/A-green honesty bug).

    Seeded by writing sprint.json directly: AUTHORING no longer accepts a
    command on a manual block, so a manual+command block can only exist as
    one already stored (grandfathered). Run-time is what these pin, and it is
    unchanged — routing still keys on command presence."""

    def _save(self, ae: dict) -> None:
        story = make_story_dict(id="story-001", acceptance_execution=ae)
        sprint = make_sprint_dict(stories=[story])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _verify(self, story_id: str):
        return run_cli(_VERIFY_ACCEPTANCE, ["--story", story_id], self.smm_dir)

    def test_manual_steps_only_is_na_and_never_shelled(self):
        self._save({"type": "manual", "steps": ["go read the logs and confirm X"]})
        # Call _run_story in-process (not via run_cli's subprocess) so the
        # patched subprocess.run is actually observed.
        with patch.object(verify_acceptance.subprocess, "run") as mock_run:
            rc = verify_acceptance._run_story(self.smm_dir, "story-001")
        self.assertEqual(rc, verify_acceptance._EXIT_OK)
        mock_run.assert_not_called()

    def test_manual_with_command_runs_and_passes(self):
        self._save({"type": "manual", "command": "true"})
        result = self._verify("story-001")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manual_with_command_runs_and_exit_decides_failure(self):
        # The concern: a manual story carrying a real command used to report
        # green unrun. Now the command runs and its non-zero exit fails.
        self._save({"type": "manual", "command": "false"})
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("false", result.stderr)


class TestManualTypeSprintMatrix(_SMMTestCase):
    """--sprint gates on command PRESENCE. A manual block with only prose
    `steps` is an N/A row (never shelled, never reddens the sprint); a manual
    block carrying a runnable command is executed like any other.

    Written straight to disk for the same reason as TestManualTypeStoryPath:
    a manual+command block is only reachable as an already-stored one."""

    def _seed(self, stories: list[dict]) -> None:
        sprint = make_sprint_dict(sprint_id="sprint-012", stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_manual_steps_only_is_na_and_sprint_stays_green(self):
        manual_story = make_story_dict(
            id="story-manual",
            acceptance_execution={
                "type": "manual",
                "steps": ["go read the logs and confirm X"],
            },
        )
        passing_story = make_story_dict(
            id="story-passing",
            acceptance_execution={"type": "bash", "commands": ["true"]},
        )
        self._seed([manual_story, passing_story])

        result = run_cli(_VERIFY_ACCEPTANCE, ["--sprint"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("N/A", result.stdout)
        self.assertNotIn(
            "go read the logs and confirm X",
            result.stdout,
            "manual prose must never be shelled out",
        )

        events = verify_events(self._read_events())
        self.assertEqual(len(events), 1, events)
        meta = events[0]["metadata"]
        self.assertEqual(meta["verify_status"], "green")
        failing_stories = [f["story"] for f in meta["failing"]]
        self.assertNotIn("story-manual", failing_stories)

    def test_manual_with_command_runs_in_sprint_and_can_redden(self):
        # The honesty fix: a manual block carrying a real command is run in the
        # --sprint matrix (not N/A-green), so a failing one reddens the sprint.
        manual_cmd_story = make_story_dict(
            id="story-manual-cmd",
            acceptance_execution={"type": "manual", "command": "false"},
        )
        self._seed([manual_cmd_story])

        result = run_cli(_VERIFY_ACCEPTANCE, ["--sprint"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[FAIL]", result.stdout)

        events = verify_events(self._read_events())
        self.assertEqual(len(events), 1, events)
        meta = events[0]["metadata"]
        self.assertEqual(meta["verify_status"], "red")
        failing_stories = [f["story"] for f in meta["failing"]]
        self.assertIn("story-manual-cmd", failing_stories)


if __name__ == "__main__":
    unittest.main()

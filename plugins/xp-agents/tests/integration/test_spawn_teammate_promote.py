#!/usr/bin/env python3
"""End-to-end TOCTOU test for spawn_teammate.py post-promote.

Drives spawn_teammate.main() against a real SMM dir + sprint.json (no
mocks on sprint_store) with stubbed worktree+claude. Proves the get→
update_story_status pair was replaced with an atomic CAS that refuses
to demote a story already advanced past in-progress.

Lives alongside the other e2e teammate tests (test_assign_team.py,
test_story_close.py) — these tests need real file I/O against the
sprint store, not the unit-level mocks of test_spawn_teammate.py.
"""

import json
import os
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _IntegrationTestCase,
    make_sprint_dict,
    make_story_dict,
)


def _run_with_tee_mock(*, raise_error: bool = False):
    """Stub run_with_tee so we don't actually launch claude in tests."""

    def side_effect(cmd, **kwargs):
        if raise_error:
            raise subprocess.CalledProcessError(1, cmd)

    return side_effect


class TestSpawnTeammatePromoteE2E(_IntegrationTestCase):
    """End-to-end: spawn_teammate.main() against real sprint.json.

    No mocks on sprint_store. Verifies the CAS replaces the legacy
    get→update pair so a story already advanced past in-progress is
    not silently demoted back to reviewing.
    """

    def _seed_sprint(self, status: str) -> None:
        """Write a one-story sprint with the given status."""
        sprint = make_sprint_dict(stories=[make_story_dict(status=status)])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _read_status(self) -> str:
        return json.loads((self.smm_dir / "sprint.json").read_text())["stories"][0][
            "status"
        ]

    def _spawn(
        self, *, name: str = "worktree-story-001", raise_error: bool = False
    ) -> None:
        """Drive spawn_teammate.main with stubbed worktree+claude."""
        import spawn_teammate

        prompt_file = Path(self.tmpdir) / f"{name}.prompt.txt"
        prompt_file.write_text("body")

        with (
            unittest.mock.patch.object(
                spawn_teammate,
                "create_worktree",
                return_value=str(self.tmpdir),
            ),
            unittest.mock.patch.object(
                spawn_teammate,
                "run_with_tee",
                side_effect=_run_with_tee_mock(raise_error=raise_error),
            ),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    name,
                    "--smm-dir",
                    str(self.smm_dir),
                    "--prompt-file",
                    str(prompt_file),
                    "--story-id",
                    "story-001",
                ]
            )

    def test_in_progress_promotes_to_reviewing(self):
        """The happy path: in-progress at start, reviewing on rc=0."""
        self._seed_sprint("in-progress")
        self._spawn()
        self.assertEqual(self._read_status(), "reviewing")

    def test_done_status_not_silently_demoted(self):
        """Pins concern 3ba0b6237c65 end-to-end. If something advanced the
        story to done before spawn_teammate's promote phase ran, the CAS
        must refuse to overwrite — status stays done. Demonstrates the
        TOCTOU window is closed: with the legacy get_story+update pair,
        the get returned (a stale) in-progress and the update silently
        wrote reviewing, dropping the done state. The CAS performs the
        check inside the same locked critical section, so the actual
        status at write time is the only state that matters."""
        self._seed_sprint("done")
        self._spawn()
        self.assertEqual(
            self._read_status(),
            "done",
            "story already advanced to done was demoted by CAS — "
            "expected guard at write-time, got silent overwrite",
        )

    def test_deferred_status_not_silently_demoted(self):
        """Symmetric to the done case — deferred is also a terminal state
        that must not be overwritten by a stale promote."""
        self._seed_sprint("deferred")
        self._spawn()
        self.assertEqual(self._read_status(), "deferred")

    def test_failed_teammate_leaves_in_progress(self):
        """rc!=0 raises before the CAS runs; status stays in-progress."""
        self._seed_sprint("in-progress")
        with self.assertRaises(subprocess.CalledProcessError):
            self._spawn(raise_error=True)
        self.assertEqual(self._read_status(), "in-progress")

    def test_post_promote_does_not_use_legacy_get_update_pair(self):
        """spawn_teammate's post-promote must use the atomic CAS
        update_story_status_if, NOT the legacy get_story + unlocked
        update_story_status pair that has the cross-process TOCTOU
        window the story-002 fix targets.

        Patches both legacy entry points to raise — only the CAS
        survives. With this guard in place, a regression that reverts
        spawn_teammate.py back to the legacy pair trips immediately,
        reintroducing the bug visibly instead of silently."""
        import sprint_store

        self._seed_sprint("in-progress")
        with (
            unittest.mock.patch.object(
                sprint_store,
                "get_story",
                side_effect=AssertionError(
                    "legacy get_story called — CAS bypass is the regression"
                ),
            ),
            unittest.mock.patch.object(
                sprint_store,
                "update_story_status",
                side_effect=AssertionError(
                    "legacy update_story_status called — must be CAS"
                ),
            ),
        ):
            self._spawn()
        self.assertEqual(self._read_status(), "reviewing")


class TestSpawnTeammateInPlace(_IntegrationTestCase):
    """story-008: --in-place runs the teammate in the MAIN checkout (solo
    delegation) instead of a worktree — skip create_worktree, run in the
    process cwd, omit the worktree preamble, and DON'T promote to reviewing
    (the story stays in-progress/solo so /xp-accept's solo path handles it)."""

    def _seed_sprint(self, status: str = "in-progress") -> None:
        sprint = make_sprint_dict(stories=[make_story_dict(status=status)])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _read_status(self) -> str:
        return json.loads((self.smm_dir / "sprint.json").read_text())["stories"][0][
            "status"
        ]

    def _spawn_in_place(self, capture: dict) -> None:
        """Drive spawn_teammate.main --in-place; create_worktree must NOT be
        called, and run_with_tee's cwd + stdin are captured."""
        import spawn_teammate

        prompt_file = Path(self.tmpdir) / "p.prompt.txt"
        prompt_file.write_text("BODY-MARKER")

        def tee_capture(cmd, **kwargs):
            capture["cwd"] = kwargs.get("cwd")
            stdin = kwargs.get("stdin")
            if stdin is not None:
                capture["stdin"] = Path(stdin.name).read_text()

        with (
            unittest.mock.patch.object(
                spawn_teammate,
                "create_worktree",
                side_effect=AssertionError("create_worktree called in --in-place mode"),
            ),
            unittest.mock.patch.object(
                spawn_teammate, "run_with_tee", side_effect=tee_capture
            ),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    "worktree-story-001",
                    "--smm-dir",
                    str(self.smm_dir),
                    "--prompt-file",
                    str(prompt_file),
                    "--story-id",
                    "story-001",
                    "--in-place",
                ]
            )

    def test_in_place_skips_worktree_and_runs_in_main_checkout(self):
        self._seed_sprint("in-progress")
        cap: dict = {}
        self._spawn_in_place(cap)
        self.assertEqual(cap["cwd"], os.getcwd())
        self.assertNotIn(".claude/worktrees", cap["cwd"])

    def test_in_place_omits_worktree_preamble(self):
        self._seed_sprint("in-progress")
        cap: dict = {}
        self._spawn_in_place(cap)
        self.assertNotIn("Worktree Context", cap["stdin"])
        self.assertIn("BODY-MARKER", cap["stdin"])

    def test_in_place_does_not_promote_to_reviewing(self):
        """In-place stays in-progress/solo — no self-promote (no worktree for
        /xp-accept's reviewing path to detach onto)."""
        self._seed_sprint("in-progress")
        cap: dict = {}
        self._spawn_in_place(cap)
        self.assertEqual(self._read_status(), "in-progress")

    def test_in_place_writes_story_assignment_for_attribution(self):
        """In-place still writes the name-keyed .story-assignment so commit
        attribution stays EXPLICIT (Tier 1 via XP_TEAMMATE_NAME) rather than
        relying on the single-in-progress heuristic."""
        import worktree

        self._seed_sprint("in-progress")
        cap: dict = {}
        self._spawn_in_place(cap)
        assignment = worktree.story_assignment_path(self.smm_dir, "worktree-story-001")
        self.assertTrue(assignment.exists())
        self.assertEqual(assignment.read_text().strip(), "story-001")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for sprint_cli.py force-unmerged / merge-backstop subcommands.

Covers update-story's --force-unmerged escape hatch, the engine-altitude
merge backstop (TestMergeBackstop), and update-story-if's own
--force-unmerged path. Split out of test_sprint_cli_mutate.py to keep
each test file under the 500-line cap (decision d027fe5c9066) — the
add-story/edit-story/update-story-branch structural coverage stays in
test_sprint_cli_mutate.py, and update-story-if's CAS + the run()-vs-save()
routing contract live in test_sprint_cli_mutate_status.py. The CLI is
invoked as a subprocess via run_cli(_CLI, ...), so these subcommands
still route through sprint_cli.py (which imports the handlers from
sprint_cli_mutate.py) — no import repoint needed.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import append_commit, init_repo
from conftest import (
    _SMMTestCase,
    run_cli,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)

_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"


class TestForceUnmerged(_SMMTestCase):
    """The mark-done merge gate's escape hatch.

    A gate with no recovery path is the trap this project keeps re-learning, so
    the bypass exists. But it is never SILENT: the CLI -- deterministic code, not
    LLM prose -- records a debt event, and refuses an empty reason.
    """

    def _status(self) -> str:
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        return loaded["stories"][0]["status"]

    def _debts(self) -> list[dict]:
        path = self.smm_dir / "events.jsonl"
        if not path.exists():
            return []
        events = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        return [e for e in events if e["type"] == "debt"]

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))

    def test_force_unmerged_marks_done_and_records_a_debt(self):
        """The bypass works, and it leaves a trace. The debt is the PRICE of the
        override -- it is what turns 'I skipped the gate' from a private decision
        into something the retro can see."""
        result = run_cli(
            _CLI,
            ["update-story", "story-001", "done", "--force-unmerged", "merged by hand"],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "done")
        debts = self._debts()
        self.assertEqual(len(debts), 1)
        self.assertIn("story-001", debts[0]["content"])
        self.assertIn("merged by hand", debts[0]["content"])

    def test_empty_reason_is_refused_and_nothing_moves(self):
        """`--force-unmerged ""` would be a SILENT bypass wearing the costume of
        an accountable one. Refuse it, and leave the story where it was."""
        result = run_cli(
            _CLI,
            ["update-story", "story-001", "done", "--force-unmerged", "   "],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 1)
        self.assertNotEqual(self._status(), "done")
        self.assertEqual(self._debts(), [])

    def test_force_unmerged_only_applies_to_done(self):
        """The gate only fires on `done`, so the override is meaningless anywhere
        else. Accepting it there would mint debt events for nothing."""
        result = run_cli(
            _CLI,
            ["update-story", "story-001", "deferred", "--force-unmerged", "why"],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(self._debts(), [])

    def test_plain_mark_done_records_no_debt(self):
        """The ordinary path stays clean -- no debt, no noise."""
        result = run_cli(_CLI, ["update-story", "story-001", "done"], self.smm_dir)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "done")
        self.assertEqual(self._debts(), [])


class TestMergeBackstop(_SMMTestCase):
    """The engine-altitude merge backstop.

    The Bash-regex gate refuses `update-story <id> done` on an unmerged branch,
    but an id hidden in a shell variable (`update-story "$SID" done`) evades every
    regex — the shell resolves the var, so the real id reaches the engine handler
    where no gate stood. This pins the SAME git-derived proof below the shell, in
    the handlers where every writer of `status` converges.

    rc contract mirrors each handler's existing codes: update-story blocks with
    rc=1, update-story-if with rc=2 (its "cannot proceed / bad input" code,
    distinct from the rc=1 CAS race-loss).
    """

    _STORY_BRANCH = "paulingalls/story-001-thing"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        init_repo(self.repo)

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, capture_output=True, check=True)

    def _seed_unmerged(self, status: str = "closing") -> None:
        """A story whose recorded branch holds a commit its base does not."""
        self._git("checkout", "-b", self._STORY_BRANCH)
        append_commit(self.repo, "story.txt")
        self._git("checkout", "main")
        story = _make_story(
            id="story-001", status=status, branch_name=self._STORY_BRANCH
        )
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[story]))
        )

    def _status(self) -> str:
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        return loaded["stories"][0]["status"]

    def test_update_story_done_refused_and_sprint_untouched(self):
        """E2E: an unmerged branch, driven through the engine handler, exits
        non-zero with a merge-not-verified message and leaves sprint.json byte-
        identical."""
        self._seed_unmerged()
        before = (self.smm_dir / "sprint.json").read_bytes()

        result = run_cli(
            _CLI,
            ["update-story", "story-001", "done", "--cwd", self.repo],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("story-001", result.stderr)
        self.assertIn("not merged", result.stderr.lower())
        self.assertEqual(
            (self.smm_dir / "sprint.json").read_bytes(),
            before,
            "a refused mark-done must not write",
        )

    def test_update_story_if_new_done_refused_rc2(self):
        """The OTHER writer of `done` — the compare-and-swap — is gated too, and
        blocks with rc=2 (bad input), not the rc=1 that means the CAS lost its
        race."""
        self._seed_unmerged(status="closing")

        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "closing",
                "--new",
                "done",
                "--cwd",
                self.repo,
            ],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("not merged", result.stderr.lower())
        self.assertEqual(self._status(), "closing", "the CAS must not have written")


class TestUpdateStoryIfForceUnmerged(_SMMTestCase):
    """The recovery hatch on the OTHER writer of `done` -- the CAS used by
    /xp-accept Step 1.5. Same accountable-override contract as update-story's
    --force-unmerged (TestForceUnmerged above), routed through the shared
    _merge_gate helper -- but bad input here exits rc=2, not rc=1, and a lost
    CAS race (status != --expected) must stay rc=1 and untouched by the force
    flag entirely."""

    _STORY_BRANCH = "paulingalls/story-001-thing"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        init_repo(self.repo)

    def _seed_unmerged(self, status: str = "closing") -> None:
        self._git("checkout", "-b", self._STORY_BRANCH)
        append_commit(self.repo, "story.txt")
        self._git("checkout", "main")
        story = _make_story(
            id="story-001", status=status, branch_name=self._STORY_BRANCH
        )
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[story]))
        )

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, capture_output=True, check=True)

    def _status(self) -> str:
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        return loaded["stories"][0]["status"]

    def _debts(self) -> list[dict]:
        path = self.smm_dir / "events.jsonl"
        if not path.exists():
            return []
        events = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        return [e for e in events if e["type"] == "debt"]

    def test_forced_cas_to_done_succeeds_and_records_a_debt(self):
        self._seed_unmerged(status="closing")

        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "closing",
                "--new",
                "done",
                "--force-unmerged",
                "merged by hand",
                "--cwd",
                self.repo,
            ],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "done")
        debts = self._debts()
        self.assertEqual(len(debts), 1)
        self.assertIn("story-001", debts[0]["content"])
        self.assertIn("merged by hand", debts[0]["content"])

    def test_empty_reason_is_refused_rc2_and_nothing_moves(self):
        self._seed_unmerged(status="closing")

        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "closing",
                "--new",
                "done",
                "--force-unmerged",
                "   ",
                "--cwd",
                self.repo,
            ],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self._status(), "closing")
        self.assertEqual(self._debts(), [])

    def test_force_unmerged_only_applies_to_done_rc2(self):
        self._seed_unmerged(status="reviewing")

        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "reviewing",
                "--new",
                "closing",
                "--force-unmerged",
                "why",
                "--cwd",
                self.repo,
            ],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self._status(), "reviewing")
        self.assertEqual(self._debts(), [])

    def test_unrecorded_bypass_refuses_rc2_and_cas_never_runs(self):
        """The debt record is the price of the bypass, taken BEFORE the CAS
        write. Make _record_forced_unmerged's write fail -- events.jsonl made
        read-only, directory itself left writable so a failure there can only
        be the append, not some other file the CAS also needs -- and the
        status must stay exactly where it started -- no unrecorded bypass, no
        CAS started on its behalf."""
        self._seed_unmerged(status="closing")
        events_path = self.smm_dir / "events.jsonl"
        events_path.chmod(0o400)
        try:
            result = run_cli(
                _CLI,
                [
                    "update-story-if",
                    "story-001",
                    "--expected",
                    "closing",
                    "--new",
                    "done",
                    "--force-unmerged",
                    "merged by hand",
                    "--cwd",
                    self.repo,
                ],
                self.smm_dir,
            )
        finally:
            events_path.chmod(0o600)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self._status(), "closing")

    def test_lost_cas_race_stays_rc1_even_with_force_flag(self):
        """Force only bypasses the merge backstop, never the CAS semantics --
        a stale --expected must still lose the race at rc=1."""
        self._seed_unmerged(status="done")

        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "closing",
                "--new",
                "done",
                "--force-unmerged",
                "merged by hand",
                "--cwd",
                self.repo,
            ],
            self.smm_dir,
        )

        self.assertEqual(result.returncode, 1, result.stderr)


if __name__ == "__main__":
    unittest.main()

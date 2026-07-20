#!/usr/bin/env python3
"""Tests for sprint_cli.py status-transition subcommands.

Covers update-story-if (the compare-and-swap CLI exposure used by
xp-accept Step 1.5) and the run()-vs-save() routing contract (which spans
create and add-story too, so it stays here). Split out of
test_sprint_cli_mutate.py to keep each test file under the 500-line cap
(decision d027fe5c9066) — the add-story/edit-story/update-story-branch
structural coverage stays in test_sprint_cli_mutate.py, and the
force-unmerged / merge-backstop coverage lives in
test_sprint_cli_mutate_force_unmerged.py. The CLI is invoked as a
subprocess via run_cli(_CLI, ...), so these subcommands still route
through sprint_cli.py (which imports the handlers from
sprint_cli_mutate.py) — no import repoint needed.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

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


class TestUpdateStoryIfCommand(_SMMTestCase):
    """CLI exposure of the CAS helper. Production xp-accept Step 1.5
    uses this to guard the singleton reviewing→closing transition."""

    def _seed(self, status: str) -> None:
        sprint = _make_sprint(stories=[_make_story(id="story-001", status=status)])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_succeeds_when_status_matches_expected(self):
        self._seed("reviewing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "reviewing",
                "--new",
                "closing",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "closing")

    def test_cas_mismatch_exits_rc1(self):
        # A prior caller already advanced the story past `reviewing`;
        # the CAS subcommand must report failure (no demotion). Pins
        # rc=1 specifically — the xp-accept skill instructs the
        # orchestrator to skip-this-story on rc=1 vs halt on rc=2,
        # so the 1↔2 distinction is contract, not implementation detail.
        self._seed("closing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "reviewing",
                "--new",
                "closing",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "closing")

    def test_invalid_new_status_exits_rc2(self):
        # Validation error (argparse choices=) — distinct from the
        # benign rc=1 race-loss; orchestrator must halt, not skip.
        self._seed("reviewing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-001",
                "--expected",
                "reviewing",
                "--new",
                "bogus",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)

    def test_unknown_story_id_exits_rc2(self):
        # Helper's ValueError → rc=2. Same orchestrator semantics as
        # the bogus-status case: halt, surface stderr, do not skip.
        self._seed("reviewing")
        result = run_cli(
            _CLI,
            [
                "update-story-if",
                "story-999",
                "--expected",
                "reviewing",
                "--new",
                "closing",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)


class TestStructuralSubcommandsRouteThroughRun(_SMMTestCase):
    """Story-004: _cmd_create + _cmd_add_story route through sprint_save.run()
    (structural mutations — full pipeline). _cmd_edit_story routes through
    sprint_save.save() (status flips — side-effect-free). Lock-in tests.

    Observable side-effect of run() used here: the soft-warn marker for
    sister-test layout (Q1(b)) — touched only by run(), never by save().
    """

    _MARKER = ".sister-test-layout-warn"

    def _sample_sprint(self):
        return _make_sprint(stories=[_make_story(id="story-001", status="ready")])

    def test_create_fires_run_pipeline(self):
        sprint = self._sample_sprint()
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(sprint))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.smm_dir / self._MARKER).exists(),
            "expected sister-test soft-warn marker after _cmd_create — proves "
            "_cmd_create routes through sprint_save.run()",
        )

    def test_add_story_fires_run_pipeline(self):
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # Disjoint from the on-disk story's default src/auth.py claim.
        new_story = _make_story(
            id="story-099", status="ready", file_domain=["src/other.py — new module"]
        )
        result = run_cli(_CLI, ["add-story"], self.smm_dir, json.dumps(new_story))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.smm_dir / self._MARKER).exists(),
            "expected sister-test soft-warn marker after _cmd_add_story",
        )

    def test_add_story_dup_id_stays_above_run(self):
        """story-003's locked contract: dup-id guard runs BEFORE sprint_save.run.
        A duplicate-id payload must NOT fire run()'s side effects (no marker,
        no transition concerns)."""
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        dup = _make_story(id="story-001", status="ready", title="dup")
        result = run_cli(_CLI, ["add-story"], self.smm_dir, json.dumps(dup))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate story id", result.stderr)
        self.assertFalse(
            (self.smm_dir / self._MARKER).exists(),
            "dup-id rejection MUST short-circuit before sprint_save.run — "
            "marker should NOT exist (locks story-003 contract)",
        )

    def test_edit_story_uses_save_not_run(self):
        """Metadata edits via edit-story must NOT trigger sister discovery or
        soft-warn (impact-zone constraint per plan-review e7b72bd57c84)."""
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"execution_mode": "solo"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            (self.smm_dir / self._MARKER).exists(),
            "edit-story MUST route through save() not run() — sister-test "
            "soft-warn marker should NOT exist (locks the architectural split)",
        )
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["execution_mode"], "solo")

    def test_edit_story_refuses_to_write_status(self):
        """The FORGE. The mark-done merge gate stands at `update-story <id> done`;
        `edit-story` reached the same field with a raw JSON patch and never met it —
        so `{"status":"done"}` recorded a ship whose merge nobody ever proved.

        Same hole plan_cli.edit-milestone closed for `status`/`delivered_sprint`, and
        the same answer: a status TRANSITION has a state machine (update-story /
        update-story-if) that owns its rules; a patch path that writes the field
        walks around that machine. So the patch path does not write it at all."""
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"status": "done"}),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("update-story", result.stderr, "name the path that IS gated")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertNotEqual(loaded["stories"][0]["status"], "done", "no forged done")

    def test_edit_story_still_accepts_the_fields_it_owns(self):
        """The control: refusing `status` must not refuse the edits skills rely on."""
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"execution_mode": "teammate", "executor_model": "haiku"}),
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

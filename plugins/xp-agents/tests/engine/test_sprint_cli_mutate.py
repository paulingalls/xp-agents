#!/usr/bin/env python3
"""Tests for sprint_cli.py structural-mutation subcommands.

Covers add-story, update-story, update-story-if, edit-story,
update-story-branch, and the run()-vs-save() routing contract (which spans
create too, so it stays here). Split out of test_sprint_cli.py in
sprint-108 M1, again in story-005 — `create` and the re-slice preserve now
live in test_sprint_cli_create.py — and again in story-015 —
build-capstone now lives in test_sprint_cli_build_capstone.py — to keep
each test file under the 500-line cap (decision d027fe5c9066). The CLI is
invoked as a subprocess via run_cli(_CLI, ...), so these subcommands
still route through sprint_cli.py (which imports the handlers from
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


class TestAddStoryCommand(_SMMTestCase):
    def test_add_story(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        # Disjoint domain: _make_story defaults to src/auth.py, which the
        # on-disk story-001 already claims. Two independent stories claiming
        # one path is a real file_domain collision and the write refuses it.
        new_story = _make_story(
            id="story-002", title="Login", file_domain=["src/login.py — new module"]
        )
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(new_story),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(len(loaded["stories"]), 2)

    def test_corrupt_sprint_fails_cleanly_not_with_a_traceback(self):
        """add-story genuinely CANNOT proceed on a sprint it can't read — it
        appends to the recorded story list. But it must say so the way every
        other handler does (message + rc 1), not dump a stack: the actionable
        next step is `create`, the repair path, and a traceback buries it."""
        corrupt = '{"sprint_id": "sprint-001",'
        (self.smm_dir / "sprint.json").write_text(corrupt)
        result = run_cli(
            _CLI, ["add-story"], self.smm_dir, json.dumps(_make_story(id="story-002"))
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("could not be read", result.stderr)
        self.assertEqual(
            (self.smm_dir / "sprint.json").read_text(),
            corrupt,
            "a refused add-story must not write",
        )


class TestAddStoryDupId(_SMMTestCase):
    """add-story rejects payloads whose id collides with an existing
    story (story-003). Non-dict / id-less payloads fall through to the
    existing schema validator so their error messages stay stable."""

    def test_dup_id_rejects_nonzero(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        sprint_path = self.smm_dir / "sprint.json"
        sprint_path.write_text(json.dumps(sprint))
        before = sprint_path.read_bytes()
        dup_payload = _make_story(id="story-001", title="Collision")
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(dup_payload),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate story id", result.stderr)
        self.assertIn("story-001", result.stderr)
        self.assertEqual(sprint_path.read_bytes(), before)

    def test_new_id_succeeds(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(
                _make_story(
                    id="story-099", title="Fresh", file_domain=["src/fresh.py — new"]
                )
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        ids = [s["id"] for s in loaded["stories"]]
        self.assertIn("story-099", ids)

    def test_dup_check_preserves_jsondecodeerror_path(self):
        # Pre-check must not swallow the existing parse-error branch.
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["add-story"], self.smm_dir, "{not json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid JSON", result.stderr)
        self.assertNotIn("Duplicate story id", result.stderr)

    def test_missing_id_falls_through_to_validator(self):
        # An id-less dict isn't a dup candidate; the schema validator
        # owns the rejection so its message stays the source of truth.
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps({"title": "no-id"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation error", result.stderr)
        self.assertNotIn("Duplicate story id", result.stderr)

    def test_non_dict_payload_falls_through_to_validator(self):
        # Same contract for non-dict JSON shapes (list, string, ...).
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["add-story"], self.smm_dir, "[]")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation error", result.stderr)
        self.assertNotIn("Duplicate story id", result.stderr)


class TestUpdateStoryCommand(_SMMTestCase):
    def test_update_status(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story", "story-001", "in-progress"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")

    def test_invalid_story_id(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["update-story", "story-999", "done"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


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


class TestEditStoryCommand(_SMMTestCase):
    """edit-story updates arbitrary story fields via stdin JSON."""

    def test_updates_context_field(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "Updated context."}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["context"], "Updated context.")

    def test_unknown_story_id_fails(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-999"],
            self.smm_dir,
            json.dumps({"context": "new"}),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_validates_schema(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "x" * 601}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("budget", result.stderr.lower())

    def test_no_sprint_fails(self):
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "new"}),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_id_override(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"id": "story-999"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("immutable", result.stderr.lower())

    def test_rejects_non_object_input(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps(["not", "a", "dict"]),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_scalar_file_domain_is_clean_error_not_traceback(self):
        # A non-list (scalar/bool) file_domain must fail cleanly through the
        # collision gate: collision_report defers shape to the schema validator,
        # so edit-story returns rc 1 with a caught error message — never an
        # uncaught TypeError traceback from iterating a non-list domain.
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        for bad in (42, True):
            result = run_cli(
                _CLI,
                ["edit-story", "story-001"],
                self.smm_dir,
                json.dumps({"file_domain": bad}),
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("Error:", result.stderr)


class TestUpdateStoryBranch(_SMMTestCase):
    def test_sets_branch_name(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-001", "paul/story-001-foo"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["branch_name"], "paul/story-001-foo")

    def test_invalid_story_fails(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-999", "paul/story-999-foo"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", result.stderr.lower())

    def test_no_sprint_fails(self):
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-001", "paul/story-001-foo"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)


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
        """Status flips via edit-story must NOT trigger sister discovery or
        soft-warn (impact-zone constraint per plan-review e7b72bd57c84)."""
        sprint = self._sample_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"status": "in-progress"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            (self.smm_dir / self._MARKER).exists(),
            "edit-story MUST route through save() not run() — sister-test "
            "soft-warn marker should NOT exist (locks the architectural split)",
        )
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")


if __name__ == "__main__":
    unittest.main()

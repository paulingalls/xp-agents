#!/usr/bin/env python3
"""Tests for sprint_cli.py structural-mutation subcommands.

Covers create, add-story, update-story, update-story-if, edit-story,
build-capstone, update-story-branch, and the run()-vs-save() routing
contract. Split out of test_sprint_cli.py in sprint-108 M1 to keep each
test file under the 500-line cap (decision d027fe5c9066). The CLI is
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


class TestCreateCommand(_SMMTestCase):
    def test_create(self):
        sprint = _make_sprint(goal="New Sprint")
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(sprint))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "sprint.json").exists())

    def test_create_invalid(self):
        result = run_cli(_CLI, ["create"], self.smm_dir, '{"bad": "data"}')
        self.assertNotEqual(result.returncode, 0)


class TestAddStoryCommand(_SMMTestCase):
    def test_add_story(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        new_story = _make_story(id="story-002", title="Login")
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(new_story),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(len(loaded["stories"]), 2)


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
            json.dumps(_make_story(id="story-099", title="Fresh")),
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


class TestSetExecutorCommand(_SMMTestCase):
    """set-executor writes a field only when its flag is PROVIDED (value-or-null:
    a provided-empty flag persists null). An OMITTED flag leaves the field
    untouched — so branch 6 can clear the executor_effort latch (debt
    c93c9745f5ed) via `--effort ""` while preserving an executor_model that
    /xp-schedule deliberately pre-seeded."""

    def _seed(self, **fields):
        sprint = _make_sprint()
        sprint["stories"][0].update(fields)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _story(self):
        return json.loads((self.smm_dir / "sprint.json").read_text())["stories"][0]

    def test_effort_only_clears_effort_and_preserves_preseeded_model(self):
        """Branch 6: `--effort ""` clears the effort latch; an OMITTED --model
        leaves a /xp-schedule pre-seeded executor_model intact."""
        self._seed(executor_model="haiku", executor_effort="high")
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--effort", ""], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._story()["executor_model"], "haiku")
        self.assertIsNone(self._story()["executor_effort"])

    def test_both_flags_write_value_or_null(self):
        """Branches 4/5: a decided tier plus effort are both persisted; a
        provided-empty --effort clears a stale effort (branch-5 reject)."""
        self._seed(executor_model="opus", executor_effort="high")
        result = run_cli(
            _CLI,
            ["set-executor", "story-001", "--model", "sonnet", "--effort", ""],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._story()["executor_model"], "sonnet")
        self.assertIsNone(self._story()["executor_effort"])

    def test_omitted_effort_leaves_effort_untouched(self):
        """An omitted --effort does not touch the field (only provided flags write)."""
        self._seed(executor_effort="high")
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--model", "opus"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._story()["executor_model"], "opus")
        self.assertEqual(self._story()["executor_effort"], "high")

    def test_provided_empty_model_clears_model(self):
        """A provided-empty --model explicitly clears the field to null."""
        self._seed(executor_model="opus")
        result = run_cli(
            _CLI, ["set-executor", "story-001", "--model", ""], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self._story()["executor_model"])


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


class TestBuildCapstoneCommand(_SMMTestCase):
    def _run(self, extra):
        return run_cli(_CLI, ["build-capstone", *extra], self.smm_dir)

    def test_prints_ready_capstone_json(self):
        result = self._run(
            [
                "--milestone",
                "Milestone 3: surface-coverage",
                "--surfaces",
                "cli,sdk",
                "--depends-on",
                "story-001,story-002",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["id"], "story-006")
        self.assertEqual(story["status"], "ready")
        self.assertTrue(story["title"].startswith("Capstone:"))
        self.assertEqual(story["dependencies"], ["story-001", "story-002"])
        surfaces = {
            a["surface"] for a in story["acceptance_criteria"] if isinstance(a, dict)
        }
        self.assertEqual(surfaces, {"cli", "sdk"})

    def test_output_pipes_into_add_story(self):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[_make_story(id="story-001")]))
        )
        built = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--depends-on",
                "story-001",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(built.returncode, 0, built.stderr)
        added = run_cli(_CLI, ["add-story"], self.smm_dir, stdin_data=built.stdout)
        self.assertEqual(added.returncode, 0, added.stderr)


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
        new_story = _make_story(id="story-099", status="ready")
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

#!/usr/bin/env python3
"""Tests for sprint_store.py — load/save and mutations.

Covers: load/save, update_story_status, set_branch, set_story_branch.
Render (render_markdown, render_story_sections) lives in
test_sprint_render.py — moved with the sprint_render extraction.
Status checks (has_active_*, is_complete, scheduled_*), compute_velocity,
compute_blockers, and count_by_status live in test_sprint_status.py
(split for the 500-line cap). Schema validation tests live in
test_sprint_schema.py. transitive_active_dependents tests live in
test_sprint_store_dependents.py (split for the 500-line cap).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)

# ===========================================================================
# Store load/save tests
# ===========================================================================


class TestLoadSprint(_SMMTestCase):
    def test_load_valid(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        loaded = sprint_store.load_sprint(self.smm_dir)
        assert loaded is not None
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_load_missing_returns_none(self):
        import sprint_store

        self.assertIsNone(sprint_store.load_sprint(self.smm_dir))

    def test_load_symlink_raises(self):
        import sprint_store

        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(_make_sprint()))
        (self.smm_dir / "sprint.json").symlink_to(real)
        with self.assertRaises(OSError):
            sprint_store.load_sprint(self.smm_dir)

    def test_load_corrupt_json_raises_corrupt_error(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text("{bad json")
        with self.assertRaises(sprint_store.SprintCorruptError):
            sprint_store.load_sprint(self.smm_dir)

    def test_load_invalid_schema_raises_corrupt_error(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text('{"bad": "schema"}')
        with self.assertRaises(sprint_store.SprintCorruptError):
            sprint_store.load_sprint(self.smm_dir)

    def test_load_undecodable_bytes_raises_corrupt_error(self):
        # Byte-level corruption is the third unusable-content cause, alongside
        # malformed JSON and schema-invalid. It must surface as the SAME type:
        # every guard that keeps the `create` repair path open catches
        # SprintCorruptError, so a UnicodeDecodeError leaking through as itself
        # bypasses them all and tracebacks the only tool that can overwrite the
        # bad file.
        import sprint_store

        (self.smm_dir / "sprint.json").write_bytes(b'{"goal": "\xff\xfe"}')
        with self.assertRaises(sprint_store.SprintCorruptError):
            sprint_store.load_sprint(self.smm_dir)

    def test_fail_open_degrades_undecodable_bytes_to_none(self):
        # load_sprint_fail_open catches (SprintCorruptError, OSError) — so it
        # only degrades byte corruption once load_sprint raises the right type.
        import sprint_store

        (self.smm_dir / "sprint.json").write_bytes(b'{"goal": "\xff\xfe"}')
        self.assertIsNone(sprint_store.load_sprint_fail_open(self.smm_dir))

    def test_corrupt_error_is_value_error_subclass(self):
        # Existing handlers catch (ValueError, OSError); the new type must
        # remain catchable by them so only the opt-in gate changes behavior.
        import sprint_store

        self.assertTrue(issubclass(sprint_store.SprintCorruptError, ValueError))

    def test_missing_story_raises_plain_value_error_not_corrupt(self):
        # A valid sprint with an absent story id is ABSENCE, not corruption —
        # get_story must raise plain ValueError, never SprintCorruptError, so
        # the gate can fail open on a missing story while failing hard on a
        # corrupt file.
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        with self.assertRaises(ValueError) as ctx:
            sprint_store.get_story(self.smm_dir, "story-999")
        self.assertNotIsInstance(ctx.exception, sprint_store.SprintCorruptError)


class TestSaveSprint(_SMMTestCase):
    def test_save_valid(self):
        import sprint_store

        sprint_store.save_sprint(self.smm_dir, _make_sprint())
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_save_invalid_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.save_sprint(self.smm_dir, {"bad": "data"})

    def test_save_clears_needs_sprint_marker(self):
        import sprint_store

        marker = self.smm_dir / ".needs-sprint"
        marker.write_text("startup")
        sprint_store.save_sprint(self.smm_dir, _make_sprint())
        self.assertFalse(marker.exists())

    def test_save_keeps_marker_when_no_active(self):
        import sprint_store

        marker = self.smm_dir / ".needs-sprint"
        marker.write_text("startup")
        sprint = _make_sprint(stories=[_make_story(status="done")])
        sprint_store.save_sprint(self.smm_dir, sprint)
        self.assertTrue(marker.exists())


# ===========================================================================
# Update story status
# ===========================================================================


class TestUpdateStoryStatus(_SMMTestCase):
    def test_update_to_in_progress(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        sprint_store.update_story_status(self.smm_dir, "story-001", "in-progress")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")

    def test_update_to_done(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "done")

    def test_invalid_story_id_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        with self.assertRaises(ValueError):
            sprint_store.update_story_status(self.smm_dir, "story-999", "done")

    def test_no_sprint_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.update_story_status(self.smm_dir, "story-001", "done")


class TestUpdateStoryStatusIf(_SMMTestCase):
    """Atomic compare-and-swap on story status.

    Closes the get_story → update_story_status TOCTOU window in
    spawn_teammate.py: load+check+save run under a single flock so a
    concurrent mutation between read and write cannot silently demote
    a story already advanced past in-progress.
    """

    def _seed(self, status: str) -> None:
        sprint = _make_sprint(stories=[_make_story(status=status)])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _read_status(self) -> str:
        return json.loads((self.smm_dir / "sprint.json").read_text())["stories"][0][
            "status"
        ]

    def test_returns_true_and_updates_when_status_matches(self):
        import sprint_store

        self._seed("in-progress")
        result = sprint_store.update_story_status_if(
            self.smm_dir, "story-001", expected="in-progress", new="reviewing"
        )
        self.assertTrue(result)
        self.assertEqual(self._read_status(), "reviewing")

    def test_returns_false_and_leaves_status_when_already_done(self):
        """Pins concern 3ba0b6237c65: rc=0 promote must not demote a story
        already advanced past in-progress (e.g. user manually flipped it
        to done mid-run, or an orchestrator raced past)."""
        import sprint_store

        self._seed("done")
        result = sprint_store.update_story_status_if(
            self.smm_dir, "story-001", expected="in-progress", new="reviewing"
        )
        self.assertFalse(result)
        self.assertEqual(self._read_status(), "done")

    def test_invalid_new_status_raises_before_load(self):
        """Boundary validation matches update_story_status — `new` must be
        a known status. Raises before touching the sprint file."""
        import sprint_store

        self._seed("in-progress")
        with self.assertRaises(ValueError):
            sprint_store.update_story_status_if(
                self.smm_dir, "story-001", expected="in-progress", new="bogus"
            )
        # Status untouched.
        self.assertEqual(self._read_status(), "in-progress")

    def test_unknown_story_id_raises(self):
        import sprint_store

        self._seed("in-progress")
        with self.assertRaises(ValueError):
            sprint_store.update_story_status_if(
                self.smm_dir, "story-999", expected="in-progress", new="reviewing"
            )

    def test_no_sprint_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.update_story_status_if(
                self.smm_dir, "story-001", expected="in-progress", new="reviewing"
            )

    def test_concurrent_callers_serialize_via_lock(self):
        """Two parallel processes both attempting in-progress → reviewing.

        Exactly one must see status==expected and update; the other must
        observe the post-update status (`reviewing` ≠ `in-progress`) and
        return False. If both returned True, the lock isn't holding the
        load-modify-save together as a single critical section.
        """
        import subprocess
        import sys as _sys

        self._seed("in-progress")

        plugin_root = Path(__file__).parent.parent.parent
        smm_pkg = plugin_root / "smm"
        snippet = (
            "import sys\n"
            f"sys.path.insert(0, {str(smm_pkg)!r})\n"
            "from pathlib import Path\n"
            "import sprint_store\n"
            "r = sprint_store.update_story_status_if(\n"
            f"    Path({str(self.smm_dir)!r}),\n"
            "    'story-001', expected='in-progress', new='reviewing'\n"
            ")\n"
            "print('TRUE' if r else 'FALSE')\n"
        )

        procs = [
            subprocess.Popen(
                [_sys.executable, "-c", snippet],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        outs = [p.communicate(timeout=15) for p in procs]

        for p, (_stdout, stderr) in zip(procs, outs, strict=True):
            self.assertEqual(p.returncode, 0, f"subprocess failed: {stderr}")

        results = sorted(o[0].strip() for o in outs)
        self.assertEqual(
            results,
            ["FALSE", "TRUE"],
            f"expected exactly one TRUE/FALSE pair, got {results!r}",
        )
        # Final status reflects the winning CAS.
        self.assertEqual(self._read_status(), "reviewing")


class TestSetBranch(_SMMTestCase):
    def test_writes_branch_name(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        sprint_store.set_branch(self.smm_dir, "paul/sprint-031-test")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["branch_name"], "paul/sprint-031-test")

    def test_overwrites_existing(self):
        import sprint_store

        sprint = _make_sprint(branch_name="old/name")
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        sprint_store.set_branch(self.smm_dir, "new/name")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["branch_name"], "new/name")

    def test_no_sprint_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.set_branch(self.smm_dir, "paul/sprint-031-test")


class TestSetStoryBranch(_SMMTestCase):
    def test_writes_story_branch_name(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        sprint_store.set_story_branch(self.smm_dir, "story-001", "paul/story-001-foo")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["branch_name"], "paul/story-001-foo")

    def test_overwrites_existing(self):
        import sprint_store

        story = _make_story(branch_name="old/branch")
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[story]))
        )
        sprint_store.set_story_branch(self.smm_dir, "story-001", "new/branch")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["branch_name"], "new/branch")

    def test_invalid_story_id_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        with self.assertRaises(ValueError):
            sprint_store.set_story_branch(
                self.smm_dir, "story-999", "paul/story-999-foo"
            )

    def test_no_sprint_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.set_story_branch(
                self.smm_dir, "story-001", "paul/story-001-foo"
            )


_PROSE_MANUAL = {"type": "manual", "command": "go read the logs and confirm X"}


class TestManualShapeAtAuthoring(_SMMTestCase):
    """A manual acceptance block may not carry a command at authoring time.

    Prose declared in `command` used to reach the runner, which shelled it
    for an exit 127 that read as a plain red. The write must now fail
    loudly instead. Stored blocks are grandfathered per story, derived from
    disk and failing CLOSED — see TestManualShapeGrandfathering.
    """

    def _store(self, sprint: dict) -> None:
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_save_rejects_prose_in_manual_command(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[_make_story(acceptance_execution=dict(_PROSE_MANUAL))]
        )
        with self.assertRaises(ValueError) as ctx:
            sprint_store.save_sprint(self.smm_dir, sprint)
        msg = str(ctx.exception)
        self.assertIn("command", msg)
        self.assertIn("manual", msg)
        self.assertIn("steps", msg)

    def test_save_accepts_manual_with_steps_only(self):
        import sprint_store

        ae = {"type": "manual", "steps": ["Deploy to staging", "Confirm redirect"]}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        sprint_store.save_sprint(self.smm_dir, sprint)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["acceptance_execution"], ae)

    def test_save_accepts_non_manual_with_command(self):
        import sprint_store

        ae = {"type": "pytest", "command": "pytest tests/"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        sprint_store.save_sprint(self.smm_dir, sprint)

    def test_missing_sprint_grants_no_exemption(self):
        # Fail closed: no file on disk is no proof anything was grandfathered.
        import sprint_store

        sprint = _make_sprint(
            stories=[_make_story(acceptance_execution=dict(_PROSE_MANUAL))]
        )
        with self.assertRaises(ValueError):
            sprint_store.save_sprint(self.smm_dir, sprint)

    def test_corrupt_sprint_grants_no_exemption(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text("{bad json")
        sprint = _make_sprint(
            stories=[_make_story(acceptance_execution=dict(_PROSE_MANUAL))]
        )
        with self.assertRaises(ValueError):
            sprint_store.save_sprint(self.smm_dir, sprint)


class TestManualShapeGrandfathering(_SMMTestCase):
    """A manual+command block ALREADY on disk keeps the sprint editable.

    validate_sprint walks every story, so a flag-only rule would make one
    stored block refuse every later, unrelated write on that sprint. The
    exemption is per story and covers only an UNCHANGED stored block.
    """

    def setUp(self):
        super().setUp()
        self.stored = _make_story(
            id="story-001", acceptance_execution=dict(_PROSE_MANUAL)
        )
        self.other = _make_story(id="story-002", context="Second story.")
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[self.stored, self.other]))
        )

    def test_stored_block_still_loads(self):
        import sprint_store

        loaded = sprint_store.load_sprint_required(self.smm_dir)
        self.assertEqual(loaded["stories"][0]["acceptance_execution"], _PROSE_MANUAL)

    def test_status_update_still_succeeds(self):
        import sprint_store

        sprint_store.update_story_status(self.smm_dir, "story-001", "in-progress")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")

    def test_editing_a_different_story_still_succeeds(self):
        import sprint_store

        sprint_store.edit_story(self.smm_dir, "story-002", {"context": "Rewritten."})
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][1]["context"], "Rewritten.")

    def test_editing_the_offending_block_is_rejected(self):
        import sprint_store

        updates = {"acceptance_execution": {"type": "manual", "command": "still prose"}}
        with self.assertRaises(ValueError) as ctx:
            sprint_store.edit_story(self.smm_dir, "story-001", updates)
        self.assertIn("steps", str(ctx.exception))


# Status check functions, compute_velocity, compute_blockers, count_by_status
# tests live in test_sprint_status.py — split per the 500-line cap. Render
# tests live in test_sprint_render.py. Load/save and mutations stay here.
# transitive_active_dependents tests live in test_sprint_store_dependents.py.
# ready_frontier{,_data} tests live in test_sprint_frontier.py — split
# for the 500-line cap (the frontier query is a distinct read-path concern).


if __name__ == "__main__":
    unittest.main()

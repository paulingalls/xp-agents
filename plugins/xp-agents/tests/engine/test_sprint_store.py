#!/usr/bin/env python3
"""Tests for sprint_store.py — load/save and mutations.

Covers: load/save, update_story_status, set_branch, set_story_branch.
Render (render_markdown, render_story_sections) lives in
test_sprint_render.py — moved with the sprint_render extraction.
Status checks (has_active_*, is_complete, scheduled_*), compute_velocity,
compute_blockers, and count_by_status live in test_sprint_status.py
(split for the 500-line cap). Schema validation tests live in
test_sprint_schema.py.
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

    def test_load_corrupt_json_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text("{bad json")
        with self.assertRaises(ValueError):
            sprint_store.load_sprint(self.smm_dir)

    def test_load_invalid_schema_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text('{"bad": "schema"}')
        with self.assertRaises(ValueError):
            sprint_store.load_sprint(self.smm_dir)


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


# Status check functions, compute_velocity, compute_blockers, count_by_status
# tests live in test_sprint_status.py — split per the 500-line cap. Render
# tests live in test_sprint_render.py. Load/save and mutations stay here.


# ===========================================================================
# Render
# ===========================================================================


class TestTransitiveActiveDependents(_SMMTestCase):
    """Return sorted in-motion stories transitively blocked by a given story."""

    def _write(self, *stories: dict) -> None:
        sprint = _make_sprint(stories=list(stories))
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_no_sprint_returns_empty(self):
        import sprint_store

        result = sprint_store.transitive_active_dependents(self.smm_dir, "story-001")
        self.assertEqual(result, [])

    def test_no_dependents_returns_empty(self):
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(id="story-002", status="in-progress"),
        )
        result = sprint_store.transitive_active_dependents(self.smm_dir, "story-001")
        self.assertEqual(result, [])

    def test_direct_in_progress_dependent_returned(self):
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="in-progress",
                dependencies=["story-001"],
            ),
        )
        self.assertEqual(
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            ["story-002"],
        )

    def test_transitive_active_dependents_returned_sorted(self):
        import sprint_store

        # story-001 → story-002 → story-003; all in-progress.
        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="in-progress",
                dependencies=["story-001"],
            ),
            _make_story(
                id="story-003",
                status="in-progress",
                dependencies=["story-002"],
            ),
        )
        self.assertEqual(
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            ["story-002", "story-003"],
        )

    def test_done_dependent_excluded(self):
        # A done dependent has already shipped — no need to defer it. The
        # transitive walk must filter by status, not by dependency edge alone.
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(id="story-002", status="done", dependencies=["story-001"]),
        )
        self.assertEqual(
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            [],
        )

    def test_reviewing_dependent_cascades(self):
        # A reviewing dependent is mid-acceptance — if its base story has
        # to be deferred, the reviewing story's verification work is
        # invalidated and it must cascade-defer too. Without this widening,
        # /xp-accept would happily mark the reviewing story done against a
        # broken base.
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="reviewing",
                dependencies=["story-001"],
            ),
        )
        self.assertEqual(
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            ["story-002"],
        )

    def test_dependency_cycle_terminates(self):
        # Sprint schema doesn't enforce DAG; a cycle (story depending on
        # itself, or A↔B) must not infinite-loop the walker. Real cycles
        # come from copy-paste typos in sprint.json.
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="in-progress",
                dependencies=["story-001", "story-002"],
            ),
        )
        result = sprint_store.transitive_active_dependents(self.smm_dir, "story-001")
        self.assertEqual(result, ["story-002"])


# ===========================================================================
# Status-module extraction + re-export shim (story-008)
# ===========================================================================
# When sprint_store grew past 500 lines, the 8 status-check functions were
# moved into a sibling module sprint_status. This class pins both the new
# import path AND the legacy import path through sprint_store, so the 16+
# existing callers keep working without churn (constraint 2c19173dad39).


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for the edit_story file_domain collision guard (sprint-115 M2, story-006).

`sprint_store.edit_story` bypasses `sprint_save.run()` — it shallow-merges the
update dict and writes directly, skipping M1's collision gate. Without a guard,
an edit-story can rewrite a story's file_domain onto a path a concurrently-runnable
story already owns and silently reintroduce the collision M1 forbids.

These tests pin the guard's this-write-only semantics: a domain edit that INTRODUCES
a collision is refused, but an unrelated-field edit on a legacy sprint that already
holds a pre-existing collision still succeeds (the pre-existing collision is not this
write's fault).

Every claimant here is RUNNING. A mid-sprint amendment asks whether a path is
claimed by a story that is actually running (story-011), so a fixture of parked
stories would make each refusal below vacuously green — the guard would have
nothing to hold. Mirrors the fixture + assertion style of
TestCreateRefusesCollidingSprintE2E and TestAddStoryNotBlockedByPreexistingCollision
in test_sprint_save_sisters_autoinclude.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_store
from conftest import _s, _SMMTestCase, run_cli


def _sprint(stories):
    return {
        "sprint_id": "sprint-001",
        "goal": "t",
        "started": "2026-04-01",
        "milestone": "",
        "stories": stories,
    }


class TestEditStoryCollisionGuard(_SMMTestCase):
    """edit_story refuses a file_domain edit that INTRODUCES a collision on a
    concurrently-runnable path, while leaving every other edit untouched."""

    def _disjoint(self, **b_extra):
        a = _s("story-001", "a", "in-progress")
        a["file_domain"] = ["src/shared.py — a"]
        b = _s("story-002", "b", "in-progress")
        b["file_domain"] = ["src/other.py — b"]
        b.update(b_extra)
        return _sprint([a, b])

    def _preexisting_collision(self, extra_stories=None):
        """Two independent stories already claiming src/shared.py, planted on
        disk via save_sprint DIRECTLY — the edit-story bypass that side-steps
        run()'s gate, so the collision sits on disk without this write's fault."""
        a = _s("story-001", "a", "in-progress")
        a["file_domain"] = ["src/shared.py — a"]
        b = _s("story-002", "b", "in-progress")
        b["file_domain"] = ["src/shared.py — b"]
        stories = [a, b, *(extra_stories or [])]
        return _sprint(stories)

    # AC1 — colliding edit refused
    def test_colliding_domain_edit_is_refused(self):
        sprint_store.save_sprint(self.smm_dir, self._disjoint())
        with self.assertRaises(ValueError) as ctx:
            sprint_store.edit_story(
                self.smm_dir, "story-002", {"file_domain": ["src/shared.py — b"]}
            )
        message = str(ctx.exception)
        self.assertIn("src/shared.py", message)
        self.assertIn("story-001", message)
        self.assertIn("story-002", message)

    def test_refused_edit_leaves_sprint_json_unchanged(self):
        sprint_store.save_sprint(self.smm_dir, self._disjoint())
        before = (self.smm_dir / "sprint.json").read_bytes()
        with self.assertRaises(ValueError):
            sprint_store.edit_story(
                self.smm_dir, "story-002", {"file_domain": ["src/shared.py — b"]}
            )
        self.assertEqual((self.smm_dir / "sprint.json").read_bytes(), before)

    # AC2 — non-file_domain edit allowed, no collision check imposed
    def test_non_file_domain_edit_succeeds_and_writes_field(self):
        sprint_store.save_sprint(self.smm_dir, self._disjoint())
        sprint_store.edit_story(self.smm_dir, "story-002", {"context": "x"})
        story = sprint_store.get_story(self.smm_dir, "story-002")
        self.assertEqual(story["context"], "x")

    # AC3 — pre-existing collision + unrelated-field edit succeeds
    def test_preexisting_collision_allows_unrelated_field_edit(self):
        sprint_store.save_sprint(self.smm_dir, self._preexisting_collision())
        # No file_domain key: the guard must not fire on the pre-existing
        # 001/002 collision this edit did not cause.
        sprint_store.edit_story(self.smm_dir, "story-001", {"context": "x"})
        story = sprint_store.get_story(self.smm_dir, "story-001")
        self.assertEqual(story["context"], "x")

    # AC4 — introduced-only filter: a disjoint domain edit succeeds even while a
    # pre-existing collision sits among OTHER stories.
    def test_disjoint_domain_edit_succeeds_despite_preexisting_collision(self):
        c = _s("story-003", "c", "in-progress")
        c["file_domain"] = ["src/c.py — c"]
        sprint_store.save_sprint(
            self.smm_dir, self._preexisting_collision(extra_stories=[c])
        )
        # story-003's edit is disjoint; the 001/002 collision is not its fault.
        sprint_store.edit_story(
            self.smm_dir, "story-003", {"file_domain": ["src/disjoint.py — c"]}
        )
        story = sprint_store.get_story(self.smm_dir, "story-003")
        self.assertEqual(story["file_domain"], ["src/disjoint.py — c"])

    # AC5 — edit onto a (transitive) dependency's path succeeds
    def test_edit_onto_dependency_path_succeeds(self):
        sprint_store.save_sprint(
            self.smm_dir, self._disjoint(dependencies=["story-001"])
        )
        # story-002 depends on story-001, so the two can never run concurrently
        # and may legally share src/shared.py.
        sprint_store.edit_story(
            self.smm_dir, "story-002", {"file_domain": ["src/shared.py — b"]}
        )
        story = sprint_store.get_story(self.smm_dir, "story-002")
        self.assertEqual(story["file_domain"], ["src/shared.py — b"])


class TestEditStoryCollisionGuardE2E(_SMMTestCase):
    """AC6: drive the real CLI as a subprocess. _cmd_edit_story maps ValueError
    to rc 1, so raising from edit_story covers the edit-story subcommand."""

    _CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"

    def test_colliding_edit_story_exits_nonzero_and_leaves_json_unchanged(self):
        a = _s("story-001", "a", "in-progress")
        a["file_domain"] = ["src/shared.py — a"]
        b = _s("story-002", "b", "in-progress")
        b["file_domain"] = ["src/other.py — b"]
        sprint_store.save_sprint(self.smm_dir, _sprint([a, b]))
        before = (self.smm_dir / "sprint.json").read_bytes()

        result = run_cli(
            self._CLI,
            ["edit-story", "story-002"],
            self.smm_dir,
            json.dumps({"file_domain": ["src/shared.py — b"]}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("src/shared.py", result.stderr)
        self.assertIn("story-001", result.stderr)
        self.assertIn("story-002", result.stderr)
        self.assertEqual((self.smm_dir / "sprint.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

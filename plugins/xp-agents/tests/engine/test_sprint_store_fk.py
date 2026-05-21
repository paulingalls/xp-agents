#!/usr/bin/env python3
"""save_sprint enforces the per-AC verify.surface FK (adopted retro Try).

sprint_store.save_sprint loads the project's acceptance_surfaces names and
threads them into validate_sprint as valid_surfaces, so an acceptance_criteria
object naming a surface that doesn't exist is rejected on write. Enforcement is
save-only — load_sprint and mutate/resave paths stay shape-only (read-path
grandfathering). When no acceptance_surfaces exist, save falls back to
shape-only (no false rejection). Mirrors test_execution_plan_store_fk.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import surfaces as _surfaces
from _system_context_fixtures import valid_doc
from conftest import _SMMTestCase
from conftest import make_sprint_dict as _make_sprint
from conftest import make_story_dict as _make_story
from system_context_schema import SYSTEM_CONTEXT_FILENAME


class TestSaveSprintSurfaceFK(_SMMTestCase):
    def _write_context(self, surfaces: list[dict]) -> None:
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(valid_doc(acceptance_surfaces=surfaces))
        )

    def _sprint(self, surface: str) -> dict:
        story = _make_story(
            acceptance_criteria=[{"description": "works", "surface": surface}]
        )
        return _make_sprint(stories=[story])

    def test_unknown_surface_rejected_on_save(self):
        import sprint_store as store

        self._write_context(_surfaces("cli", "sdk"))
        with self.assertRaises(ValueError) as ctx:
            store.save_sprint(self.smm_dir, self._sprint("ghost"))
        self.assertIn("ghost", str(ctx.exception))

    def test_known_surface_saves_successfully(self):
        import sprint_store as store

        self._write_context(_surfaces("cli", "sdk"))
        store.save_sprint(self.smm_dir, self._sprint("cli"))
        reloaded = store.load_sprint(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(
            reloaded["stories"][0]["acceptance_criteria"][0]["surface"], "cli"
        )

    def test_no_acceptance_surfaces_falls_back_to_shape_only(self):
        import sprint_store as store

        self._write_context([])
        # 'ghost' is unknown, but with no surfaces to check against the FK
        # must not fire — shape-only, no false rejection.
        store.save_sprint(self.smm_dir, self._sprint("ghost"))
        reloaded = store.load_sprint(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(
            reloaded["stories"][0]["acceptance_criteria"][0]["surface"], "ghost"
        )

    def test_malformed_system_context_degrades_to_shape_only(self):
        import sprint_store as store

        # A partial/legacy system_context (missing required fields) must not
        # block sprint saves — the FK degrades to shape-only rather than raising.
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps({"branching_strategy": {"stage": 2}})
        )
        store.save_sprint(self.smm_dir, self._sprint("ghost"))
        reloaded = store.load_sprint(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(
            reloaded["stories"][0]["acceptance_criteria"][0]["surface"], "ghost"
        )

    def test_symlinked_system_context_degrades_to_shape_only(self):
        import sprint_store as store

        # load_system_context raises OSError on a symlinked context. That
        # OSError is intentionally swallowed on the FK path (the symlink
        # defense still fires on the dedicated load/save paths), so the sprint
        # save degrades to shape-only rather than blocking.
        target = self.smm_dir / "real_context.json"
        target.write_text(json.dumps(valid_doc(acceptance_surfaces=_surfaces("cli"))))
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).symlink_to(target)
        store.save_sprint(self.smm_dir, self._sprint("ghost"))
        reloaded = store.load_sprint(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(
            reloaded["stories"][0]["acceptance_criteria"][0]["surface"], "ghost"
        )

    def test_mutate_resave_grandfathers_surface_drift(self):
        import sprint_store as store

        # Author a valid sprint, then drift acceptance_surfaces (drop 'sdk').
        # A mutate/resave path (update_story_status, enforce_budget=False) must
        # not raise on the untouched per-AC surface — the FK only enforces on
        # strict authoring saves.
        self._write_context(_surfaces("cli", "sdk"))
        story = _make_story(
            id="story-001",
            status="ready",
            acceptance_criteria=[{"description": "works", "surface": "sdk"}],
        )
        store.save_sprint(self.smm_dir, _make_sprint(stories=[story]))
        self._write_context(_surfaces("cli"))
        store.update_story_status(self.smm_dir, "story-001", "in-progress")
        reloaded = store.load_sprint(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(reloaded["stories"][0]["status"], "in-progress")

    def test_e2e_ghost_rejected_valid_round_trips(self):
        import sprint_store as store

        self._write_context(_surfaces("cli", "sdk"))
        with self.assertRaises(ValueError):
            store.save_sprint(self.smm_dir, self._sprint("ghost"))
        store.save_sprint(self.smm_dir, self._sprint("sdk"))
        reloaded = store.load_sprint(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(
            reloaded["stories"][0]["acceptance_criteria"][0]["surface"], "sdk"
        )


if __name__ == "__main__":
    unittest.main()

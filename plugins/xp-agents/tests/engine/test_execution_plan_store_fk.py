#!/usr/bin/env python3
"""save_plan enforces the milestone.surfaces_touched FK (adopted retro Try).

execution_plan_store.save_plan loads the project's acceptance_surfaces names
and threads them into validate_plan as valid_surfaces, so a surfaces_touched
entry naming a surface that doesn't exist is rejected on write. Enforcement is
save-only — load_plan stays shape-only (read-path grandfathering). When no
acceptance_surfaces exist, save falls back to shape-only (no false rejection).
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
from conftest import make_milestone_dict as _make_milestone
from conftest import make_plan_dict as _make_plan
from system_context_schema import SYSTEM_CONTEXT_FILENAME


class TestSavePlanSurfaceFK(_SMMTestCase):
    def _write_context(self, surfaces: list[dict]) -> None:
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(valid_doc(acceptance_surfaces=surfaces))
        )

    def _plan(self, surfaces_touched: list[str]) -> dict:
        return _make_plan(
            milestones=[_make_milestone(surfaces_touched=surfaces_touched)]
        )

    def test_unknown_surface_rejected_on_save(self):
        import execution_plan_store as store

        self._write_context(_surfaces("cli", "sdk"))
        with self.assertRaises(ValueError) as ctx:
            store.save_plan(self.smm_dir, self._plan(["ghost"]))
        self.assertIn("ghost", str(ctx.exception))

    def test_known_surfaces_save_successfully(self):
        import execution_plan_store as store

        self._write_context(_surfaces("cli", "sdk"))
        store.save_plan(self.smm_dir, self._plan(["cli", "sdk"]))
        reloaded = store.load_plan(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(reloaded["milestones"][0]["surfaces_touched"], ["cli", "sdk"])

    def test_no_acceptance_surfaces_falls_back_to_shape_only(self):
        import execution_plan_store as store

        self._write_context([])
        # 'ghost' is unknown, but with no surfaces to check against the FK
        # must not fire — shape-only, no false rejection.
        store.save_plan(self.smm_dir, self._plan(["ghost"]))
        reloaded = store.load_plan(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(reloaded["milestones"][0]["surfaces_touched"], ["ghost"])

    def test_malformed_system_context_degrades_to_shape_only(self):
        import execution_plan_store as store

        # A partial/legacy system_context (missing required fields) must not
        # block plan saves — the FK degrades to shape-only rather than raising.
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps({"branching_strategy": {"stage": 2}})
        )
        store.save_plan(self.smm_dir, self._plan(["ghost"]))
        reloaded = store.load_plan(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(reloaded["milestones"][0]["surfaces_touched"], ["ghost"])

    def test_symlinked_system_context_degrades_to_shape_only(self):
        import execution_plan_store as store

        # load_system_context raises OSError on a symlinked context. That
        # OSError is intentionally swallowed on the FK path (the symlink
        # defense still fires on the dedicated load/save paths), so the plan
        # save degrades to shape-only rather than blocking.
        target = self.smm_dir / "real_context.json"
        target.write_text(json.dumps(valid_doc(acceptance_surfaces=_surfaces("cli"))))
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).symlink_to(target)
        store.save_plan(self.smm_dir, self._plan(["ghost"]))
        reloaded = store.load_plan(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(reloaded["milestones"][0]["surfaces_touched"], ["ghost"])

    def test_mutate_resave_grandfathers_surface_drift(self):
        import execution_plan_store as store

        # Author a valid plan, then drift acceptance_surfaces (drop 'sdk').
        # A mutate/resave path (update_milestone_status, enforce_budget=False)
        # must not raise on the untouched surfaces_touched — the FK only
        # enforces on strict authoring saves.
        self._write_context(_surfaces("cli", "sdk"))
        store.save_plan(self.smm_dir, self._plan(["sdk"]))
        self._write_context(_surfaces("cli"))
        store.update_milestone_status(self.smm_dir, 1, "in-progress")
        reloaded = store.load_plan(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(reloaded["milestones"][0]["status"], "in-progress")

    def test_e2e_ghost_rejected_valid_round_trips(self):
        import execution_plan_store as store

        self._write_context(_surfaces("cli", "sdk"))
        with self.assertRaises(ValueError):
            store.save_plan(self.smm_dir, self._plan(["sdk", "ghost"]))
        store.save_plan(self.smm_dir, self._plan(["sdk"]))
        reloaded = store.load_plan(self.smm_dir)
        assert reloaded is not None
        self.assertEqual(reloaded["milestones"][0]["surfaces_touched"], ["sdk"])


if __name__ == "__main__":
    unittest.main()

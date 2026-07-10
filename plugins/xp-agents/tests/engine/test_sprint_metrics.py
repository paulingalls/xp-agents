#!/usr/bin/env python3
"""Tests for sprint_metrics.py and the sprint_store re-export shim.

Pins the refactor-extraction-discipline contract (decision 03cb90c9b2d7):
sprint_metrics.py owns the computed-field helpers (count_by_status,
compute_velocity, compute_blockers, list_stories, next_sprint_id);
sprint_store.py re-exports them so existing import sites keep working
without churn. Behavior tests for these functions already live in
test_sprint_status.py and test_sprint_cli.py — the identity check here
only pins that the bodies were MOVED, not copied.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class TestSprintMetricsModuleAndShim(unittest.TestCase):
    """Pins the extraction: bodies live in sprint_metrics.py, sprint_store
    re-exports the same callables (not copies) so both old and new import
    paths keep working.
    """

    _METRICS_NAMES = (
        "count_by_status",
        "compute_velocity",
        "compute_blockers",
        "list_stories",
        "next_sprint_id",
    )

    def test_new_module_exposes_all_metrics_functions(self):
        import sprint_metrics

        for name in self._METRICS_NAMES:
            self.assertTrue(
                hasattr(sprint_metrics, name), f"sprint_metrics missing {name}"
            )

    def test_sprint_store_reexports_are_identical_objects(self):
        import sprint_metrics
        import sprint_store

        for name in self._METRICS_NAMES:
            self.assertIs(
                getattr(sprint_store, name),
                getattr(sprint_metrics, name),
                f"{name} was copied, not moved",
            )


if __name__ == "__main__":
    unittest.main()

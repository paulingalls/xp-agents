#!/usr/bin/env python3
"""Tests for sprint_status.py and the sprint_store re-export shim.

Pins the refactor-extraction-discipline contract (constraint 2c19173dad39):
sprint_status.py owns the 8 status-check functions; sprint_store.py
re-exports them so 16+ existing import sites keep working without churn.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class TestSprintStatusModuleAndShim(unittest.TestCase):
    _STATUS_NAMES = (
        "has_active_stories",
        "has_active_stories_data",
        "has_stories_with_status",
        "has_in_progress_stories",
        "has_ready_stories",
        "has_scheduled_stories",
        "scheduled_file_domains_overlap",
        "is_complete",
    )

    def test_new_module_exposes_all_status_functions(self):
        import sprint_status

        for name in self._STATUS_NAMES:
            self.assertTrue(
                callable(getattr(sprint_status, name, None)),
                f"sprint_status.{name} should be a callable",
            )

    def test_sprint_store_reexports_status_functions(self):
        import sprint_status
        import sprint_store

        for name in self._STATUS_NAMES:
            store_fn = getattr(sprint_store, name, None)
            status_fn = getattr(sprint_status, name, None)
            self.assertIs(
                store_fn,
                status_fn,
                f"sprint_store.{name} must re-export sprint_status.{name}",
            )


if __name__ == "__main__":
    unittest.main()

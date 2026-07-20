#!/usr/bin/env python3
"""Shared fixtures for the test_work_selection_decide*.py test family.

Not test_-prefixed — not pytest-collected. Houses the base TestCase classes
and constants used by MORE THAN ONE sibling test module (parent
test_work_selection_decide.py plus the split-off
test_work_selection_decide_{triage,force_close_gate,force_close_extra,
drop_cascade}.py), so no sibling needs to import another sibling — or the
parent — just to reach shared setup.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(
    0,
    str(Path(__file__).parent.parent / "skills" / "xp-work-selection" / "scripts"),
)

import work_selection_decide
from conftest import _HookTestCase
from event_schema import EVENT_TYPE_STATUS

# The exact metadata every retro-lane disposition now carries. Spelled out once:
# a test that asserts the whole dict is what catches a lane tag going missing,
# and a missing lane tag silently disarms the FORCE-CLOSE gate.
_RETRO_DEFERRED = {"action": "retro_try_disposition", "disposition": "deferred"}
_RETRO_DROPPED = {"action": "retro_try_disposition", "disposition": "dropped"}


class _DecideTestCase(_HookTestCase):
    """Shared setup: expose mod + _last_event() + _run_main()."""

    def setUp(self):
        super().setUp()
        self.mod = work_selection_decide
        # Chdir out of any worktree path so agent_id resolves to "main".
        self._prev_cwd = os.getcwd()
        os.chdir(self.smm_dir)

    def tearDown(self):
        os.chdir(self._prev_cwd)
        super().tearDown()

    def _last_event(self) -> dict:
        events = self._read_events()
        self.assertGreater(len(events), 0, "expected at least one event")
        return events[-1]

    def _run_main(self, argv: list[str]) -> int:
        old_argv = sys.argv
        sys.argv = ["work_selection_decide.py", *argv]
        try:
            self.mod.main()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
        finally:
            sys.argv = old_argv


class _ForceCloseTestCase(_DecideTestCase):
    """Helpers for seeding prior-defer history against a Try id.

    `link_field` selects how the seeded deferral names its Try:
      - "resolves"   → legacy metadata.resolves (every deferral already on
                       disk in a real SMM log carries this shape)
      - "references" → the new top-level field deferrals write from now on
    The gate must count BOTH, or migrating the writer silently resets every
    Try's deferral count to zero and disarms the gate on exactly the Tries it
    exists to catch.
    """

    def _seed_prior_defers(
        self, try_ref_id: str, count: int, link_field: str = "resolves"
    ) -> None:
        self._write_events(
            [self._defer_event(i, try_ref_id, link_field) for i in range(count)]
        )

    def _defer_event(self, index: int, try_ref_id: str, link_field: str) -> dict:
        event = {
            "id": f"{index:012x}",
            "ts": f"2026-01-{index + 1:02d}T00:00:00+00:00",
            "type": EVENT_TYPE_STATUS,
            "agent_id": "main",
            "content": f"Defer {index}",
            "schema_version": 1,
            "working_on": [],
            "metadata": {"disposition": "deferred"},
        }
        match link_field:
            case "resolves":
                event["metadata"]["resolves"] = [try_ref_id]
            case "references":
                event["references"] = [try_ref_id]
            case _:
                raise ValueError(f"unknown link_field: {link_field}")
        return event

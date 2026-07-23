#!/usr/bin/env python3
"""Shared fixtures for the TDD gate's session-scoping test suites.

Split into its own module (not defined locally) because two test files now
exercise them: test_tdd_gate_session_scope.py and
test_tdd_gate_in_place_teammate.py (the latter split out when the collapse
pins pushed the former past the project's 500-line cap).
"""

from unittest.mock import patch

import tdd_stop_gate
from conftest import _HookTestCase, _make_stop_input, make_event
from event_schema import EVENT_TYPE_SESSION_STARTED, EVENT_TYPE_STATUS


def session_anchor() -> dict:
    """The boundary event. Emitted on startup/clear only — NOT on resume or
    compact, so compaction cannot reset the window and disarm the gate."""
    return make_event(EVENT_TYPE_SESSION_STARTED, content="Session started")


def filler(n: int) -> list[dict]:
    """Events carrying no test signal at all."""
    return [make_event(EVENT_TYPE_STATUS, content=f"Edited file {i}") for i in range(n)]


class _GateTestCase(_HookTestCase):
    """Drives the Stop gate with a mocked working tree."""

    def _stop(self, events: list[dict], *, dirty: bool, cwd: str = ".") -> str | None:
        self._write_events(events)
        uncommitted = ["src/app.py"] if dirty else []
        with patch("commits.get_uncommitted_files", return_value=uncommitted) as mock:
            result = tdd_stop_gate.run(_make_stop_input(cwd=cwd), smm_dir=self.smm_dir)
        self.tree_was_checked = mock.called
        return result

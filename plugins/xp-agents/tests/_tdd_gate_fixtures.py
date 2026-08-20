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

TEAMMATE_CWD = "/Users/dev/xp-agents/.claude/worktrees/worktree-story-003"
"""A worktree teammate's hook cwd — the `worktree-story-` segment
`extract_worktree_name` keys on. Shared because two modules now assert against
this exact path (session scoping and the coordination release), and two
independently-written copies of a path a resolver parses is a drift hazard, not
a convenience."""


def session_anchor() -> dict:
    """The boundary event. Emitted on startup/clear only — NOT on resume or
    compact, so compaction cannot reset the window and disarm the gate."""
    return make_event(EVENT_TYPE_SESSION_STARTED, content="Session started")


def filler(n: int) -> list[dict]:
    """Events carrying no test signal at all."""
    return [make_event(EVENT_TYPE_STATUS, content=f"Edited file {i}") for i in range(n)]


class _GateTestCase(_HookTestCase):
    """Drives the Stop gate with a mocked working tree."""

    def _stop(
        self,
        events: list[dict],
        *,
        dirty: bool,
        cwd: str = ".",
        agent_id: str | None = "main",
    ) -> str | None:
        """Drive the Stop gate against a mocked working tree.

        `agent_id=None` DROPS the key, which is the shape a real Stop payload
        has: the harness sends `agent_id` only when a hook fires inside a
        subagent call, and Stop fires on the main thread. `_make_stop_input`
        always injects `"main"`, so without this keyword no test reachable
        through this fixture can express that payload — which is how the gate's
        absent-id fail-open survived. Passing `""` gives the empty spelling;
        the default keeps every pre-existing caller byte-identical.
        """
        self._write_events(events)
        uncommitted = ["src/app.py"] if dirty else []
        payload = _make_stop_input(cwd=cwd)
        if agent_id is None:
            payload.pop("agent_id", None)
        else:
            payload["agent_id"] = agent_id
        with patch(
            "worktree_state.get_uncommitted_files", return_value=uncommitted
        ) as mock:
            result = tdd_stop_gate.run(payload, smm_dir=self.smm_dir)
        self.tree_was_checked = mock.called
        return result

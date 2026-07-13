#!/usr/bin/env python3
"""Shared fixtures for the lead-only Write/Edit gates (scripts/lead_gates.py).

Extracted when test_lead_gates.py crossed the 500-line cap and its fail-closed
suite moved out to test_write_gate_fails_closed.py — two test modules now drive
the same gate, so the sprint fixtures and the `_spawned` patch live here rather
than being imported test-module-to-test-module. Follows the `tests/_*.py`
convention (_branching_fixtures, _event_fixtures, _spawn_guard).
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import lead_gates
import pre_tool_write
from conftest import _HookTestCase, _make_write_input, _s, _sprint_json

# The branch /xp-assign cuts for a story and records ON the story (Step 2) BEFORE
# it spawns the teammate onto it (Step 4). A story counts as spawned only when a
# live worktree is checked out on THIS branch — see lead_gates._story_is_spawned.
# The story id alone cannot say: ids repeat every sprint, so last sprint's
# `worktree-story-001` is indistinguishable from this one's by name.
BRANCH_001 = "dev/story-001-login"
BRANCH_002 = "dev/story-002-register"

# One teammate story promoted to in-progress — the state /xp-assign exists to
# act on. Whether the gate fires depends on whether it has a worktree yet.
SPRINT_TEAMMATE_IN_PROGRESS = _sprint_json(
    [
        _s(
            "story-001",
            "As a user I can log in",
            "in-progress",
            execution_mode="teammate",
            branch_name=BRANCH_001,
        )
    ]
)

# The stale case: the story the marker was armed for is done. Nothing to assign.
SPRINT_ALL_ACCEPTED = _sprint_json([_s("story-001", "As a user I can log in", "done")])

# The resurrection case: a story is scheduled AFTER the stale marker was
# suppressed. Still nothing to assign — /xp-schedule promotes, /xp-assign spawns.
SPRINT_SCHEDULED_AFTER_STALE = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "done"),
        _s("story-002", "As a user I can register", "scheduled"),
    ]
)

# A solo story in progress: /xp-assign has no teammate to spawn for it.
SPRINT_SOLO_IN_PROGRESS = _sprint_json(
    [_s("story-001", "As a user I can log in", "in-progress", execution_mode="solo")]
)


def _lead_write(**kw):
    return _make_write_input(session_id="t", cwd="/tmp", **kw)


class _AssignGateTestCase(_HookTestCase):
    """Shared setup: arm the marker, control whether teammates are spawned."""

    def _arm(self, sprint_json: str | None = None) -> None:
        (self.smm_dir / ".assign-pending").write_text("xp-plan-reviewer")
        if sprint_json is not None:
            (self.smm_dir / "sprint.json").write_text(sprint_json)

    def _spawned(self, *story_ids: str, branches: dict[str, str] | None = None):
        """Patch the worktree lookup: the named stories have a live teammate.

        Patches the BATCH lookup, not the per-story one: the predicate must
        answer every story from a single `git worktree list`. A per-story lookup
        re-runs that subprocess once per story, on every Write/Edit.

        Each named story's worktree is on the branch the sprint fixture recorded
        for it, so `_spawned("story-001")` means "story-001's OWN teammate is
        live". *branches* overrides that per story — which is how the stale
        cross-sprint worktree is expressed: same story id, DIFFERENT branch.
        """
        default = {"story-001": BRANCH_001, "story-002": BRANCH_002}
        resolved = {**default, **(branches or {})}
        return patch.object(
            lead_gates.worktree,
            "live_teammate_branch_by_story",
            side_effect=lambda _cwd: {
                sid: resolved.get(sid, f"dev/{sid}") for sid in story_ids
            },
        )

    def _assert_blocks(self, input_data: dict) -> None:
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(input_data, smm_dir=self.smm_dir)
        self.assertIn("xp-assign", str(ctx.exception))

    def _assert_allows(self, input_data: dict) -> None:
        """The assign gate must not fire. Asserts on check_lead_gates directly:
        run() can raise for unrelated reasons (the schedule gate), and a test
        that accepted any BlockedError would pass for the wrong reason.
        """
        try:
            lead_gates.check_lead_gates(input_data, self.smm_dir, is_plan_file=False)
        except _common.BlockedError as e:  # pragma: no cover - failure path
            self.fail(f"assign gate fired when it should not have: {e}")

#!/usr/bin/env python3
"""Capstone smoke test for the deterministic-event-emission doctrine (M3).

For every ``STATUS_ACTION_*`` constant declared in ``event_schema.py``,
this module asserts that a producer driver exists, runs it against a
fresh SMM, and confirms at least one emitted event carries
``metadata.action`` set to the constant's value.

Two assertions, no escape hatch:

1. **Missing-coverage canary** — every ``STATUS_ACTION_*`` constant must
   appear in ``_PRODUCER_CASES`` (driven) or ``_DOCTRINE_GAPS`` (debt
   event filed). A constant absent from both fails this test loud, so a
   future hook that adds a constant without a producer cannot land
   silently.

2. **Per-constant emission** — each driver runs and at least one event
   carries the expected ``metadata.action``. Stubs returning ``[]`` fail
   this assertion until the producer is wired.

Doctrine gaps (constants with no producer) are tracked via debt events
referenced by ID in ``_DOCTRINE_GAPS``. This makes the gap legible and
auditable; silent exclusions are not allowed.
"""

import shutil
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_failure
import bash_post_tool
import event_schema
import post_tool_exit_plan
import post_tool_use
import review_cycle_done
import subagent_stop
from _bases import _PLUGIN_ROOT
from _commit_helpers import patch_commits
from concerns import LINT_CONCERN_PREFIX
from conftest import (
    _HookTestCase,
    _make_bash_failure_input,
    _make_bash_input,
    _make_skill_input,
    _make_stop_input,
    _make_write_input,
    _s,
    make_event,
)
from event_schema import event_action

sys.path.insert(0, str(_PLUGIN_ROOT / "skills" / "xp-sprint-start" / "scripts"))
import save_sprint

Driver = Callable[[Path], list[dict]]


def _all_status_action_values() -> dict[str, str]:
    """Return {constant_name: value} for every STATUS_ACTION_* constant."""
    return {
        name: getattr(event_schema, name)
        for name in dir(event_schema)
        if name.startswith("STATUS_ACTION_")
    }


def _events(smm_dir: Path) -> list[dict]:
    return _common.read_events_raw(smm_dir)


def _drive_file_write(smm_dir: Path) -> list[dict]:
    post_tool_use.run(
        _make_write_input(tool_response={"success": True}),
        smm_dir=smm_dir,
    )
    return _events(smm_dir)


def _drive_test_run_complete(smm_dir: Path) -> list[dict]:
    bash_post_tool.run(
        _make_bash_input(
            command="pytest",
            stdout="===== 3 passed in 0.1s =====",
        ),
        smm_dir=smm_dir,
    )
    return _events(smm_dir)


def _drive_lint_resolved(smm_dir: Path) -> list[dict]:
    seeded = make_event(
        "concern",
        content=f"{LINT_CONCERN_PREFIX}scripts/foo.py: 1 error (X)",
        files=["scripts/foo.py"],
    )
    _common.append_safe(smm_dir, seeded)
    with (
        patch_commits(files=["scripts/foo.py"], body="Fix lint"),
        patch("worktree.normalize_path", side_effect=lambda p, _cwd: p),
        patch(
            "lint_check.detect_linter_config",
            return_value=("ruff", "ruff.toml"),
        ),
        patch("lint_check.run_linter", return_value=None),
    ):
        bash_post_tool.run(
            _make_bash_input(
                command="git commit -m 'Fix lint'",
                stdout="[main abc1234] Fix lint\n 1 file changed",
                cwd=str(smm_dir),
            ),
            smm_dir=smm_dir,
        )
    return _events(smm_dir)


def _drive_bash_failed(smm_dir: Path) -> list[dict]:
    bash_failure.run(
        _make_bash_failure_input(
            command="pytest",
            error="Command failed with status 1",
            exit_code=1,
        ),
        smm_dir=smm_dir,
    )
    return _events(smm_dir)


def _drive_commit_success(smm_dir: Path) -> list[dict]:
    with patch_commits(files=["scripts/foo.py"], body="Add foo"):
        bash_post_tool.run(
            _make_bash_input(
                command="git commit -m 'Add foo'",
                stdout="[main abc1234] Add foo\n 1 file changed",
                cwd=str(smm_dir),
            ),
            smm_dir=smm_dir,
        )
    return _events(smm_dir)


def _drive_subagent_complete(smm_dir: Path) -> list[dict]:
    subagent_stop.run(
        _make_stop_input(agent_type="general-purpose"),
        smm_dir=smm_dir,
    )
    return _events(smm_dir)


def _drive_plan_completed(smm_dir: Path) -> list[dict]:
    # Plan subagent stop emits BOTH plan_completed (completion event) and
    # plan_awaiting_review (gate event) — one driver covers both action assertions.
    subagent_stop.run(
        _make_stop_input(agent_type="Plan"),
        smm_dir=smm_dir,
    )
    return _events(smm_dir)


def _drive_plan_exited(smm_dir: Path) -> list[dict]:
    post_tool_exit_plan.run(
        {
            "session_id": "t",
            "tool_name": "ExitPlanMode",
            "tool_input": {"plan": "do thing"},
            "tool_response": {"filePath": "/tmp/plan.md"},
            "agent_id": "main",
            "cwd": "/tmp",
        },
        smm_dir=smm_dir,
    )
    return _events(smm_dir)


def _drive_review_cycle(skill: str) -> Driver:
    def _runner(smm_dir: Path) -> list[dict]:
        review_cycle_done.run(_make_skill_input(skill=skill), smm_dir=smm_dir)
        return _events(smm_dir)

    return _runner


def _drive_iteration_complete(smm_dir: Path) -> list[dict]:
    # iteration_complete fires only when .accept exists and the sprint has
    # no in-progress stories — otherwise save_sprint treats this as a
    # regular write and emits no lifecycle event.
    (smm_dir / ".accept").write_text("done")
    data = {
        "sprint_id": "sprint-001",
        "goal": "Build auth",
        "started": "2026-04-01",
        "milestone": "",
        "stories": [_s("story-001", "Login", "done")],
    }
    save_sprint.run(data, smm_dir)
    return _events(smm_dir)


# ---------------------------------------------------------------------------
# Producer-case map: constant *name* -> driver callable.
# Keyed by name (not value) so the missing-coverage canary cannot be silenced
# by a duplicated value across two distinct constants.
# ---------------------------------------------------------------------------

_PRODUCER_CASES: dict[str, Driver] = {
    "STATUS_ACTION_FILE_WRITE": _drive_file_write,
    "STATUS_ACTION_TEST_RUN_COMPLETE": _drive_test_run_complete,
    "STATUS_ACTION_LINT_RESOLVED": _drive_lint_resolved,
    "STATUS_ACTION_BASH_FAILED": _drive_bash_failed,
    "STATUS_ACTION_COMMIT_SUCCESS": _drive_commit_success,
    "STATUS_ACTION_SUBAGENT_COMPLETE": _drive_subagent_complete,
    "STATUS_ACTION_PLAN_COMPLETED": _drive_plan_completed,
    "STATUS_ACTION_PLAN_AWAITING_REVIEW": _drive_plan_completed,
    "STATUS_ACTION_PLAN_EXITED": _drive_plan_exited,
    "STATUS_ACTION_SIMPLIFY_COMPLETE": _drive_review_cycle("simplify"),
    "STATUS_ACTION_QR_COMPLETE": _drive_review_cycle("xp-quality-review"),
    "STATUS_ACTION_SECURITY_COMPLETE": _drive_review_cycle("security-review"),
    "STATUS_ACTION_PLAN_REVIEWED": _drive_review_cycle("xp-review-plan"),
    "STATUS_ACTION_HOUSEKEEPING_COMPLETE": _drive_review_cycle("xp-housekeeper"),
    "STATUS_ACTION_ITERATION_COMPLETE": _drive_iteration_complete,
}


# ---------------------------------------------------------------------------
# Doctrine gaps: action_value -> debt event ID. Constants here are declared
# in event_schema.py but have no producer hook. The debt event records the
# gap so it shows up in retro / housekeeping queues until the producer
# lands or the constant is removed.
# ---------------------------------------------------------------------------

_DOCTRINE_GAPS: dict[str, str] = {
    # STATUS_ACTION_SPRINT_RETRO_DONE is consumed by retrospective.py and
    # compact.py expecting a status-type event with this action, but no
    # producer emits one. save_retrospective.py emits the same string
    # value but on a retrospective-type event (via RETRO_ACTION_SPRINT_DONE).
    # Tracked by debt event ef03cbc32f1e — either wire a status producer
    # at sprint-retro completion, or remove the constant and rewrite the
    # consumers against retrospective-type events.
    "STATUS_ACTION_SPRINT_RETRO_DONE": "ef03cbc32f1e",
    # STATUS_ACTION_CONCERN_CLASSIFY is intentionally emitted by the LLM
    # running close skills' Step 5c (via append.sh from
    # _close_pipeline_shared.md), NOT by a Python hook. There's no
    # producer to drive in this canary because the producer is prose
    # in a SKILL.md that the LLM executes. Consumer is
    # smm_cli.py count-classifications, exercised by
    # tests/engine/test_smm_cli_count_classifications.py.
    # Not a debt — this is an intentional LLM-via-SKILL.md producer
    # pattern, the first STATUS_ACTION_* of its kind.
    "STATUS_ACTION_CONCERN_CLASSIFY": "LLM-via-SKILL.md (not a debt)",
}


class TestActionVocabularySmoke(_HookTestCase):
    """Capstone: every STATUS_ACTION_* must be exercised by a driver."""

    def test_missing_coverage_canary(self):
        """Every constant must be in _PRODUCER_CASES or _DOCTRINE_GAPS.

        Keyed on constant *name* — a future constant whose value collides
        with an existing one cannot be silently considered covered.
        """
        constant_names = set(_all_status_action_values())
        covered = set(_PRODUCER_CASES) | set(_DOCTRINE_GAPS)
        missing = sorted(constant_names - covered)
        self.assertEqual(
            missing,
            [],
            "STATUS_ACTION_* constants without a producer driver or "
            f"doctrine-gap debt entry: {missing}. Add a driver to "
            "_PRODUCER_CASES or file a debt event and add to _DOCTRINE_GAPS.",
        )

    def _reset_smm(self) -> None:
        """Wipe smm_dir back to the setUp baseline (events.jsonl + lock).

        Per-subTest reset prevents marker leakage across drivers — e.g.
        ``_drive_iteration_complete`` writes ``.accept`` and review-cycle
        drivers write a review flag. Without this reset, a later driver's
        behavior would depend on dict-iteration order of ``_PRODUCER_CASES``.
        """
        for child in self.smm_dir.iterdir():
            if child.name == "events.lock":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        self.events_file.touch()

    def test_per_constant_action_emitted(self):
        """Each driver emits at least one event with metadata.action = value."""
        for name, driver in _PRODUCER_CASES.items():
            with self.subTest(action=name):
                action_value = getattr(event_schema, name)
                self._reset_smm()
                events = driver(self.smm_dir)
                actions = [event_action(e) for e in events]
                self.assertIn(
                    action_value,
                    actions,
                    f"driver for {name} emitted no event with "
                    f"metadata.action={action_value!r}; actions seen: {actions!r}",
                )


if __name__ == "__main__":
    unittest.main()

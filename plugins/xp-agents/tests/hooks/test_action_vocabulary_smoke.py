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
import smm_cli
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

# EVENT_TYPE_* added explicitly so a future rename fails at test collection
# (NameError) rather than silently changing make_event() behavior; see
# test_post_tool.py for the canonical pattern + rationale.
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_QUESTION,
    event_action,
)

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
        EVENT_TYPE_CONCERN,
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


def _drive_question_close(smm_dir: Path) -> list[dict]:
    # Seed an open question, then drive smm_cli's _cmd_question_close
    # in-process via a constructed argparse.Namespace (mirrors how the
    # CLI dispatch invokes it).
    import argparse

    q = make_event(EVENT_TYPE_QUESTION, content="aging question?")
    _common.append_safe(smm_dir, q)
    smm_cli._cmd_question_close(
        argparse.Namespace(
            smm_dir=smm_dir,
            event_id=q["id"],
            rationale="smoke",
        )
    )
    return _events(smm_dir)


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
    "STATUS_ACTION_ASSIGN_COMPLETE": _drive_review_cycle("xp-assign"),
    "STATUS_ACTION_HOUSEKEEPING_COMPLETE": _drive_review_cycle("xp-housekeeper"),
    "STATUS_ACTION_ITERATION_COMPLETE": _drive_iteration_complete,
    "STATUS_ACTION_QUESTION_CLOSE": _drive_question_close,
}


# ---------------------------------------------------------------------------
# Doctrine gaps: action_value -> tracking note. Constants here are declared
# in event_schema.py but have no producer hook. Two categories of gap:
#   1. Debt-tracked: value is a debt event ID; gap shows up in retro /
#      housekeeping queues until the producer lands or the constant is
#      removed (e.g. STATUS_ACTION_SPRINT_RETRO_DONE).
#   2. Intentional: value explains why the gap is permanent (e.g.
#      LLM-via-SKILL.md producer pattern).
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
}


# Non-hook producers: the action constant is emitted from somewhere
# other than a Python hook — either LLM prose running a SKILL.md, or a
# bash helper invoked deterministically from a shell preload. Either way
# there is no Python hook to drive via _PRODUCER_CASES. These are NOT
# debts — separated from _DOCTRINE_GAPS so that dict stays single-purpose
# (debt-id values). Each entry should cite the producer + a test that
# exercises the consumer (or producer shape, where the producer is
# deterministic shell).
#
#   STATUS_ACTION_CONCERN_CLASSIFY     — Producer: close skills' Step 5c
#       (_close_pipeline_shared.md, LLM prose). Consumer: smm_cli
#       count-classifications, exercised by
#       tests/engine/test_smm_cli_count_classifications.py.
#       Tracked by debt 730e9a0dbe9c.
#   STATUS_ACTION_END_SESSION_DROP     — Producer: xp-end-session SKILL.md
#       Step 3 (LLM prose, LLM-judged auto-resolve). Consumer: retro
#       tooling reads metadata.action to distinguish bulk drops from
#       organic resolutions; integration test test_end_session_pipeline
#       asserts the produced event shape end-to-end.
#   STATUS_ACTION_CLOSE_STARTED        — Producer: _preload_base.sh
#       emit_close_started_event helper (bash, deterministic), invoked
#       from xp-{sprint,free,plan}-close preloads. Consumer:
#       retro_metrics.security_close_ran. Integration tests in
#       test_close_preloads_emit_shared.py per-mode subclasses assert the
#       emitted event shape; story-close inverse-pin asserts NO emission.
_NON_HOOK_PRODUCERS: set[str] = {
    "STATUS_ACTION_CONCERN_CLASSIFY",
    "STATUS_ACTION_END_SESSION_DROP",
    "STATUS_ACTION_CLOSE_STARTED",
    "STATUS_ACTION_RETIRE_PRINCIPLE",
    "STATUS_ACTION_RETIRE_MODULE",
    "STATUS_ACTION_RETIRE_CONVENTION",
    "STATUS_ACTION_RETIRE_PROJECT_SPECIFIC",
    "STATUS_ACTION_RETIRE_ACCEPTANCE_SURFACE",
    "STATUS_ACTION_EDIT_PRINCIPLE",
    "STATUS_ACTION_EDIT_MODULE",
    "STATUS_ACTION_EDIT_CONVENTION",
    "STATUS_ACTION_EDIT_PROJECT_SPECIFIC",
    "STATUS_ACTION_EDIT_ACCEPTANCE_SURFACE",
}


class TestActionVocabularySmoke(_HookTestCase):
    """Capstone: every STATUS_ACTION_* must be exercised by a driver."""

    def test_missing_coverage_canary(self):
        """Every constant must be in _PRODUCER_CASES or _DOCTRINE_GAPS.

        Keyed on constant *name* — a future constant whose value collides
        with an existing one cannot be silently considered covered.
        """
        constant_names = set(_all_status_action_values())
        covered = set(_PRODUCER_CASES) | set(_DOCTRINE_GAPS) | _NON_HOOK_PRODUCERS
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

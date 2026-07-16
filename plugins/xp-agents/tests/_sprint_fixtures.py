#!/usr/bin/env python3
"""Sprint / SMM seeding fixtures for git+SMM tests.

Split out of ``_branching_fixtures.py`` (split-shim per convention
91fcf9b8744d) when that file crossed the 500-line cap. Everything here writes
SMM state — sprint.json, execution_plan.json, system_context.json, event
builders — and touches no git repo, so it holds no ``GIT_ENV`` and imports
nothing from its sibling fixture modules.

Callers should keep importing from ``_branching_fixtures``, which re-exports
every name below by identity.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import execution_plan_store
import sprint_store
from _event_fixtures import make_event
from _system_context_fixtures import valid_doc
from event_schema import EVENT_TYPE_CONCERN


def open_concern_event(
    files=("scripts/x.py",), ts: str = "2026-04-05T09:00:00+00:00"
) -> dict:
    """An open (never-resolved) CONCERN event over ``files``.

    Shared builder for retro candidate-gate tests: a commit overlapping these
    files stays in the candidate-gated resolves_link_rate denominator.
    Assertion-free — callers assert on the computed rate.
    """
    return make_event(
        EVENT_TYPE_CONCERN, content="open concern", ts=ts, files=list(files)
    )


def write_system_context(smm_dir: Path, stage: int, **bs_extras: object) -> None:
    """Write a fully-valid system_context.json with the given branching stage.

    Extra ``branching_strategy`` fields (``integration_branch``,
    ``protected_branches``, ...) pass through ``bs_extras``. Single
    fixture for all stage/branching test shapes — replaces near-identical
    inline ``_write_stage_3_ctx`` / ``_write_branching_ctx`` helpers
    that drifted across test classes.

    Uses ``valid_doc`` so the doc passes schema validation on save. The
    earlier minimal shape (project_name + branching_strategy only) failed
    save validation, which ``_maybe_auto_promote``'s broad except silently
    swallowed — masking the real auto-promote behavior in every test.

    Note for stage=1 callers: the auto-promote will fire on the first
    ``get_branching_stage`` read, mutating this fixture to stage=2 and
    emitting one ``decision`` event with topic ``branching-stage-auto-promote``.
    Tests that assert on event-log contents must account for this; use
    ``stage=2`` directly when the test is not specifically exercising the
    auto-promote path.
    """
    doc = valid_doc(branching_strategy={"stage": stage, **bs_extras})
    (smm_dir / "system_context.json").write_text(json.dumps(doc))


def seed_sprint_with_stories(smm_dir: Path, stories: "list[tuple[str, str]]") -> None:
    """Write a minimal sprint.json from ``[(story_id, status), ...]`` pairs.

    Single-source-of-truth fixture — replaces three near-identical
    helpers (test_worktree.py, test_branching_cli_detection.py,
    test_story_close.py) that built the same sprint shape with slight
    naming drift (`_write_sprint` vs `_write_sprint_with_stories`).
    """
    story_dicts = [
        {
            "id": sid,
            "title": f"t-{sid}",
            "status": status,
            "dependencies": [],
            "milestone_ref": "",
            "design_sources": "",
            "context": "",
            "file_domain": [],
            "interface_contracts": [],
            "acceptance_criteria": [],
        }
        for sid, status in stories
    ]
    (smm_dir / "sprint.json").write_text(
        json.dumps(
            {
                "sprint_id": "sprint-001",
                "goal": "g",
                "started": "2026-05-04",
                "milestone": "",
                "stories": story_dicts,
            }
        )
    )


def write_sprint_json(
    smm_dir: Path, sprint_id: str, goal: str, started: str = "2026-04-22"
) -> None:
    """Write a minimal valid sprint.json with one ready story.

    Promoted here from a local helper in test_branching_sprint.py when
    test_branching_reslice.py was split out (story-005) and needed the same
    seed — one fixture beats two copies drifting apart.
    """
    sprint_store.save_sprint(
        smm_dir,
        {
            "sprint_id": sprint_id,
            "goal": goal,
            "started": started,
            "milestone": "test",
            "stories": [
                {
                    "id": "story-001",
                    "title": "Test",
                    "status": "ready",
                    "dependencies": [],
                    "milestone_ref": "test",
                    "design_sources": "test",
                    "context": "test",
                    "file_domain": [],
                    "interface_contracts": [],
                    "acceptance_criteria": ["test"],
                }
            ],
        },
    )


def seed_plan(smm_dir: Path, branch: str | None = None) -> None:
    """Write a minimal valid execution_plan.json. Optionally sets the branch field."""
    plan = {
        "title": "Test Plan",
        "sources": [],
        "overview": "ov",
        "milestones": [],
    }
    if branch is not None:
        plan["branch"] = branch
    execution_plan_store.save_plan(smm_dir, plan, enforce_budget=False)

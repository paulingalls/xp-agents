#!/usr/bin/env python3
"""Shared CLI test helpers: subprocess runner and plan/milestone factories.

Extracted from duplicated definitions across engine CLI test files.
Canonical import surface is via conftest.py.
"""

import os
import subprocess
import sys
from pathlib import Path

VALID_SOURCE = {
    "label": "Design doc",
    "location": "docs/design.md",
    "type": "repo",
    "content": None,
}

VALID_MILESTONE = {
    "number": 1,
    "name": "Foundation",
    "status": "planned",
    "delivered_sprint": None,
    "goal": "Build the foundation",
    "done": "Foundation is built and tested",
    "sources": "Design doc §Architecture",
    "change_zones": [{"path": "src/foo.py", "note": "new module"}],
    "impact_zones": [{"path": "src/bar.py", "note": "imports foo"}],
    "design_details": "Multi-paragraph details here.",
    "constraints": ["Python 3.10+"],
}


def run_cli(
    cli_path: Path,
    args: list[str],
    smm_dir: Path,
    stdin_data: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(cli_path), "--smm-dir", str(smm_dir), *args]
    env = {**os.environ, **extra_env} if extra_env is not None else None
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def make_plan_dict(**overrides) -> dict:
    plan = {
        "title": "Test Plan",
        "sources": [VALID_SOURCE.copy()],
        "overview": "Test overview.",
        "milestones": [VALID_MILESTONE.copy()],
    }
    plan.update(overrides)
    return plan


def make_milestone_dict(**overrides) -> dict:
    m = VALID_MILESTONE.copy()
    m.update(overrides)
    return m


VALID_SPRINT_STORY = {
    "id": "story-001",
    "title": "User registration",
    "status": "ready",
    "dependencies": [],
    "milestone_ref": "",
    "design_sources": "",
    "context": "Build user registration flow.",
    "file_domain": ["src/auth.py \u2014 new module"],
    "interface_contracts": [],
    "acceptance_criteria": [
        "Users can register",
        "E2E: registration flow",
    ],
}


def make_sprint_dict(**overrides) -> dict:
    plan = {
        "sprint_id": "sprint-001",
        "goal": "Build auth",
        "started": "2026-04-10",
        "milestone": "",
        "stories": [VALID_SPRINT_STORY.copy()],
    }
    plan.update(overrides)
    return plan


def make_story_dict(**overrides) -> dict:
    s = VALID_SPRINT_STORY.copy()
    s.update(overrides)
    return s

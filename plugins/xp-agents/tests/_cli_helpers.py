#!/usr/bin/env python3
"""Shared CLI test helpers: subprocess runner and plan/milestone factories.

Extracted from duplicated definitions across engine CLI test files.
Canonical import surface is via conftest.py.
"""

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
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(cli_path), "--smm-dir", str(smm_dir), *args]
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
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

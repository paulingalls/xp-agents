#!/usr/bin/env python3
"""Load/save for execution_plan.json.

Python API for execution plan operations. Internal scripts import
these functions directly. Shell scripts and skills use plan_cli.py
which wraps this module.

Follows the same pattern as smm_store.py: atomic writes, schema
validation on save, fail-loud on corrupt reads, symlink rejection.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from _acceptance_execution import render_acceptance_execution
from _append_impl import write_text_atomic
from execution_plan_schema import (
    PLAN_FILENAME,
    VALID_MILESTONE_STATUSES,
    validate_plan,
)

_MARKER_NAME = ".needs-execution-plan"


def plan_exists(smm_dir: Path) -> bool:
    """Check if execution_plan.json exists (not a symlink)."""
    path = smm_dir / PLAN_FILENAME
    return path.exists() and not path.is_symlink()


def load_plan(smm_dir: Path) -> dict | None:
    """Read the execution plan from disk.

    Returns:
        Parsed plan dict on success, or None if the file does
        not exist.

    Raises:
        ValueError: If the file exists but contains malformed
            JSON or fails schema validation.
        OSError: If the path is a symlink.
    """
    path = smm_dir / PLAN_FILENAME
    if path.is_symlink():
        raise OSError(f"Plan path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt plan file at {path}: {exc}") from exc

    errors = validate_plan(data, enforce_budget=False)
    if errors:
        raise ValueError(f"Schema-invalid plan at {path}: {'; '.join(errors)}")
    return data


def load_plan_required(smm_dir: Path) -> dict:
    """Load the execution plan or raise ValueError if missing.

    Use this at call sites where the plan MUST exist (tests with
    seeded fixtures, internal CLI subcommands). Pyright sees the
    `dict` return so callers don't need a follow-up
    `assert plan is not None`.
    """
    plan = load_plan(smm_dir)
    if plan is None:
        raise ValueError(f"No execution plan found at {smm_dir}")
    return plan


def save_plan(smm_dir: Path, data: dict, *, enforce_budget: bool = True) -> None:
    """Validate and atomically write the execution plan.

    Clears the NEEDS_EXECUTION_PLAN marker on success.

    Raises:
        ValueError: If the data fails schema validation.
        OSError: If the target path is a symlink.
    """
    path = smm_dir / PLAN_FILENAME
    if path.is_symlink():
        raise OSError(f"Plan path is a symlink: {path}")

    errors = validate_plan(data, enforce_budget=enforce_budget)
    if errors:
        raise ValueError(f"Plan validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))
    (smm_dir / _MARKER_NAME).unlink(missing_ok=True)


def update_milestone_status(
    smm_dir: Path,
    milestone_num: int,
    status: str,
    delivered_sprint: str | None = None,
) -> None:
    """Set a milestone's status (and optionally its delivered_sprint).

    delivered_sprint is required when status=='delivered' and cleared on
    any transition away from 'delivered'.

    Raises:
        ValueError: No plan exists, no milestone matches, 'delivered'
            status is missing delivered_sprint, or the new state fails
            schema validation on save.
        OSError: Plan path is a symlink.
    """
    if status == "delivered" and not delivered_sprint:
        raise ValueError("delivered_sprint required for delivered status")
    plan = load_plan(smm_dir)
    if plan is None:
        raise ValueError("No execution plan found")
    for milestone in plan["milestones"]:
        if milestone["number"] == milestone_num:
            milestone["status"] = status
            if status == "delivered":
                milestone["delivered_sprint"] = delivered_sprint
            elif milestone.get("delivered_sprint"):
                milestone["delivered_sprint"] = None
            save_plan(smm_dir, plan, enforce_budget=False)
            return
    raise ValueError(f"No milestone with number {milestone_num}")


def set_branch(smm_dir: Path, branch: str | None) -> None:
    """Set the plan's `branch` field (None clears it).

    Raises:
        ValueError: No plan exists, or the new state fails schema
            validation (invalid branch name).
        OSError: Plan path is a symlink.
    """
    plan = load_plan(smm_dir)
    if plan is None:
        raise ValueError("No execution plan found")
    plan["branch"] = branch
    save_plan(smm_dir, plan, enforce_budget=False)


_TERMINAL_STATUSES = frozenset({"delivered", "deferred"})
_ACTIVE_STATUSES = VALID_MILESTONE_STATUSES - _TERMINAL_STATUSES


def plan_is_complete(plan: dict) -> bool:
    """True when no milestone is still active (planned/in-progress).

    Pure helper on a loaded plan dict — caller handles plan-not-found.
    Deferred milestones are terminal (consciously dropped) and do not
    count as remaining work — same class as delivered for completion.
    """
    return not any(m["status"] in _ACTIVE_STATUSES for m in plan["milestones"])


def has_remaining_work(smm_dir: Path) -> bool:
    """True if the plan has planned or in-progress milestones.

    Returns False when no plan exists (callers treat absence as "nothing
    to do"). Distinct from is-plan-complete, which errors on no-plan.
    """
    plan = load_plan(smm_dir)
    return plan is not None and not plan_is_complete(plan)


def count_milestones(smm_dir: Path) -> dict[str, int]:
    """Count milestones by status. Returns one entry per VALID_MILESTONE_STATUSES."""
    counts = {status: 0 for status in VALID_MILESTONE_STATUSES}
    plan = load_plan(smm_dir)
    if plan is None:
        return counts
    for m in plan["milestones"]:
        status = m["status"]
        if status in counts:
            counts[status] += 1
    return counts


def archive(smm_dir: Path) -> Path | None:
    """Move execution_plan.json to plans/ with a timestamp.

    Returns the archived file path, or None if no plan exists.
    """
    src = smm_dir / PLAN_FILENAME
    plans_dir = smm_dir / "plans"
    plans_dir.mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = plans_dir / f"execution_plan_{ts}.json"
    try:
        shutil.move(str(src), str(dest))
    except FileNotFoundError:
        return None
    return dest


def render_markdown(plan: dict) -> str:
    """Render a plan dict as markdown for display."""
    lines: list[str] = []

    lines.append(f"# Execution Plan: {plan['title']}")
    lines.append("")

    if plan.get("branch"):
        lines.append(f"**Branch:** {plan['branch']}")
        lines.append("")

    # Sources table
    if plan["sources"]:
        lines.append("## Sources")
        lines.append("")
        lines.append("| Label | Location | Type |")
        lines.append("|-------|----------|------|")
        for src in plan["sources"]:
            lines.append(f"| {src['label']} | {src['location']} | {src['type']} |")
        lines.append("")

    # Overview
    lines.append("## Change Overview")
    lines.append("")
    lines.append(plan["overview"])
    lines.append("")

    # Milestones
    lines.append("## Milestones")
    lines.append("")

    for m in plan["milestones"]:
        status_tag = _format_status(m)
        lines.append(f"### Milestone {m['number']}: {m['name']} {status_tag}")
        lines.append(f"- **Goal:** {m['goal']}")
        lines.append(f"- **Definition of Done:** {m['done']}")
        lines.append(f"- **Sources:** {m['sources']}")
        lines.append("")

        _render_zones(lines, "Change Zones", m["change_zones"])
        _render_zones(lines, "Impact Zones", m["impact_zones"])

        lines.append("**Design Details:**")
        lines.append(m["design_details"])
        lines.append("")

        if m["constraints"]:
            lines.append("**Constraints:**")
            for c in m["constraints"]:
                lines.append(f"- {c}")
            lines.append("")

        ae = m.get("acceptance_execution")
        if ae:
            render_acceptance_execution(ae, lines)
            lines.append("")

    return "\n".join(lines)


def _format_status(milestone: dict) -> str:
    """Format the status tag for a milestone header."""
    if milestone["status"] == "delivered":
        sprint = milestone.get("delivered_sprint", "")
        return f"[delivered: {sprint}]"
    return f"[{milestone['status']}]"


def _render_zones(lines: list[str], heading: str, zones: list[dict]) -> None:
    """Render change/impact zones as a bullet list."""
    if not zones:
        return
    lines.append(f"**{heading}:**")
    for z in zones:
        note = z.get("note", "")
        if note:
            lines.append(f"- `{z['path']}` — {note}")
        else:
            lines.append(f"- `{z['path']}`")
    lines.append("")

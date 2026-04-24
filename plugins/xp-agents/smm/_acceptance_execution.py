#!/usr/bin/env python3
"""Shared acceptance_execution validation and rendering.

Used by both sprint_schema.py (story-level) and
execution_plan_schema.py (milestone-level).
"""


def validate_acceptance_execution(ae: object, prefix: str) -> list[str]:
    """Validate an acceptance_execution block.

    Returns a list of error strings — empty means valid.
    """
    errors: list[str] = []
    if not isinstance(ae, dict):
        errors.append(f"{prefix} must be an object")
        return errors
    if not isinstance(ae.get("type"), str):
        errors.append(f"{prefix}.type is required and must be a string")
    if not isinstance(ae.get("command"), str):
        errors.append(f"{prefix}.command is required and must be a string")
    if "setup" in ae and not isinstance(ae["setup"], str):
        errors.append(f"{prefix}.setup must be a string")
    if "notes" in ae and not isinstance(ae["notes"], str):
        errors.append(f"{prefix}.notes must be a string")
    return errors


def render_acceptance_execution(ae: dict, lines: list[str]) -> None:
    """Append acceptance_execution markdown to lines list."""
    lines.append("**Acceptance Execution:**")
    lines.append(f"- **Type:** {ae['type']}")
    lines.append(f"- **Command:** `{ae['command']}`")
    if ae.get("setup"):
        lines.append(f"- **Setup:** `{ae['setup']}`")
    if ae.get("notes"):
        lines.append(f"- **Notes:** {ae['notes']}")

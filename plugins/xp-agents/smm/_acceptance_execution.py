#!/usr/bin/env python3
"""Shared acceptance_execution validation and rendering.

Used by both sprint_schema.py (story-level) and
execution_plan_schema.py (milestone-level).

Two shapes are accepted (exactly one must be present):
- ``command: str`` — single command (back-compat).
- ``commands: list[str]`` — ordered list of commands; verify_acceptance.py
  runs them in order and stops at the first non-zero exit.
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

    has_command = "command" in ae
    has_commands = "commands" in ae
    if has_command and has_commands:
        errors.append(
            f"{prefix} must have exactly one of `command` or `commands`, not both"
        )
    elif not has_command and not has_commands:
        errors.append(f"{prefix} must have exactly one of `command` or `commands`")
    elif has_command and not isinstance(ae["command"], str):
        errors.append(f"{prefix}.command must be a string")
    elif has_commands:
        cmds = ae["commands"]
        if not isinstance(cmds, list):
            errors.append(f"{prefix}.commands must be a list of strings")
        elif not cmds:
            errors.append(f"{prefix}.commands must not be empty")
        else:
            for i, c in enumerate(cmds):
                if not isinstance(c, str):
                    errors.append(f"{prefix}.commands[{i}] must be a string")

    if "setup" in ae and not isinstance(ae["setup"], str):
        errors.append(f"{prefix}.setup must be a string")
    if "notes" in ae and not isinstance(ae["notes"], str):
        errors.append(f"{prefix}.notes must be a string")
    return errors


def extract_commands(ae: dict) -> list[str]:
    """Return the ordered list of commands for either schema shape.

    Single source of truth for the back-compat fan-out: callers iterate
    one list regardless of whether the story declares `command` or
    `commands`. Pre-condition: `ae` has already been validated.
    """
    if "commands" in ae:
        return list(ae["commands"])
    return [ae["command"]]


def render_acceptance_execution(ae: dict, lines: list[str]) -> None:
    """Append acceptance_execution markdown to lines list."""
    lines.append("**Acceptance Execution:**")
    lines.append(f"- **Type:** {ae['type']}")
    cmds = extract_commands(ae)
    if "commands" in ae:
        lines.append("- **Commands:**")
        for i, c in enumerate(cmds, 1):
            lines.append(f"  {i}. `{c}`")
    else:
        lines.append(f"- **Command:** `{cmds[0]}`")
    if ae.get("setup"):
        lines.append(f"- **Setup:** `{ae['setup']}`")
    if ae.get("notes"):
        lines.append(f"- **Notes:** {ae['notes']}")

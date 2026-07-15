#!/usr/bin/env python3
"""Shared acceptance_execution validation and rendering.

Used by both sprint_schema.py (story-level) and
execution_plan_schema.py (milestone-level), plus the per-AC verify
validator for sprint acceptance_criteria items.

The command/commands verify block takes two shapes:
- ``command: str`` — single command (back-compat).
- ``commands: list[str]`` — ordered list of commands; verify_acceptance.py
  runs them in order and stops at the first non-zero exit.

The story/milestone acceptance_execution block requires exactly one of
them; a per-AC verify object may carry neither (a structured manual
check).
"""


def _validate_command_block(
    block: dict, prefix: str, *, require_one: bool
) -> list[str]:
    """Validate the `command` xor `commands` (+ setup/notes) of a block.

    Shared by the story-level acceptance_execution validator (require_one=
    True) and the per-AC verify validator (require_one=False, where an
    object AC may carry only a description). Does not check `type` — that
    requirement is story-level only.
    """
    errors: list[str] = []
    has_command = "command" in block
    has_commands = "commands" in block
    if has_command and has_commands:
        errors.append(
            f"{prefix} must have exactly one of `command` or `commands`, not both"
        )
    elif not has_command and not has_commands:
        if require_one:
            errors.append(f"{prefix} must have exactly one of `command` or `commands`")
    elif has_command and not isinstance(block["command"], str):
        errors.append(f"{prefix}.command must be a string")
    elif has_commands:
        cmds = block["commands"]
        if not isinstance(cmds, list):
            errors.append(f"{prefix}.commands must be a list of strings")
        elif not cmds:
            errors.append(f"{prefix}.commands must not be empty")
        else:
            for i, c in enumerate(cmds):
                if not isinstance(c, str):
                    errors.append(f"{prefix}.commands[{i}] must be a string")

    if "setup" in block and not isinstance(block["setup"], str):
        errors.append(f"{prefix}.setup must be a string")
    if "notes" in block and not isinstance(block["notes"], str):
        errors.append(f"{prefix}.notes must be a string")
    return errors


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

    errors.extend(_validate_command_block(ae, prefix, require_one=True))
    if "pins" in ae:
        pins = ae["pins"]
        if not isinstance(pins, list):
            errors.append(f"{prefix}.pins must be a list of strings")
        else:
            for i, p in enumerate(pins):
                if not isinstance(p, str):
                    errors.append(f"{prefix}.pins[{i}] must be a string")
    return errors


def validate_per_ac_verify(
    item: object, prefix: str, *, valid_surfaces: frozenset[str] | None = None
) -> list[str]:
    """Validate a single acceptance_criteria item.

    An item is either a bare ``str`` (a manual AC) or an object with a
    required ``description`` (str), an optional ``surface`` (str), and an
    optional ``command`` xor ``commands`` verify block reusing the
    story-level shape (minus the required ``type``). An object carrying
    only a description is a structured manual check.

    When ``valid_surfaces`` is supplied, an object's ``surface`` must be one
    of those names (FK to acceptance_surfaces). ``None`` keeps the FK
    shape-only — enforcement is the caller's choice, mirroring the
    milestone.surfaces_touched FK in execution_plan_schema.
    """
    if isinstance(item, str):
        return []
    if not isinstance(item, dict):
        return [f"{prefix} must be a string or an object"]

    errors: list[str] = []
    if not isinstance(item.get("description"), str):
        errors.append(f"{prefix}.description is required and must be a string")
    surface = item.get("surface")
    if "surface" in item and not isinstance(surface, str):
        errors.append(f"{prefix}.surface must be a string")
    elif (
        isinstance(surface, str)
        and valid_surfaces is not None
        and surface not in valid_surfaces
    ):
        errors.append(f"{prefix}.surface references unknown surface {surface!r}")
    errors.extend(_validate_command_block(item, prefix, require_one=False))
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

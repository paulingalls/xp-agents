#!/usr/bin/env python3
"""Shared acceptance_execution validation and rendering.

Used by both sprint_schema.py (story-level) and
execution_plan_schema.py (milestone-level), plus the per-AC verify
validator for sprint acceptance_criteria items.

The command/commands verify block takes two shapes:
- ``command: str`` — single command (back-compat).
- ``commands: list[str]`` — ordered list of commands; verify_acceptance.py
  runs them in order and stops at the first non-zero exit.

The story/milestone acceptance_execution block requires exactly one of them
for every ``type`` EXCEPT ``manual``: a manual check is verified by human/agent
judgment, so its command block is optional. Human/agent steps live in an
optional ``steps: list[str]`` (distinct from runnable ``commands``). A per-AC
verify object may carry neither command block (a structured manual check).

Two layers, and they say different things — do not collapse them:

AUTHORING (``enforce_manual_shape=True``) forbids ``command``/``commands`` on a
manual block outright. Prose then has exactly one home, ``steps``, so it can
never land in a field that gets shelled. This reverses an earlier rule that a
manual block MAY carry a runnable confirmation: an operator declared
observational prose in a manual ``command``, the runner shelled it, ``/bin/sh``
exited 127, and the close gate reported a plain red the operator could not make
green. Off by default, so read paths keep loading what is already stored.

Both write paths ask for it — story-level (sprint_schema) and milestone-level
(execution_plan_schema) — each behind its own per-item grandfather (see
_manual_shape_exemption). validate_sprint/validate_plan walk every story/
milestone on the read path too, so an ungrandfathered rule would make an
already-stored document unloadable.

RUN-TIME is UNCHANGED. Gate on command PRESENCE, not on ``type``: whatever runs
a command runs it regardless of type, and a manual block with no command is N/A.
A grandfathered manual+command block already on disk therefore still runs
exactly as before — the authoring rule narrows what can be written, not what a
written block does.
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
    if "steps" in block:
        steps = block["steps"]
        if not isinstance(steps, list):
            errors.append(f"{prefix}.steps must be a list of strings")
        else:
            for i, s in enumerate(steps):
                if not isinstance(s, str):
                    errors.append(f"{prefix}.steps[{i}] must be a string")
    return errors


def validate_acceptance_execution(
    ae: object,
    prefix: str,
    *,
    allow_pins: bool = True,
    enforce_manual_shape: bool = False,
) -> list[str]:
    """Validate an acceptance_execution block.

    ``enforce_manual_shape`` turns on the authoring-time rule that a manual
    block may not carry ``command``/``commands`` (see the module docstring).
    It defaults to False so read paths keep loading stored blocks. Both the
    story-level caller (sprint_schema.py) and the milestone-level caller
    (execution_plan_schema.py) turn it on at their write path, each behind
    its own per-item grandfather.

    ``allow_pins`` gates the optional ``pins`` field. It defaults to True
    for the story-level caller (sprint_schema.py), the only scope
    ``pins`` is ever consumed at: scripts/verify_paths.extract_verify_paths
    is only ever called with a story dict (close_verify_gate.py,
    verify_deferred.py) — no milestone-scoped verify gate reads it.
    execution_plan_schema.py (milestone-level) passes allow_pins=False so a
    milestone-level `pins` fails validation loudly instead of silently
    doing nothing.

    Returns a list of error strings — empty means valid.
    """
    errors: list[str] = []
    if not isinstance(ae, dict):
        errors.append(f"{prefix} must be an object")
        return errors
    if not isinstance(ae.get("type"), str):
        errors.append(f"{prefix}.type is required and must be a string")

    # The command block is optional for a manual check (its verification is
    # human/agent judgment); every other type must still carry exactly one of
    # command xor commands. Whether a manual block MAY carry one is the
    # enforce_manual_shape question below, not this one.
    is_manual = ae.get("type") == "manual"
    require_one = not is_manual
    errors.extend(_validate_command_block(ae, prefix, require_one=require_one))

    if enforce_manual_shape and is_manual:
        present = [key for key in ("command", "commands") if key in ae]
        if present:
            errors.append(
                f"{prefix}.{present[0]} is not allowed when type is `manual` — "
                "a manual check is human/agent judgment, and anything declared "
                "here is shelled by the acceptance runner; move the prose to "
                f"{prefix}.steps"
            )
    if "pins" in ae:
        if not allow_pins:
            errors.append(
                f"{prefix}.pins is story-scoped (a verify-gate exemption "
                "consumed only at story close) and is not valid on a "
                "milestone; move it to the story's acceptance_execution"
            )
        else:
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
    # A manual block may carry no command (extract_commands would KeyError);
    # render Command/Commands only when a runnable block is present.
    if "command" in ae or "commands" in ae:
        cmds = extract_commands(ae)
        if "commands" in ae:
            lines.append("- **Commands:**")
            for i, c in enumerate(cmds, 1):
                lines.append(f"  {i}. `{c}`")
        else:
            lines.append(f"- **Command:** `{cmds[0]}`")
    if ae.get("steps"):
        lines.append("- **Steps:**")
        for i, s in enumerate(ae["steps"], 1):
            lines.append(f"  {i}. {s}")
    if ae.get("setup"):
        lines.append(f"- **Setup:** `{ae['setup']}`")
    if ae.get("notes"):
        lines.append(f"- **Notes:** {ae['notes']}")

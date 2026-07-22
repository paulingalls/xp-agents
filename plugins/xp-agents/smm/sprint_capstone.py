#!/usr/bin/env python3
"""Capstone story builder — pure, no I/O.

Split out of sprint_store.py for the file-size cap: this is one cohesive
question (what does a milestone's final, cross-cutting story look like), it
touches no disk, and it is the only part of the store that CONSTRUCTS a
story rather than reading or mutating one. `sprint_store` re-exports
`build_capstone_story` so the historical import path keeps working.
"""

_HARNESS_PLACEHOLDER = "<implementer fills: test harness>"
_COMMAND_PLACEHOLDER = "<implementer fills: cross-cutting test invocation>"
_MANUAL_TYPE = "manual"


def _acceptance_execution_placeholder(harness: str | None) -> dict:
    """The capstone's acceptance_execution placeholder for a resolved harness.

    A `manual` harness gets its placeholder in ``steps``, not ``command``:
    authoring forbids command/commands on a manual block (see
    _acceptance_execution), so a command here would make the builder emit a
    story `add-story` refuses — a refusal the operator cannot fix, because
    the plugin wrote the block. Every other harness keeps the runnable
    ``command`` placeholder.
    """
    if harness == _MANUAL_TYPE:
        return {
            "type": _MANUAL_TYPE,
            "steps": [_COMMAND_PLACEHOLDER],
            "notes": "Placeholder — fill with the real cross-cutting check steps.",
        }
    return {
        "type": harness or _HARNESS_PLACEHOLDER,
        "command": _COMMAND_PLACEHOLDER,
        "notes": "Placeholder — fill with the real cross-cutting test command.",
    }


def build_capstone_story(
    story_id: str,
    milestone_name: str,
    touched_surfaces: list[str],
    depends_on: list[str],
    *,
    milestone_ref: str = "",
    harness: str | None = None,
) -> dict:
    """Return a schema-valid capstone story dict for a milestone.

    The capstone is the final story: it depends on every sibling and
    proves the milestone's surfaces compose end to end. Each touched
    surface becomes one behavior-shaped object AC (`{description,
    surface}`); a cross-surface ``E2E:`` AC heads the list. The
    ``acceptance_execution`` block is a non-empty placeholder the
    implementer replaces with the real cross-cutting invocation when the
    capstone's own story is built. Pure: the caller appends the result
    to the stories list and persists via ``save_sprint``.

    ``harness`` is the resolved ``acceptance_execution.type``. It is
    never guessed here — callers resolve it (e.g. from the project's
    declared acceptance surfaces) and pass it in, or pass ``None`` when
    no harness could be resolved. ``None`` yields a schema-valid
    placeholder type rather than an omitted field, so the capstone stays
    in the acceptance roll-up until an implementer fills it in.
    """
    acceptance_criteria: list[str | dict] = [
        f"E2E: Given the {milestone_name} stories ship, When the cross-cutting "
        f"acceptance test exercises every touched surface, Then all report green"
    ]
    for surface in touched_surfaces:
        acceptance_criteria.append(
            {
                "description": (
                    f"Given the {milestone_name} stories ship, When the {surface} "
                    f"acceptance suite runs, Then it passes"
                ),
                "surface": surface,
            }
        )

    return {
        "id": story_id,
        "title": f"Capstone: {milestone_name}",
        "status": "ready",
        "dependencies": list(depends_on),
        "milestone_ref": milestone_ref,
        "design_sources": "",
        "context": (
            f"Capstone for {milestone_name}: cross-cutting acceptance test "
            f"proving the milestone's surfaces compose end to end."
        ),
        "file_domain": [
            "<implementer fills: cross-cutting acceptance test path>",
        ],
        "interface_contracts": [],
        "acceptance_criteria": acceptance_criteria,
        "acceptance_execution": _acceptance_execution_placeholder(harness),
    }

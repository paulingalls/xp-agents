#!/usr/bin/env python3
"""Schema constants and validator for retrospective K/F/T data.

Single source of truth for what constitutes a valid retrospective.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as event_schema.py and smm_schema.py.
"""

KEEP_CONTENT_MAX = 250
FIX_CONTENT_MAX = 300
TRY_CONTENT_MAX = 300
TRY_MAX_ITEMS = 4
ANALYSIS_NOTES_MAX = 600

_SECTION_BUDGETS = {
    "keep": KEEP_CONTENT_MAX,
    "fix": FIX_CONTENT_MAX,
    "try": TRY_CONTENT_MAX,
}


def validate_retro(data: dict) -> list[str]:
    """Validate a retrospective K/F/T structure.

    Returns a list of error strings — empty list means valid.
    """
    errors: list[str] = []

    for section, budget in _SECTION_BUDGETS.items():
        items = data.get(section, [])
        if not isinstance(items, list):
            errors.append(f"{section} must be an array")
            continue
        if section == "try" and len(items) > TRY_MAX_ITEMS:
            errors.append(f"try has {len(items)} items, max {TRY_MAX_ITEMS}")
        for idx, item in enumerate(items):
            if not isinstance(item, (dict, str)):
                errors.append(f"{section}[{idx}] must be a dict or string")
                continue
            content = item.get("content", "") if isinstance(item, dict) else item
            if isinstance(content, str) and len(content) > budget:
                errors.append(
                    f"{section}[{idx}] content exceeds budget"
                    f" ({len(content)} > {budget} chars)"
                )

    notes = data.get("analysis_notes")
    if isinstance(notes, str) and len(notes) > ANALYSIS_NOTES_MAX:
        errors.append(
            f"analysis_notes exceeds budget ({len(notes)} > {ANALYSIS_NOTES_MAX} chars)"
        )

    return errors

#!/usr/bin/env python3
"""Prompt nugget: prioritized delta injection at UserPromptSubmit.

Reads NEW signal events since last injection (watermark) and surfaces
the top 3 by priority (concerns > questions > assumptions > discoveries
> debt > decisions). ~100 tokens max. No output when nothing is new.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import read_delta
import resolution

# Signal types worth surfacing, in priority order — higher priority is
# more likely to affect the agent's current work.
_NUGGET_PRIORITY = {
    _common.CONCERN: 0,
    _common.QUESTION: 1,
    _common.ASSUMPTION: 2,
    _common.DISCOVERY: 3,
    _common.DEBT: 4,
    _common.DECISION: 5,
}

_MAX_NUGGETS = 3
_WATERMARK_ID = "prompt-nugget"

# Concern patterns already visible in tool output — filter from nuggets.
_NOISY_CONCERN_PREFIXES = (
    concerns.TEST_COMMAND_FAILED_PREFIX,
    concerns.TEST_FAILURES_PREFIX,
    concerns.LINT_CONCERN_PREFIX,
    concerns.LINT_RESOLVED_PREFIX,
)


_NUGGET_CONTENT_MAX = 120


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return additionalContext nugget, or None if nothing new since last injection."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    try:
        # Locked single-read: full events for resolution chain completeness
        # (chains span the watermark), new_events slice for the nugget signals.
        # Watermark advance uses the same total_lines snapshot returned by
        # read_events_from under shared flock — closes the read/advance gap.
        # Documented exception to _common.read_events_locked: both tuple
        # elements are needed and the watermark must advance.
        events, new_events = read_delta.read_delta_full(smm_dir, _WATERMARK_ID)
        resolved = resolution.compute_resolutions(events)
    except Exception:
        return None

    resolved_ids = resolution.collect_all_resolved_ids(resolved)

    signals = [
        e
        for e in new_events
        if e.get("type") in _NUGGET_PRIORITY
        and e.get("id") not in resolved_ids
        and not (
            e.get("type") == _common.CONCERN
            and e.get("content", "").startswith(_NOISY_CONCERN_PREFIXES)
        )
    ]
    if not signals:
        return None

    # read_delta returns events in chronological order; reverse so most-recent
    # comes first within each priority group after the stable sort by type.
    signals.reverse()
    signals.sort(key=lambda e: _NUGGET_PRIORITY.get(e.get("type", ""), 99))

    lines = []
    for e in signals[:_MAX_NUGGETS]:
        etype = e.get("type", "")
        content = _common.truncate(e.get("content", ""), _NUGGET_CONTENT_MAX)
        lines.append(f"- [{etype}] {content}")

    return "New since last prompt:\n" + "\n".join(lines)


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    nugget = run(input_data)
    if nugget:
        _common.hook_output("UserPromptSubmit", nugget)
    sys.exit(0)

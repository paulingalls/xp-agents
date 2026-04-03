#!/usr/bin/env python3
"""Prompt nugget: prioritized delta injection at UserPromptSubmit time.

Uses watermark-based read_delta to show only NEW signal events since
the last injection. Picks the top 3 by priority (concerns > questions >
assumptions > discoveries > debt > decisions). ~100 tokens max.
If nothing new, no injection (exit 0 with no output).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import read_delta
from resolution import compute_resolutions

# Signal types worth surfacing, in priority order.
# Higher priority = more likely to affect the agent's current work.
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


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Build a prompt nugget from new events since last injection.

    Returns nugget string for additionalContext, or None if nothing new.
    """
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    try:
        new_events = read_delta.read_delta(
            smm_dir,
            _WATERMARK_ID,
        )
    except Exception:
        return None

    # Filter out resolved concerns/debt/decisions — read full history
    # to catch resolutions from earlier delta windows
    all_events = _common.read_events_raw(smm_dir)
    resolved = compute_resolutions(all_events)
    resolved_ids = (
        resolved.get("resolved_concern_ids", set())
        | resolved.get("resolved_debt_ids", set())
        | resolved.get("resolved_decision_ids", set())
        | resolved.get("resolved_goal_ids", set())
        | resolved.get("resolved_assumption_ids", set())
        | resolved.get("answered_question_ids", set())
    )

    signals = [
        e
        for e in new_events
        if e.get("type") in _NUGGET_PRIORITY and e.get("id") not in resolved_ids
    ]
    if not signals:
        return None

    # Sort by priority (type), then by recency (position in list = chronological).
    # For events of the same type, most recent comes last in the original list,
    # so we reverse to get most recent first, then stable-sort by priority.
    signals.reverse()
    signals.sort(key=lambda e: _NUGGET_PRIORITY.get(e.get("type", ""), 99))

    lines = []
    for e in signals[:_MAX_NUGGETS]:
        etype = e.get("type", "")
        content = _truncate(e.get("content", ""))
        lines.append(f"- [{etype}] {content}")

    return "New since last prompt:\n" + "\n".join(lines)


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    nugget = run(input_data)
    if nugget:
        _common.hook_output("UserPromptSubmit", nugget)
    sys.exit(0)

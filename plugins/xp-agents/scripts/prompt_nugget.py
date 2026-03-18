#!/usr/bin/env python3
"""Prompt nugget: tiny delta injection at UserPromptSubmit time.

Uses watermark-based read_delta to show only NEW signal events since
the last injection. Produces ~20-50 tokens max. If nothing new, no
injection (exit 0 with no output).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import read_delta

# Signal types worth surfacing in the nugget
_NUGGET_TYPES = frozenset(
    {
        _common.CONCERN,
        _common.DECISION,
        _common.GOAL,
        _common.DEBT,
        _common.QUESTION,
    }
)

_WATERMARK_ID = "prompt-nugget"


def _truncate(text: str, max_len: int = 60) -> str:
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
            tier=read_delta.TIER_FULL,
        )
    except Exception:
        return None

    signals = [e for e in new_events if e.get("type") in _NUGGET_TYPES]
    if not signals:
        return None

    lines = []
    for e in signals[-5:]:  # cap at 5 most recent
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

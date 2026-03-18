#!/usr/bin/env python3
"""Prompt nugget: lightweight context injection at UserPromptSubmit time.

Reads SHARED_MENTAL_MODEL.md to extract Intent and Risks sections.
Injects a brief reminder (~50-80 tokens) via additionalContext.
If nothing is open, returns None (no injection).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common


def _parse_smm_section(text: str, heading: str) -> list[str]:
    """Extract bullet items from a markdown section."""
    pattern = rf"^## {re.escape(heading)}\s*\n((?:- .+\n?)*)"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return []
    return [
        line.lstrip("- ").strip()
        for line in match.group(1).strip().splitlines()
        if line.startswith("- ")
    ]


def _truncate(text: str, max_len: int = 80) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Build a prompt nugget from the materialized SMM.

    Returns nugget string for additionalContext, or None if nothing open.
    """
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
    if not smm_file.exists():
        return None

    try:
        smm_text = smm_file.read_text(encoding="utf-8")
    except OSError:
        return None

    intents = _parse_smm_section(smm_text, "Intent")
    risks = _parse_smm_section(smm_text, "Risks")

    if not intents and not risks:
        return None

    lines = ["Session checkpoint:"]

    if intents:
        summaries = [_truncate(s) for s in intents[:5]]
        quoted = ", ".join(f'"{s}"' for s in summaries)
        lines.append(f"- {len(intents)} intent(s): {quoted}")

    if risks:
        summaries = [_truncate(s) for s in risks[:5]]
        quoted = ", ".join(f'"{s}"' for s in summaries)
        lines.append(f"- {len(risks)} risk(s): {quoted}")

    return "\n".join(lines)


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    nugget = run(input_data)
    if nugget:
        _common.hook_output("UserPromptSubmit", nugget)
    sys.exit(0)

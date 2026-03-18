#!/usr/bin/env python3
"""Stop nugget: lightweight session checkpoint at Stop time.

Reads prepare_curation_data() to extract open intents and unresolved
risks. Injects a brief reminder (~50-80 tokens) via additionalContext.
If nothing is open, returns None (no injection).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import materialize


def _truncate(text: str, max_len: int = 80) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Build a stop nugget from current SMM state.

    Returns nugget string for additionalContext, or None if nothing open.
    """
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    data = materialize.prepare_curation_data(smm_dir)
    current = data.get("current_smm", {})

    intents = current.get("intent", [])
    risks = current.get("risks", [])

    if not intents and not risks:
        return None

    lines = ["Session checkpoint:"]

    if intents:
        summaries = [_truncate(i.get("content", "")) for i in intents[:5]]
        quoted = ", ".join(f'"{s}"' for s in summaries)
        lines.append(f"- {len(intents)} intent(s): {quoted}")

    if risks:
        summaries = [_truncate(r.get("content", "")) for r in risks[:5]]
        quoted = ", ".join(f'"{s}"' for s in summaries)
        lines.append(f"- {len(risks)} risk(s): {quoted}")

    return "\n".join(lines)


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    nugget = run(input_data)
    if nugget:
        _common.hook_output("Stop", nugget)
    sys.exit(0)

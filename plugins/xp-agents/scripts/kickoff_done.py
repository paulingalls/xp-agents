#!/usr/bin/env python3
"""PostToolUse:Skill hook: inject behavioral guide after kickoff.

When /xp-housekeeping completes (the final step of kickoff),
injects BEHAVIORAL_GUIDE.md as additionalContext. The curated SMM is
already in context — housekeeping reads and writes the file directly.
"""

import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common


@functools.lru_cache(maxsize=1)
def _load_behavioral_guide() -> str:
    """Load BEHAVIORAL_GUIDE.md from plugin root."""
    try:
        plugin_root = _common.resolve_plugin_root()
        guide_path = plugin_root / "BEHAVIORAL_GUIDE.md"
        if guide_path.is_file():
            return guide_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        pass
    return ""


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Inject SMM + behavioral guide after xp-kickoff completes."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    if skill_name != "xp-housekeeping":
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Clean up kickoff marker
    (smm_dir / ".needs-kickoff").unlink(missing_ok=True)

    # Inject behavioral guide only — the agent already has the SMM
    # from housekeeping step 8 (Read the file it just wrote).
    guide = _load_behavioral_guide()
    return guide if guide else None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)

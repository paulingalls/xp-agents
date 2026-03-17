#!/usr/bin/env python3
"""PostToolUse:Skill hook: inject SMM + behavioral guide after session review.

When /xp-session-review completes, materializes the SMM and injects
it along with BEHAVIORAL_GUIDE.md as additionalContext. This ensures
the main agent has the fresh SMM and behavioral guide deterministically
loaded together, in order.
"""

import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import materialize


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
    """Inject SMM + behavioral guide after xp-session-review completes."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    if skill_name != "xp-session-review":
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Materialize fresh SMM
    md = materialize.materialize(smm_dir)

    # Clean up session review marker
    (smm_dir / ".needs-session-review").unlink(missing_ok=True)

    # Build context: SMM first, then behavioral guide
    parts: list[str] = []
    if md:
        parts.append(_common.wrap_smm_context(md))

    guide = _load_behavioral_guide()
    if guide:
        parts.append(guide)

    return "\n\n".join(parts) if parts else None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)

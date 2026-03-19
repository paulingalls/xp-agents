#!/usr/bin/env python3
"""SubagentStart hook: inject project context for subagents.

Tiered injection based on agent type:
- Explore: Intent + Constraints pillars only (~200 tokens)
- Plan/general-purpose/background: Full SMM + behavioral guide (~1000 tokens)
- xp-* agents: skipped (use own preloads)
"""

import functools
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common

# ---------------------------------------------------------------------------
# Behavioral guide loader (shared pattern with kickoff_done.py)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# SMM section extraction for Explore agents
# ---------------------------------------------------------------------------

_PILLAR_RE = re.compile(r"^## (Intent|Constraints|Risks|Wisdom)\s*$", re.MULTILINE)


def _extract_pillars(smm_content: str, pillars: set[str]) -> str:
    """Extract specific pillar sections from the curated SMM."""
    matches = list(_PILLAR_RE.finditer(smm_content))
    if not matches:
        return ""

    parts: list[str] = []
    for i, m in enumerate(matches):
        if m.group(1) in pillars:
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(smm_content)
            parts.append(smm_content[start:end].rstrip())

    if not parts:
        return ""
    return "# Shared Mental Model\n\n" + "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core subagent_start logic. Returns additionalContext string or None."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    # Resolve SMM dir
    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "subagent")
    agent_type = input_data.get("agent_type", "")

    # Read curated four-pillar SMM from disk (written by housekeeping)
    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
    try:
        smm_content = smm_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        smm_content = ""

    # Record start event (pairs with "completed" in SubagentStop)
    start_event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_started_content(agent_id),
        working_on=[],
    )
    _common.append_safe(smm_dir, start_event)

    # Tiered injection based on agent type
    parts: list[str] = []

    if agent_type == "Explore":
        # Explore is read-only — only needs Intent + Constraints for alignment
        if smm_content:
            extracted = _extract_pillars(smm_content, {"Intent", "Constraints"})
            if extracted:
                parts.append(_common.wrap_smm_context(extracted))
    else:
        # Plan, general-purpose, background — full SMM + behavioral guide
        if smm_content:
            parts.append(_common.wrap_smm_context(smm_content))
        guide = _load_behavioral_guide()
        if guide:
            parts.append(guide)

    if not parts:
        return None
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        _common.hook_output("SubagentStart", context)
    sys.exit(0)

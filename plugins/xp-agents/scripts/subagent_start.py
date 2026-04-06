#!/usr/bin/env python3
"""SubagentStart hook: inject project context for subagents.

Tiered injection via dispatch table (M10) + teammate detection (M14):
- Explore: Intent + Constraints pillars only (~200 tokens)
- xp-plan-reviewer / xp-retrospective: Full SMM + XP values + sprint.md
- Teammate (custom agent_type): SMM + XP values + teammate guide
- Default (Plan/general-purpose/background): Full SMM + XP values
- Other xp-* agents: skipped (use own preloads)

Note: The is_xp_agent() early return used in other hooks is replaced here
by the dispatch table. xp-* agents not in _DISPATCH return None. Do NOT
copy this pattern to other hooks — they still need the universal guard.
"""

import re
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import sprint_state

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
# Injection functions (one per tier)
# ---------------------------------------------------------------------------


def _inject_explore(smm: str, smm_dir: Path, input_data: dict) -> list[str]:
    """Explore: Intent + Constraints only, no guide."""
    if not smm:
        return []
    extracted = _extract_pillars(smm, {"Intent", "Constraints"})
    return [_common.wrap_smm_context(extracted)] if extracted else []


def _inject_full(smm: str, smm_dir: Path, input_data: dict) -> list[str]:
    """Default: full SMM + XP values (no process guide)."""
    parts: list[str] = []
    if smm:
        parts.append(_common.wrap_smm_context(smm))
    values = _common.load_xp_values()
    if values:
        parts.append(values)
    return parts


def _inject_with_sprint(smm: str, smm_dir: Path, input_data: dict) -> list[str]:
    """Plan reviewer / retrospective: full SMM + sprint.md."""
    parts = _inject_full(smm, smm_dir, input_data)
    sprint_content = sprint_state.read_sprint_content(smm_dir)
    if sprint_content:
        parts.append(sprint_content)
    return parts


def _inject_teammate(smm: str, smm_dir: Path, input_data: dict) -> list[str]:
    """Teammate: SMM + XP values + teammate guide. Stories via spawn prompt."""
    # Register in coordination immediately — closes race window before first file write
    agent_id = input_data.get("agent_id", "")
    if agent_id and smm_dir:
        coordination.update_coordination(smm_dir, agent_id, [])
    parts: list[str] = []
    if smm:
        parts.append(_common.wrap_smm_context(smm))
    values = _common.load_xp_values()
    if values:
        parts.append(values)
    guide = _common.load_teammate_guide()
    if guide:
        parts.append(guide)
    return parts


# ---------------------------------------------------------------------------
# Teammate detection
# ---------------------------------------------------------------------------

_BUILTIN_TYPES = frozenset({"Explore", "Plan", "general-purpose", "Bash"})


def is_teammate_by_agent_type(input_data: dict) -> bool:
    """Detect teammates by agent_type exclusion.

    Teammates are custom agent types — not built-in types (Explore, Plan,
    general-purpose, Bash) and not xp-* plugin agents.
    """
    agent_type = input_data.get("agent_type", "")
    if not agent_type:
        return False
    if agent_type in _BUILTIN_TYPES:
        return False
    return not agent_type.startswith("xp-")


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Callable[..., list[str]]] = {
    "Explore": _inject_explore,
    "xp-spawn-team": _inject_with_sprint,
    "xp-sprint-reviewer": _inject_with_sprint,
    "xp-sprint-retro": _inject_with_sprint,
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core subagent_start logic. Returns additionalContext or None."""
    agent_type = input_data.get("agent_type", "")

    # Dispatch: known types use their tier, unknown xp-* agents skip
    injector = _DISPATCH.get(agent_type)
    if injector is None:
        if agent_type.startswith("xp-"):
            return None
        # Detect teammates by agent_type, fall back to default
        is_teammate = is_teammate_by_agent_type(input_data)
        injector = _inject_teammate if is_teammate else _inject_full

    # Resolve SMM dir
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "subagent")

    # Read curated four-pillar SMM from disk
    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
    try:
        smm_content = smm_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        smm_content = ""

    # Record start event
    start_event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_started_content(agent_id),
        working_on=[],
    )
    _common.append_safe(smm_dir, start_event)

    # Run the selected injector
    parts = injector(smm_content, smm_dir, input_data)

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

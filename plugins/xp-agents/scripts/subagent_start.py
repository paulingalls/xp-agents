#!/usr/bin/env python3
"""SubagentStart hook: inject project context for subagents.

Tiered injection via dispatch table + teammate detection:
- Explore: Intent + Constraints pillars (~200 tokens)
- Teammate (custom agent_type): SMM + teammate guide
- Default (Plan/general-purpose/background): Full SMM
- xp-* forked agents: values only (data comes from preloads)

XP values (~250 tokens) are injected universally for ALL subagents,
appended after tier-specific context.
"""

import re
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination

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
    """Explore: Intent + Constraints only."""
    if not smm:
        return []
    extracted = _extract_pillars(smm, {"Intent", "Constraints"})
    return [_common.wrap_smm_context(extracted)] if extracted else []


def _inject_full(smm: str, smm_dir: Path, input_data: dict) -> list[str]:
    """Default: full SMM (no process guide)."""
    parts: list[str] = []
    if smm:
        parts.append(_common.wrap_smm_context(smm))
    return parts


def _inject_teammate(smm: str, smm_dir: Path, input_data: dict) -> list[str]:
    """Teammate: SMM + teammate guide. Stories via spawn prompt."""
    # Register in coordination immediately — closes race window before first file write
    agent_id = input_data.get("agent_id", "")
    if agent_id and smm_dir:
        coordination.update_coordination(smm_dir, agent_id, [])
    parts: list[str] = []
    if smm:
        parts.append(_common.wrap_smm_context(smm))
    guide = _common.load_teammate_guide()
    if guide:
        parts.append(guide)
    return parts


def _inject_xp_agent(smm: str, smm_dir: Path, input_data: dict) -> list[str]:
    """xp-* forked agents: values only (data comes from preloads)."""
    return []


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
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core subagent_start logic. Returns additionalContext or None."""
    agent_type = input_data.get("agent_type", "")

    # Dispatch: known types use their tier
    injector = _DISPATCH.get(agent_type)
    if injector is None:
        if agent_type.startswith("xp-"):
            injector = _inject_xp_agent
        else:
            # Detect teammates by agent_type, fall back to default
            is_teammate = is_teammate_by_agent_type(input_data)
            injector = _inject_teammate if is_teammate else _inject_full

    # Resolve SMM dir
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        # Even without SMM, inject values for all subagents
        values = _common.load_xp_values()
        return values if values else None

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

    # Run the selected injector (tier-specific context)
    parts = injector(smm_content, smm_dir, input_data)

    # Universal: XP values injected for ALL subagents
    values = _common.load_xp_values()
    if values:
        parts.append(values)

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

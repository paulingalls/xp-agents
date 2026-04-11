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

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import smm_cli


def _inject_explore(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Explore: Intent + Constraints only."""
    extracted = smm_cli.extract_pillars(smm, {"intent", "constraints"})
    return [_common.wrap_smm_context(extracted)] if extracted else []


def _inject_full(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Default: full SMM (no process guide)."""
    rendered = smm_cli.render_markdown(smm)
    return [_common.wrap_smm_context(rendered)] if rendered.strip() else []


def _inject_teammate_core(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Shared teammate injection: coordination + system context + SMM."""
    agent_id = input_data.get("agent_id", "")
    if agent_id and smm_dir:
        coordination.update_coordination(smm_dir, agent_id, [])
    parts: list[str] = []
    ctx_path = smm_dir / "system_context.md"
    if ctx_path.exists() and not ctx_path.is_symlink():
        try:
            ctx_content = ctx_path.read_text(encoding="utf-8")
            if ctx_content.strip():
                parts.append(f"## System Context\n{ctx_content}")
        except OSError:
            pass  # Graceful degradation
    rendered = smm_cli.render_markdown(smm)
    if rendered.strip():
        parts.append(_common.wrap_smm_context(rendered))
    return parts


def _inject_teammate(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Agent Teams teammate: SMM + teammate guide."""
    parts = _inject_teammate_core(smm, smm_dir, input_data)
    guide = _common.load_teammate_guide()
    if guide:
        parts.append(guide)
    return parts


def _inject_xp_teammate(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """xp-teammate: SMM + system context (instructions in agent .md)."""
    return _inject_teammate_core(smm, smm_dir, input_data)


def _inject_xp_agent(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
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
    "xp-teammate": _inject_xp_teammate,
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

    # Read curated SMM from JSON
    import smm_store

    smm_data = smm_store.load_smm(smm_dir)

    # Record start event
    start_event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_started_content(agent_id),
        working_on=[],
    )
    _common.append_safe(smm_dir, start_event)

    # Run the selected injector (tier-specific context)
    parts = injector(smm_data, smm_dir, input_data)

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

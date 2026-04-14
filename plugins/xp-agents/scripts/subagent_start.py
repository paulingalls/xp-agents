#!/usr/bin/env python3
"""SubagentStart hook: inject project context for subagents.

Tiered injection via dispatch table:
- Explore: Intent + Constraints pillars (~200 tokens)
- Default (Plan/general-purpose/custom): Full SMM
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
import smm_cli


def _inject_explore(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Explore: Intent + Constraints only."""
    extracted = smm_cli.extract_pillars(smm, {"intent", "constraints"})
    return [_common.wrap_smm_context(extracted)] if extracted else []


def _inject_full(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Default: full SMM (no process guide)."""
    rendered = smm_cli.render_markdown(smm)
    return [_common.wrap_smm_context(rendered)] if rendered.strip() else []


def _inject_xp_agent(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """xp-* forked agents: values only (data comes from preloads)."""
    return []


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
        injector = _inject_xp_agent if agent_type.startswith("xp-") else _inject_full

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

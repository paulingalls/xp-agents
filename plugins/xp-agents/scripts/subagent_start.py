#!/usr/bin/env python3
"""SubagentStart hook: inject project context for subagents.

Tiered injection via dispatch table (measured sizes):
- Explore: Intent + Constraints + XP values (~5 KB)
- xp-code-reviewer / Default: Full SMM + XP values (~10 KB)
- xp-retrospective: SMM_DIR + RETRO_INPUT paths + XP values (~1.6 KB)
- xp-close-reviewer: SMM_DIR + REVIEW_INPUT paths + XP values (~1.6 KB)
- xp-housekeeper: curation input path + work selection + XP values (~1.5-3 KB)
- xp-* forked agents: XP values only (~1.4 KB)
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


def _inject_retrospective(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """xp-retrospective (inline-agent): inject SMM_DIR and RETRO_INPUT paths.

    .retro-input.json is written by scripts/retrospective.py at SessionStart,
    so the handler only advertises the paths the agent prompt expects.
    """
    return [f"SMM_DIR={smm_dir}\nRETRO_INPUT={smm_dir / _common.RETRO_INPUT_FILENAME}"]


_CURATION_INPUT_FILENAME = ".curation-input.json"
_RETRO_TRY_TOPIC_PREFIX = "retro-try-"


def _gather_work_selection_events(smm_dir: Path) -> str | None:
    """Current-session work-selection events as a markdown block, or None.

    Boundary is the last session_end event; earlier events belong to prior
    sessions. Three categories are surfaced so the housekeeper can weigh
    the user's in-session choices during Intent/Risk curation.
    """
    import materialize

    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return None

    current = events[_common.current_session_start_index(events) :]

    adopted: list[str] = []
    deferred_dropped: list[str] = []
    goals: list[str] = []
    for ev in current:
        etype = ev.get("type")
        content = ev.get("content", "")
        match etype:
            case _common.DECISION if ev.get("topic", "").startswith(
                _RETRO_TRY_TOPIC_PREFIX
            ):
                adopted.append(content)
            case _common.STATUS if ev.get("metadata", {}).get("disposition") in (
                "deferred",
                "dropped",
            ):
                deferred_dropped.append(content)
            case _common.GOAL:
                goals.append(content)

    if not (adopted or deferred_dropped or goals):
        return None

    sections: list[str] = ["## Session Work Selection", ""]
    for heading, items in (
        ("### Adopted Tries", adopted),
        ("### Deferred / Dropped", deferred_dropped),
        ("### Goals", goals),
    ):
        if items:
            sections.append(heading)
            sections.extend(f"- {item}" for item in items)
            sections.append("")
    return "\n".join(sections).rstrip()


def _inject_housekeeper(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """xp-housekeeper (inline-agent): write curation input + inject paths.

    Writes .curation-input.json via materialize.prepare_curation_data,
    advertises SMM_DIR + CURATION_INPUT, and appends an optional
    ## Session Work Selection block capturing adopted/deferred/dropped
    retro Tries and session goals so the housekeeper sees the user's
    in-session disposition signals directly.
    """
    import materialize

    curation_path = smm_dir / _CURATION_INPUT_FILENAME
    _common.write_json_atomic(curation_path, materialize.prepare_curation_data(smm_dir))

    parts = [f"SMM_DIR={smm_dir}\nCURATION_INPUT={curation_path}"]
    work_selection = _gather_work_selection_events(smm_dir)
    if work_selection:
        parts.append(work_selection)
    return parts


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Callable[..., list[str]]] = {
    "Explore": _inject_explore,
    "xp-code-reviewer": _inject_full,
    "xp-agents:xp-code-reviewer": _inject_full,
    "xp-retrospective": _inject_retrospective,
    "xp-agents:xp-retrospective": _inject_retrospective,
    "xp-housekeeper": _inject_housekeeper,
    "xp-agents:xp-housekeeper": _inject_housekeeper,
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core subagent_start logic. Returns additionalContext or None."""
    agent_type = input_data.get("agent_type", "")

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

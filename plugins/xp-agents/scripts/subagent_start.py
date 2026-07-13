#!/usr/bin/env python3
"""SubagentStart hook: inject project context for subagents.

Tiered injection via the _TIERS registry (injector, wants_sequential_note):
- Explore: Intent + Constraints pillars + XP values
- xp-code-reviewer / Plan / unknown types: full SMM + XP values
- xp-retrospective: SMM_DIR + RETRO_INPUT paths + XP values
- xp-housekeeper: curation path + work-selection block + XP values
- xp-* forked agents (close/plan/sprint reviewer): XP values only
- Generic catch-alls (workflow-subagent / general-purpose / claude): XP values +
  a cheap SMM reference pointer, no full render. Purpose-blind, prompt-driven,
  highest-fanout types; most do read-only review/research, and a code-writing one
  renders the curated SMM on demand from the pointer.

Every tier gets the sequential-discipline note EXCEPT the generic catch-alls
(they do independent reads, the case the note already exempts).
"""

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import marker_names
import plugin_loader
import smm_cli
import target_routing
from event_schema import (
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    DISPOSITION_DROPPED,
    event_action,
    event_disposition,
    is_retro_lane,
    is_triage_lane,
)


def _inject_explore(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Explore: Intent + Constraints only."""
    extracted = smm_cli.extract_pillars(smm, {"intent", "constraints"})
    return [_common.wrap_smm_context(extracted)] if extracted else []


def _inject_full(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Default: full SMM (no process guide)."""
    rendered = smm_cli.render_markdown(smm)
    return [_common.wrap_smm_context(rendered)] if rendered.strip() else []


def _inject_no_smm(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """No SMM payload — xp-* forked agents get their data via skill preload."""
    return []


# smm_cli.py, resolved relative to this hook (env-independent) so the pointer
# below names an absolute path the spawned agent can run as-is.
_SMM_CLI = Path(__file__).resolve().parent.parent / "smm" / "smm_cli.py"


def _inject_reference(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """Generic agents (workflow-subagent / general-purpose / claude): a cheap
    pointer to the curated SMM instead of the full render. Purpose-blind and
    prompt-driven — most do read-only review/research and never need it, but a
    code-writing one self-serves the conventions + lessons on demand."""
    return [
        f"Project context (xp-agents) — SMM_DIR={smm_dir}\n"
        "If your task writes, designs, or changes code in this project, read its "
        "curated conventions and lessons first:\n"
        f"    python3 {_SMM_CLI} --smm-dir {smm_dir} render\n"
        "(Constraints = rules to follow · Wisdom = durable lessons · "
        "Risks = open concerns)"
    ]


def _inject_retrospective(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """xp-retrospective: advertise paths (retrospective.py writes RETRO_INPUT)."""
    return [f"SMM_DIR={smm_dir}\nRETRO_INPUT={smm_dir / _common.RETRO_INPUT_FILENAME}"]


# Only used to read events written BEFORE the lane tag existed — a tagged
# adoption is identified by its tag, never by its topic. An LLM authors this
# slug, so a tagged adoption whose slug drifts must still be seen.
_LEGACY_RETRO_TOPIC_PREFIX = "retro-try-"

# This reader's own bucket is "Deferred / **Dropped**", so it keeps its own
# disposition set and reads the RAW disposition (`event_disposition`). NOT
# intent_disposition(), which returns None for `dropped` by design — the intent
# module is deliberately blind to drops (a drop closes via metadata.resolves).
# Reusing it here would silently empty the Dropped half of this bucket.
_RETRO_BUCKET_DISPOSITIONS = (DISPOSITION_DEFERRED, DISPOSITION_DROPPED)
# The triage lane's own bucket. A triage DROP is absent on purpose: a drop is
# closure, so it lands in metadata.resolves — the one thing materialize reads
# off a `status` event — and reaches the housekeeper through the resolutions.
_TRIAGE_BUCKET_DISPOSITIONS = (DISPOSITION_ADOPTED, DISPOSITION_DEFERRED)


def _gather_work_selection_events(smm_dir: Path) -> str | None:
    """Current-session work-selection events as a markdown block, or None.

    Boundary is the most recent session_started anchor.

    Both lanes write `status` events carrying the same disposition vocabulary,
    so the disposition ALONE cannot say which lane an event came from. Each arm
    below gates on the LANE first (`is_retro_lane` / `is_triage_lane`) and only
    then on its own disposition set. Without the lane gate, a triage defer of a
    DEBT arrived under "Deferred / Dropped" and the housekeeper read it as a
    retro Try the session had declined.

    Untagged events fall through to the legacy rules the tag replaced (a
    `retro-try-` topic prefix for adoptions) — `is_retro_lane` admits them, so
    events written before the tag existed keep being seen.
    """
    import materialize

    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return None

    current = events[_common.current_session_start_index(events) :]

    adopted: list[str] = []
    deferred_dropped: list[str] = []
    triaged: list[str] = []
    goals: list[str] = []
    for ev in current:
        content = ev.get("content", "")
        match ev.get("type"):
            case _common.DECISION if _is_retro_adoption(ev):
                adopted.append(content)
            case _common.STATUS if (
                is_retro_lane(ev)
                and event_disposition(ev) in _RETRO_BUCKET_DISPOSITIONS
            ):
                deferred_dropped.append(content)
            case _common.STATUS if (
                is_triage_lane(ev)
                and event_disposition(ev) in _TRIAGE_BUCKET_DISPOSITIONS
            ):
                triaged.append(content)
            case _common.GOAL:
                goals.append(content)

    if not (adopted or deferred_dropped or triaged or goals):
        return None

    sections: list[str] = ["## Session Work Selection", ""]
    for heading, items in (
        ("### Adopted Tries", adopted),
        ("### Deferred / Dropped", deferred_dropped),
        ("### Triage: Adopted / Deferred", triaged),
        ("### Goals", goals),
    ):
        if items:
            sections.append(heading)
            sections.extend(f"- {item}" for item in items)
            sections.append("")
    return "\n".join(sections).rstrip()


def _is_retro_adoption(event: dict) -> bool:
    """A `decision` that adopts a retro Try: tagged for the retro lane with an
    `adopted` disposition, or — untagged — slugged with the legacy topic prefix.

    The tag is decisive when present, so an adoption whose LLM-authored slug
    drifted off the prefix is still seen. The topic check is reached only by an
    untagged event, which is the one case where no tag can answer.
    """
    if event_action(event) is not None:
        return is_retro_lane(event) and event_disposition(event) == DISPOSITION_ADOPTED
    return (event.get("topic") or "").startswith(_LEGACY_RETRO_TOPIC_PREFIX)


def _inject_housekeeper(smm: dict, smm_dir: Path, input_data: dict) -> list[str]:
    """xp-housekeeper: write curation input + inject paths + work-selection block."""
    import materialize

    curation_path = smm_dir / marker_names.CURATION_INPUT
    _common.write_json_atomic(curation_path, materialize.prepare_curation_data(smm_dir))

    parts = [f"SMM_DIR={smm_dir}\nCURATION_INPUT={curation_path}"]
    work_selection = _gather_work_selection_events(smm_dir)
    if work_selection:
        parts.append(work_selection)
    return parts


SEQUENTIAL_DISCIPLINE_NOTE = (
    "You are a single-purpose sequential agent: do one action, observe its "
    "result, then proceed. The harness's parallel-batching guidance does not "
    "apply to dependent calls (e.g. save then verify) — only to independent reads."
)

# The generic catch-all tier: the SMM reference pointer, and NO sequential note
# (these agents do independent reads, the case the note already exempts).
_GENERIC_TIER: tuple[Callable[..., list[str]], bool] = (_inject_reference, False)

# Per-tier (injector, wants_sequential_note), keyed by BARE agent-type names.
# Incoming `xp-agents:<bare>` qualified forms are normalized via
# target_routing.strip_our_namespace before lookup. One registry — not a
# dispatch dict plus a separate note-skip set — so a type's injector and its
# note flag can never drift out of sync.
_TIERS: dict[str, tuple[Callable[..., list[str]], bool]] = {
    "Explore": (_inject_explore, True),
    "xp-code-reviewer": (_inject_full, True),
    "xp-retrospective": (_inject_retrospective, True),
    "xp-housekeeper": (_inject_housekeeper, True),
    # Generic catch-alls (Workflow fan-out + ad-hoc Task agents): reference tier.
    "workflow-subagent": _GENERIC_TIER,
    "general-purpose": _GENERIC_TIER,
    "claude": _GENERIC_TIER,
}


def _resolve_tier(agent_type: str, bare: str) -> tuple[Callable[..., list[str]], bool]:
    """(injector, wants_note) for an agent type. Fallbacks: xp-* forked agents
    get values only (their data comes via preload) but keep the note for their
    step-gated SMM work; everything else unknown (Plan, ad-hoc) gets the full
    SMM — eager context earns its cost there."""
    tier = _TIERS.get(bare)
    if tier is not None:
        return tier
    if agent_type.startswith("xp-"):
        return (_inject_no_smm, True)
    return (_inject_full, True)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core subagent_start logic. Returns additionalContext or None."""
    agent_type = input_data.get("agent_type", "")

    bare = target_routing.strip_our_namespace(agent_type) or agent_type
    injector, wants_note = _resolve_tier(agent_type, bare)

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        values = plugin_loader.load_xp_values()
        parts = [values] if values else []
        if wants_note:
            parts.append(SEQUENTIAL_DISCIPLINE_NOTE)
        return "\n\n".join(parts)

    agent_id = input_data.get("agent_id", "subagent")

    import smm_store

    smm_data = smm_store.load_smm(smm_dir)

    start_event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_started_content(agent_id),
        working_on=[],
    )
    _common.append_safe(smm_dir, start_event)

    parts = injector(smm_data, smm_dir, input_data)

    values = plugin_loader.load_xp_values()
    if values:
        parts.append(values)

    if wants_note:
        parts.append(SEQUENTIAL_DISCIPLINE_NOTE)

    return "\n\n".join(parts)


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        _common.hook_output("SubagentStart", context)
    sys.exit(0)

#!/usr/bin/env python3
"""PostToolUse:Skill hook: inject SMM + behavioral guide after kickoff.

When /xp-housekeeping completes (the final step of kickoff),
injects SHARED_MENTAL_MODEL.md + BEHAVIORAL_GUIDE.md as
additionalContext and compacts the event log. Housekeeping is
forked, so the main agent needs both injected here.
"""

import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import compact
import markers
import sprint_state


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Inject SMM + behavioral guide after xp-kickoff completes."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    # Plugin skills may arrive as "xp-housekeeping" or "xp-agents:xp-housekeeping"
    housekeeping_names = {"xp-housekeeping", "xp-agents:xp-housekeeping"}
    if skill_name not in housekeeping_names:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Clean up kickoff marker
    markers.marker_consume(smm_dir, markers.KICKOFF)

    # Compact event log — housekeeping just curated, safe to archive
    compact_result = None
    try:
        compact_result = compact.compact_after_curation(smm_dir)
    except Exception as e:
        # Log failure as concern so we can diagnose
        concern = _common.make_event(
            _common.CONCERN,
            "xp-kickoff-done",
            f"Event log compaction failed: {e}",
            severity="low",
        )
        _common.append_safe(smm_dir, concern)

    # Log that kickoff completed (helps diagnose hook firing issues)
    archived = compact_result["archived"] if compact_result else 0
    retained = compact_result["retained"] if compact_result else 0
    status = _common.make_event(
        _common.STATUS,
        "xp-kickoff-done",
        f"Kickoff complete. Compacted: {archived} archived, {retained} retained.",
        working_on=[],
    )
    _common.append_safe(smm_dir, status)

    markers.marker_consume(smm_dir, markers.NEEDS_PRODUCT_SPEC)
    markers.marker_consume(smm_dir, markers.NEEDS_SPRINT)

    # Housekeeping is forked — inject SMM + process guide so the main
    # agent has workflow context after kickoff. XP values are already
    # in context from session_start.
    smm_content = ""
    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
    with contextlib.suppress(FileNotFoundError):
        smm_content = smm_file.read_text(encoding="utf-8").strip()

    process = _common.load_process_guide()

    # Nudge if sprint exists but no stories are in-progress
    sprint_content = sprint_state.read_sprint_content(smm_dir)
    nudge = ""
    if sprint_content and not sprint_state.has_in_progress_stories(sprint_content):
        nudge = (
            "\n\n---\n**Sprint notice:** No stories marked "
            "`in-progress`. Run story selection to pick "
            "stories for this iteration."
        )

    parts = [p for p in [smm_content, process, nudge] if p]
    result = "\n\n".join(parts)
    return result if result else None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)

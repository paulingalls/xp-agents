#!/usr/bin/env python3
"""PostToolUse:Skill hook: inject behavioral guide + compact after kickoff.

When /xp-housekeeping completes (the final step of kickoff),
injects BEHAVIORAL_GUIDE.md as additionalContext and compacts the
event log. The curated SMM is already in context — housekeeping reads
and writes the file directly.
"""

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

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
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

    # Inject behavioral guide only — the agent already has the SMM
    # from housekeeping step 8 (Read the file it just wrote).
    guide = _common.load_behavioral_guide()

    # Nudge if sprint exists but no stories are in-progress
    sprint_content = sprint_state.read_sprint_content(smm_dir)
    nudge = ""
    if sprint_content and not sprint_state.has_in_progress_stories(sprint_content):
        nudge = (
            "\n\n---\n**Sprint notice:** No stories marked "
            "`in-progress`. Run story selection to pick "
            "stories for this iteration."
        )

    result = (guide or "") + nudge
    return result if result else None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)

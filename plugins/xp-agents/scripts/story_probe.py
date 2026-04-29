#!/usr/bin/env python3
"""Story-prefix probe: nudge the agent to add `[story-NNN]` at commit time.

Called by `pre_tool_bash.run` alongside the resolves-trailer probe. When a
commit lands during a multi-story-in-progress window with no `[bracketed]`
prefix and a single dominant file-domain overlap, surface a soft nudge so
the agent can attribute via Tier 0 (explicit prefix) instead of relying on
Tier 2b's overlap heuristic at PostToolUse.

Always soft — never raises. Sibling helpers `find_story_candidate`,
`build_nudge_line`, and `emit_probe_status` mirror `resolves_probe`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity
import sprint_store
import story_metrics
import worktree
from event_schema import (
    METADATA_KEY_STORY_CANDIDATE,
    STATUS_CONTENT_STORY_PROBE,
)


def find_story_candidate(
    smm_dir: Path,
    cwd: str,
    staged_files: list[str],
    message: str,
    sprint: dict | None = None,
) -> dict | None:
    """Return a story-prefix nudge candidate, or None.

    Silencing rules (mirror `_resolve_story_id`'s tier ordering):
      - No sprint or 0 in-progress stories
      - 1 in-progress story (Tier 2a will attribute at commit time)
      - Worktree teammate with `.story-assignment-{name}` (Tier 1 attributes)
      - Any `[bracketed]` prefix on the message (agent-declared intent)
      - Tied or zero file-domain overlap

    Returns `{story_id, overlap_count, total_files}` on a single dominant
    overlap match.
    """
    if story_metrics.BRACKET_PREFIX_RE.match(message or ""):
        return None

    wt_name = identity.extract_worktree_name(cwd)
    if wt_name is not None:
        assignment = worktree.story_assignment_path(smm_dir, wt_name)
        if assignment.exists():
            return None

    if sprint is None:
        sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return None

    in_progress = sprint_store.list_stories(sprint, status="in-progress")
    if len(in_progress) < 2:
        return None

    story_id, overlap = story_metrics.resolve_dominant_story(in_progress, staged_files)
    if story_id is None:
        return None

    return {
        "story_id": story_id,
        "overlap_count": overlap,
        "total_files": len(staged_files),
    }


def build_nudge_line(candidate: dict) -> str:
    """Format the soft-nudge line for a story candidate."""
    sid = candidate["story_id"]
    return (
        f"Story attribution: staged files match {sid}'s domain "
        f"({candidate['overlap_count']}/{candidate['total_files']} files). "
        f"Add prefix [{sid}] (or any other [bracketed] prefix to skip)."
    )


def emit_probe_status(smm_dir: Path, candidate: dict | None, agent_id: str) -> None:
    """Write a story-probe status event. No-op when candidate is None so
    callers can invoke unconditionally without guarding each call site."""
    if candidate is None:
        return
    sid = candidate["story_id"]
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        f"{STATUS_CONTENT_STORY_PROBE}: {sid}",
        working_on=[],
        metadata={METADATA_KEY_STORY_CANDIDATE: sid},
    )
    _common.append_safe(smm_dir, event)

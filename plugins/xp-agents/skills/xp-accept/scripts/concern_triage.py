#!/usr/bin/env python3
"""Find open concerns overlapping in-motion stories' file domains.

Called by xp-accept preload to surface concerns that may have been
addressed by the story's work. The LLM agent in xp-accept then judges
whether each concern is truly resolved.

Usage:
    python3 concern_triage.py --smm-dir /path/to/smm --sprint-file /path/to/sprint.json
"""

import argparse
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import event_schema  # noqa: E402
import materialize  # noqa: E402
import resolution  # noqa: E402
import triage  # noqa: E402
from sprint_status import select_in_motion_stories  # noqa: E402


def find_concerns_for_story(
    story: dict,
    open_concerns: list[dict],
) -> list[dict]:
    """Find open concerns whose files overlap a story's file_domain.

    Pass concern files as candidates so file_domain globs expand against
    the actual concern paths (mirrors the cascade-analysis drift fix).
    """
    file_domain = story.get("file_domain") or []
    concern_file_union: set[str] = set()
    for concern in open_concerns:
        concern_file_union |= set(concern.get("files") or [])
    domain_paths = triage.extract_file_domain_paths(
        file_domain, candidate_files=concern_file_union
    )
    if not domain_paths:
        return []

    matching = []
    for concern in open_concerns:
        concern_files = set(concern.get("files") or [])
        if concern_files & domain_paths:
            matching.append(concern)
    return matching


def format_concern_triage(
    story_id: str,
    concerns: list[dict],
    events: list[dict],
) -> str:
    """Format concern triage output for a story."""
    if not concerns:
        return ""

    lines = [f"### Concerns for {story_id}"]
    for concern in concerns:
        cid = concern.get("id", "")
        content = concern.get("content", "")
        files = concern.get("files") or []
        lines.append(f"- [id: {cid}] {content}")
        if files:
            lines.append(f"  Files: {', '.join(files)}")
        hits = triage.find_overlapping_commits(concern, events)
        if hits:
            msgs = "; ".join(c.get("content", "")[:80] for c in hits[:3])
            lines.append(f"  **LIKELY ADDRESSED** by: {msgs}")
    return "\n".join(lines)


def run(smm_dir: Path, sprint_file: Path) -> str:
    """Scan for open concerns matching in-motion stories."""
    if not sprint_file.is_file():
        return ""

    sprint_data = json.loads(sprint_file.read_text())
    stories = select_in_motion_stories(sprint_data.get("stories", []))
    if not stories:
        return ""

    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return ""

    resolutions = resolution.compute_resolutions(events)
    resolved_ids = resolution.collect_all_resolved_ids(resolutions)

    open_concerns = triage.find_unresolved(
        events, event_schema.EVENT_TYPE_CONCERN, resolved_ids
    )

    sections: list[str] = []
    for story in stories:
        concerns = find_concerns_for_story(story, open_concerns)
        section = format_concern_triage(story.get("id", ""), concerns, events)
        if section:
            sections.append(section)

    return "\n\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find open concerns overlapping in-motion stories."
    )
    parser.add_argument("--smm-dir", type=Path, required=True)
    parser.add_argument("--sprint-file", type=Path, required=True)
    args = parser.parse_args()

    output = run(args.smm_dir, args.sprint_file)
    if output:
        print(output)


if __name__ == "__main__":
    main()

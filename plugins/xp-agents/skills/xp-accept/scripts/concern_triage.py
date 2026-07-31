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
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import commits  # noqa: E402
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


# Same 400 as the kickoff triage block, and for the same reason: it is the
# previous content cap, so the excerpt keeps the whole WHY every stored concern
# used to carry. The count cap is this block's own — one story's concerns are a
# working set, not an inventory, and a story touching a busy path was paying
# the entire backlog at full length (40,481 chars measured against a shape
# budget of 100).
_EXCERPT_MAX_CHARS = 400
_MAX_CONCERNS_PER_STORY = 10

# The count cap bounds how many concerns render; this bounds what ONE of them
# can cost. `files` was the term neither of the caps above reached — it renders
# in full for every shown concern, so a concern naming 200 paths outweighs the
# 400-char excerpt of the WHY it sits under. 12 because the largest concern on
# the live log names 28 files and the median names 1, so this fires on the
# outliers and leaves ordinary concerns untouched; the id retrieves the whole
# list, and the remainder is COUNTED rather than silently dropped.
_MAX_FILES_PER_CONCERN = 12

_ALL_COMMAND = (
    "python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-accept/scripts/concern_triage.py "
    "--smm-dir <SMM_DIR> --sprint-file <SPRINT_FILE> --all"
)


def _format_files(files: list[str]) -> str:
    """One concern's file list, bounded and with the remainder counted."""
    shown = ", ".join(files[:_MAX_FILES_PER_CONCERN])
    extra = len(files) - _MAX_FILES_PER_CONCERN
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def format_concern_triage(
    story_id: str,
    concerns: list[dict],
    events: list[dict],
    *,
    uncapped: bool = False,
) -> str:
    """Format concern triage output for a story.

    `uncapped` is the `--all` retrieval path the overflow line names.
    """
    if not concerns:
        return ""

    omitted = 0
    if not uncapped:
        concerns, omitted = triage.cap_with_overflow(concerns, _MAX_CONCERNS_PER_STORY)

    lines = [f"### Concerns for {story_id}"]
    for concern in concerns:
        cid = concern.get("id", "")
        content = _common.truncate(concern.get("content", ""), _EXCERPT_MAX_CHARS)
        files = concern.get("files") or []
        lines.append(f"- [id: {cid}] {content}")
        if files:
            lines.append(f"  Files: {_format_files(files)}")
        hits = commits.find_addressing_commits(concern, events)
        if hits:
            lines.append(commits.format_maybe_addressed_line(hits))
    if omitted:
        lines.append(triage.overflow_line(omitted, _ALL_COMMAND))
    return "\n".join(lines)


def run(smm_dir: Path, sprint_file: Path, *, uncapped: bool = False) -> str:
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
        section = format_concern_triage(
            story.get("id", ""), concerns, events, uncapped=uncapped
        )
        if section:
            sections.append(section)

    return "\n\n".join(sections)


def _build_parser() -> argparse.ArgumentParser:
    """Named, so a test can assert the overflow line's command really parses."""
    parser = argparse.ArgumentParser(
        description="Find open concerns overlapping in-motion stories."
    )
    parser.add_argument("--smm-dir", type=Path, required=True)
    parser.add_argument("--sprint-file", type=Path, required=True)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Render every matching concern, ignoring the per-story cap.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    output = run(args.smm_dir, args.sprint_file, uncapped=args.all)
    if output:
        print(output)


if __name__ == "__main__":
    main()

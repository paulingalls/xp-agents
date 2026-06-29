#!/usr/bin/env python3
"""Save sprint: write sprint.json atomically + handle acceptance flow.

Called by xp-sprint-start, xp-work-selection, and xp-accept to persist
sprint.json. After writing, it:

- Clears the .needs-sprint marker if sprint now has active stories.
- If the .accept marker was present and no in-progress stories remain,
  treats this as acceptance completion: clears .accept, records an
  iteration_complete status event, and — if the sprint is now complete —
  prints a sprint-review nudge to stdout for the main agent to see.

Usage:
    echo '<json>' | python3 save_sprint.py --smm-dir DIR
"""

import argparse
import contextlib
import json
import os
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SKILL_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(_SKILL_SCRIPTS))

import _common  # noqa: E402
import concerns  # noqa: E402
import execution_plan_store  # noqa: E402
import identity  # noqa: E402
import marker_names  # noqa: E402
import sister_tests  # noqa: E402
import sprint_store  # noqa: E402
from event_schema import (  # noqa: E402
    EVENT_TYPE_STATUS,
    STATUS_ACTION_ITERATION_COMPLETE,
)

# Matches "Milestone N: <anything>" or "Milestone N — <anything>"
_MILESTONE_NUMBER_RE = re.compile(r"^\s*Milestone\s+(\d+)\b", re.IGNORECASE)

_SPRINT_REVIEW_NUDGE = (
    "\n**Sprint complete!** All stories are done or deferred. "
    "Run `/xp-sprint-review` to review the sprint."
)


def _record_concern(smm_dir: Path, content: str) -> None:
    """Append a low-severity concern event. Never raises — recording a
    concern must not cascade into a sprint-save failure.

    agent_id is teammate-resolved attribution per the agent-id-semantics
    ADR; skill identity is not encoded into agent_id.
    """
    agent_id = identity.resolve_agent_id_from_cwd(os.getcwd())
    with contextlib.suppress(OSError, ValueError):
        _common.append_safe(smm_dir, concerns.make_concern(content, "low", agent_id))


def _transition_target_milestone(data: dict, smm_dir: Path) -> None:
    """Flip the sprint's target milestone from planned to in-progress.

    Non-fatal: every failure mode (missing plan, unparseable milestone
    text, milestone number not found) records a concern and returns
    without raising so the sprint write always completes.
    """
    milestone_text = data.get("milestone", "") or ""
    match = _MILESTONE_NUMBER_RE.match(milestone_text)
    if not match:
        _record_concern(
            smm_dir,
            f"Could not parse milestone number from sprint.milestone text "
            f"{milestone_text!r}. Expected 'Milestone N: <name>'. Execution "
            f"plan status not updated.",
        )
        return
    target_num = int(match.group(1))

    try:
        plan = execution_plan_store.load_plan(smm_dir)
    except (OSError, ValueError) as exc:
        _record_concern(
            smm_dir,
            f"Could not read execution plan to transition milestone "
            f"{target_num}: {exc}",
        )
        return
    if plan is None:
        _record_concern(
            smm_dir,
            f"No execution plan found; milestone {target_num} status not "
            f"transitioned. Sprint saved but plan hygiene skipped.",
        )
        return

    leaked = [
        m["number"]
        for m in plan["milestones"]
        if m["status"] == "in-progress" and m["number"] != target_num
    ]
    if leaked:
        _record_concern(
            smm_dir,
            f"Another milestone is already in-progress ({leaked}) while "
            f"starting sprint for milestone {target_num}. Possible leaked "
            f"in-progress state from a prior sprint pivot.",
        )

    try:
        execution_plan_store.update_milestone_status(smm_dir, target_num, "in-progress")
    except (OSError, ValueError) as exc:
        _record_concern(
            smm_dir,
            f"Failed to transition milestone {target_num} to in-progress: {exc}",
        )


def _extract_path(entry: str) -> str:
    """file_domain entries are 'path/to/file — note' or just 'path/to/file'.
    Return the path portion."""
    return entry.split(" — ", 1)[0].strip()


def _auto_include_sister_tests(
    data: dict,
    layout: "sister_tests.TestLayout",
    project_root: Path,
) -> None:
    """For each story in data['stories'], discover sister tests for the
    source paths in its file_domain and append new entries formatted as
    '<rel> — sister test for <src>'. Dedups against existing file_domain
    entries (by source-path-extracted key). Skips entries already marked
    as sisters (prevents sister-of-sister expansion). Mutates data in
    place. No SMM writes."""
    for story in data.get("stories", []):
        domain = story.get("file_domain")
        if not isinstance(domain, list):
            continue
        existing_paths = {_extract_path(e) for e in domain if isinstance(e, str)}
        additions: list[str] = []
        for entry in list(domain):  # snapshot — don't iterate over a mutating list
            if not isinstance(entry, str):
                continue
            if " — sister test for " in entry:
                continue  # prevents sister-of-sister expansion
            src = _extract_path(entry)
            if not src:
                continue
            try:
                sisters = sister_tests.discover_sister_tests(src, layout, project_root)
            except ValueError:
                continue  # bad source path; skip silently (validator owns shape)
            for sister in sisters:
                if sister in existing_paths:
                    continue
                additions.append(f"{sister} — sister test for {src}")
                existing_paths.add(sister)
        domain.extend(additions)


def run(data: dict, smm_dir: Path) -> None:
    """Write sprint.json and run the acceptance-flow side effects.

    Args:
        data: Sprint data dict (validated by sprint_store).
        smm_dir: SMM directory path.
    """
    accept_marker = smm_dir / marker_names.ACCEPT
    accept_marker_existed = accept_marker.exists()

    sprint_store.save_sprint(smm_dir, data)

    _transition_target_milestone(data, smm_dir)

    # Acceptance flow: .accept was present, no in-progress stories.
    # Use in-memory data to avoid re-reading the file we just wrote.
    has_ip = any(s["status"] == "in-progress" for s in data["stories"])
    if accept_marker_existed and not has_ip:
        accept_marker.unlink(missing_ok=True)

        # agent_id is teammate-resolved attribution per the agent-id-semantics
        # ADR; skill identity lives in metadata.action.
        agent_id = identity.resolve_agent_id_from_cwd(os.getcwd())
        event = _common.make_event(
            EVENT_TYPE_STATUS,
            agent_id,
            "Iteration complete — accept verification done.",
            working_on=[],
            metadata={"action": STATUS_ACTION_ITERATION_COMPLETE},
        )
        _common.append_safe(smm_dir, event)

        is_done = not sprint_store.has_active_stories_data(data)
        if is_done:
            print(_SPRINT_REVIEW_NUDGE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save sprint.json atomically")
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    args = parser.parse_args()

    raw = sys.stdin.read()
    data = json.loads(raw)
    run(data, args.smm_dir)


if __name__ == "__main__":
    main()

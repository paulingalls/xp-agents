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
import markers  # noqa: E402
import sister_tests  # noqa: E402  # pyright: ignore[reportMissingImports]
import sprint_store  # noqa: E402
import system_context_store  # noqa: E402
import triage  # noqa: E402
import worktree  # noqa: E402
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


def _coerce_overrides(raw: object) -> tuple["sister_tests.TestLayoutRule", ...]:
    """Coerce JSON list-of-dicts to tuple-of-TestLayoutRule. Round-trips
    skip_basenames/skip_suffixes/source_excludes from JSON list to tuple.
    Silently drops malformed entries — schema validator is the source of
    truth; this is defensive."""
    if not isinstance(raw, list):
        return ()
    out: list[sister_tests.TestLayoutRule] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                sister_tests.TestLayoutRule(
                    source_pattern=entry["source_pattern"],
                    stem_extractor=entry["stem_extractor"],
                    test_glob=entry["test_glob"],
                    skip_basenames=tuple(entry.get("skip_basenames", ())),
                    skip_suffixes=tuple(entry.get("skip_suffixes", ())),
                    source_excludes=tuple(entry.get("source_excludes", ())),
                )
            )
        except (KeyError, TypeError):
            continue
    return tuple(out)


def _resolve_layout(smm_dir: Path) -> "sister_tests.TestLayout | None":
    """Load system_context.test_layout and construct a TestLayout. Returns
    None when test_layout is absent, convention is 'unknown', system_context
    is missing/unreadable, OR the layout resolves to no rules and no
    overrides (a degenerate "custom" with empty overrides). Never writes
    events.

    Returning None for the degenerate-custom case ensures the soft-warn
    path fires once instead of silently no-op'ing every save."""
    try:
        sc = system_context_store.load_system_context(smm_dir)
    except (OSError, ValueError):
        return None
    if sc is None:
        return None
    layout_data = sc.get("test_layout")
    if not isinstance(layout_data, dict):
        return None
    convention = layout_data.get("convention")
    if not isinstance(convention, str) or convention == "unknown":
        return None
    if convention == "custom":
        rules: tuple[sister_tests.TestLayoutRule, ...] = ()
    else:
        builtin = sister_tests.BUILTIN_LAYOUTS.get(convention)
        if builtin is None:
            return None  # schema validator should catch this earlier
        rules = builtin.rules
    overrides = _coerce_overrides(layout_data.get("overrides", []))
    if not rules and not overrides:
        # Degenerate layout (convention='custom' with empty/malformed
        # overrides) — discovery would iterate zero rules and return zero
        # sisters on every save. Treat as "no layout configured" so the
        # soft-warn path surfaces it.
        return None
    return sister_tests.TestLayout(
        convention=convention, rules=rules, overrides=overrides
    )


def _warn_sister_skip_once(smm_dir: Path, reason: str) -> None:
    """One low-severity concern per session when sister-test discovery is
    skipped. The reason string distinguishes the actual skip cause —
    layout unresolved vs project root not found vs degenerate-custom — so
    the concern stays honest instead of always blaming convention='unknown'.

    Delegates to markers.warn_once for the marker-gated append; that
    primitive enforces the canonical markers API (symlink protection)
    and is the single place future warn-once needs should land.
    SISTER_TEST_LAYOUT_WARN is registered in _STALE_SESSION_MARKERS so
    SessionStart re-arms the warn."""
    agent_id = identity.resolve_agent_id_from_cwd(os.getcwd())
    markers.warn_once(
        smm_dir,
        markers.SISTER_TEST_LAYOUT_WARN,
        f"Sister-test auto-inclusion skipped: {reason}. Run /xp-system-context"
        " to detect a layout, or pipe a layout dict into"
        " system_context_cli.py edit-test-layout.",
        agent_id,
    )


def _resolve_project_root() -> Path | None:
    """Delegate to worktree.resolve_git_root for the canonical lookup.

    The prior local ancestor-walk implementation duplicated worktree's logic
    and missed two real edge cases: GIT_DIR env override and submodule .git
    files. Delegating eliminates the drift risk paired with the (now-resolved)
    glob-translator dup (debt 8ccf898d97d3). worktree.resolve_git_root shells
    `git rev-parse --show-toplevel` with per-cwd caching, so the runtime cost
    is one subprocess per unique cwd per process.
    """
    root = worktree.resolve_git_root(os.getcwd())
    return Path(root) if root else None


def _auto_include_sister_tests(
    data: dict,
    layout: "sister_tests.TestLayout",
    project_root: Path,
) -> None:
    """For each story in data['stories'], discover sister tests for the
    source paths in its file_domain and append new entries formatted as
    '<rel> — sister test for <src>'. Dedups against existing file_domain
    entries (every path the entry declares — em-dash, ASCII-dash, and
    comma-joined forms all parse identically via triage.entry_to_paths).
    Skips entries already marked as sisters (prevents sister-of-sister
    expansion). Mutates data in place. No SMM writes."""
    for story in data.get("stories", []):
        domain = story.get("file_domain")
        if not isinstance(domain, list):
            continue
        existing_paths: set[str] = set()
        for e in domain:
            if isinstance(e, str):
                existing_paths.update(triage.entry_to_paths(e))
        additions: list[str] = []
        for entry in list(domain):  # snapshot — don't iterate over a mutating list
            if not isinstance(entry, str):
                continue
            if " — sister test for " in entry:
                continue  # prevents sister-of-sister expansion
            for src in triage.entry_to_paths(entry):
                if not src:
                    continue
                try:
                    sisters = sister_tests.discover_sister_tests(
                        src, layout, project_root
                    )
                except ValueError:
                    continue  # bad source path; skip silently (validator owns shape)
                for sister in sisters:
                    if sister in existing_paths:
                        continue
                    additions.append(f"{sister} — sister test for {src}")
                    existing_paths.add(sister)
        domain.extend(additions)


def save(data: dict, smm_dir: Path) -> None:
    """Atomic write only. No sister-test discovery, no milestone transition,
    no accept-marker handling. Symmetry helper exposing the side-effect-free
    write path that run() composes; status-flip callers (sprint_cli._cmd_edit_story,
    /xp-accept, /xp-schedule) reach sprint_store directly via store.edit_story /
    store.update_story_status — both routes produce the same atomic write
    without firing run()'s side-effect bundle. Kept for symmetry with run()
    and as a test surface for behaviors that need to lock the bypass.
    See plan-review concern e7b72bd57c84 for the impact-zone constraint."""
    sprint_store.save_sprint(smm_dir, data)


def run(data: dict, smm_dir: Path) -> None:
    """Full sprint-mutation pipeline: sister-test discovery + atomic save
    + milestone transition + accept-marker handling. Use for structural
    sprint mutations (sprint_cli._cmd_create, _cmd_add_story).

    Args:
        data: Sprint data dict (validated by sprint_store).
        smm_dir: SMM directory path.
    """
    accept_marker = smm_dir / marker_names.ACCEPT
    accept_marker_existed = accept_marker.exists()

    # Sister-test auto-inclusion + Q1(b) soft-warn (story-004). Both
    # the "layout unresolved" and "project root not found" paths surface
    # through the same once-per-session marker with an honest reason —
    # silently skipping the project-root case (the prior shape: else
    # attached to `if layout`) left customers with no signal when
    # save_sprint ran from a tmpfs / non-git cwd.
    layout = _resolve_layout(smm_dir)
    if layout is None:
        _warn_sister_skip_once(
            smm_dir,
            "system_context.test_layout is unset, convention='unknown', or"
            " resolves to no rules",
        )
    else:
        project_root = _resolve_project_root()
        if project_root is None:
            _warn_sister_skip_once(
                smm_dir,
                "no project root found from cwd (no .git/ ancestor)",
            )
        else:
            _auto_include_sister_tests(data, layout, project_root)

    save(data, smm_dir)

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

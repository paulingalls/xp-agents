#!/usr/bin/env python3
"""Save sprint: full sprint-mutation pipeline (atomic write + side effects).

Engine-layer home for the sprint-mutation pipeline (relocated from the
xp-sprint-start skill in sprint-108 M1). Driven by sprint_cli's structural
subcommands (create, add-story); reached indirectly by xp-sprint-start,
xp-work-selection, and xp-accept. After writing sprint.json it:

- Clears the .needs-sprint marker if sprint now has active stories.
- If the .accept marker was present and no in-progress stories remain,
  treats this as acceptance completion: clears .accept, records an
  iteration_complete status event, and — if the sprint is now complete —
  prints a sprint-review nudge to stdout for the main agent to see.

Usage:
    echo '<json>' | python3 sprint_save.py --smm-dir DIR
"""

import argparse
import contextlib
import copy
import json
import os
import re
import sys
from pathlib import Path

# This module lives in smm/, so smm/ is always on sys.path before it is imported
# (own dir when run as a script; inserted by every cross-dir importer). Only the
# scripts/ insert is load-bearing — for _common, concerns, identity, etc.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import concerns  # noqa: E402
import execution_plan_store  # noqa: E402
import file_domain_lock  # noqa: E402
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
    '<rel> — sister test for <src>'. Skips entries already marked as sisters
    (prevents sister-of-sister expansion). Mutates data in place. No SMM writes.

    `authored` spans EVERY story and holds only the paths a planner explicitly
    wrote (entries WITHOUT the sister marker). A test file any story authored
    is that story's, full stop — never inject it into another. Seeding from
    authored paths (not previously auto-included ones) is deliberate: a
    genuinely-contested sister — one NO story authored, that a stem match
    (foo.py / foo_tools.py) resolves for two stories — is injected into BOTH,
    where the collision gate surfaces it as the tool error it is. That is the
    remedy its message prints; picking a single "winner" by list order could
    silently deny the sister to the story whose source actually covers it.

    Per-story idempotency: sister entries persist to sprint.json and are
    re-fed here on the next run(), so a path already present in a story's own
    domain (authored or a prior sister) is never re-appended.
    """
    stories = [s for s in data.get("stories", []) if isinstance(s, dict)]
    parsed: list[tuple[list[str], list[tuple[str, list[str]]], set[str]]] = []
    authored: set[str] = set()
    for story in stories:
        domain = story.get("file_domain")
        if not isinstance(domain, list):
            continue
        entries: list[tuple[str, list[str]]] = []
        own: set[str] = set()
        for e in domain:
            if isinstance(e, str):
                paths = triage.entry_to_paths(e)
                own.update(paths)
                if file_domain_lock.SISTER_TEST_MARKER not in e:
                    authored.update(paths)
                entries.append((e, paths))
        parsed.append((domain, entries, own))

    for domain, entries, own in parsed:
        additions: list[str] = []
        for entry, srcs in entries:
            if file_domain_lock.SISTER_TEST_MARKER in entry:
                continue  # prevents sister-of-sister expansion
            for src in srcs:
                if not src:
                    continue
                try:
                    sisters = sister_tests.discover_sister_tests(
                        src, layout, project_root
                    )
                except ValueError:
                    continue  # bad source path; skip silently (validator owns shape)
                for sister in sisters:
                    # Skip if any story authored it (never steal an authored
                    # test) or it is already in THIS story's domain (idempotency
                    # across re-feeds). A contested sister no one authored is
                    # NOT skipped here — it lands in every claiming story and
                    # the collision gate catches it.
                    if sister in authored or sister in own:
                        continue
                    additions.append(
                        f"{sister}{file_domain_lock.SISTER_TEST_MARKER}{src}"
                    )
                    own.add(sister)
        domain.extend(additions)


def introduced_collisions(
    data: dict, smm_dir: Path, *, current_expanded: bool = False
) -> dict[str, list[dict]]:
    """Collisions in `data` that THIS write is responsible for.

    Public (not `_`-prefixed) because it is an intentional cross-module reuse
    point: `sprint_store.edit_story` calls it to gate edits with run()'s exact
    this-write-only semantics without re-implementing them. A rename would break
    that gate — the public name signals the dependency.

    A collision is 'introduced' iff its set of colliding stories at a path GREW
    versus the on-disk baseline. Both the baseline and the write-in-hand are
    sister-expanded the same way run() expands (read-only, on deep copies) and
    run through `collision_report`; a path is attributed to this write when its
    current colliding-story set is NOT a subset of the baseline's. This attributes
    every fault source uniformly — a new/changed file_domain, a dependency edit
    that makes two shared-path stories concurrent (concurrency is not a domain
    diff), and a sister-test collision — while a collision present-in-both (a
    pre-existing one, unchanged by this write) is never blocked. Expanding BOTH
    sides identically is load-bearing: it keeps a story last persisted via
    edit-story (unexpanded on disk) from reading as 'touched' and falsely
    blocking an unrelated edit.

    Side-effect-free: never writes sprint.json, never fires the sister soft-warn
    (that stays run()'s job) — `edit_story` relies on this to keep its save()
    (not run()) semantics.

    `current_expanded=True` tells this function that `data` is ALREADY
    sister-expanded, so it skips re-expanding the current side. run() passes it:
    run() expands `data` in place (and persists that copy) before calling here,
    so a second expansion would re-glob the filesystem over every story's domain
    for an identical, idempotent result. edit_story passes RAW data and keeps the
    default (False), relying on this function to own the current-side expansion.
    The baseline is always expanded — that read is this function's own work.
    """
    layout = _resolve_layout(smm_dir)
    project_root = _resolve_project_root() if layout is not None else None

    def _expanded_report(sprint: dict) -> dict[str, list[dict]]:
        view = copy.deepcopy(sprint)  # _auto_include_sister_tests mutates in place
        if layout is not None and project_root is not None:
            _auto_include_sister_tests(view, layout, project_root)
        return file_domain_lock.collision_report(view)

    current_report = (
        file_domain_lock.collision_report(data)
        if current_expanded
        else _expanded_report(data)
    )
    baseline = sprint_store.load_sprint(smm_dir)
    if baseline is None:
        # First create: nothing on disk, so every current collision is our fault.
        return current_report
    baseline_report = _expanded_report(baseline)

    introduced: dict[str, list[dict]] = {}
    for path, claims in current_report.items():
        cur_ids = {c["story_id"] for c in claims}
        base_ids = {c["story_id"] for c in baseline_report.get(path, [])}
        if not cur_ids <= base_ids:  # colliding-story set grew -> introduced here
            introduced[path] = claims
    return introduced


def save(data: dict, smm_dir: Path) -> None:
    """Atomic write only. No sister-test discovery, no milestone transition,
    no accept-marker handling. Symmetry helper exposing the side-effect-free
    write path that run() composes; status-flip callers
    (sprint_cli_mutate._cmd_edit_story, /xp-accept, /xp-schedule) reach
    sprint_store directly via store.edit_story /
    store.update_story_status — both routes produce the same atomic write
    without firing run()'s side-effect bundle. Kept for symmetry with run()
    and as a test surface for behaviors that need to lock the bypass.
    See plan-review concern e7b72bd57c84 for the impact-zone constraint."""
    sprint_store.save_sprint(smm_dir, data)


def run(data: dict, smm_dir: Path) -> None:
    """Full sprint-mutation pipeline: sister-test discovery + atomic save
    + milestone transition + accept-marker handling. Use for structural
    sprint mutations (sprint_cli_mutate._cmd_create, _cmd_add_story).

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
    # sprint_save ran from a tmpfs / non-git cwd.
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

    # Enforce file_domain ownership on every structural write. Raising here —
    # after auto-include, before save() — leaves sprint.json untouched, and
    # skips the milestone transition and accept-marker handling below, which
    # would otherwise fire for a sprint that was never written. Both CLI
    # surfaces (create, add-story) already map ValueError to rc 1.
    #
    # A collision means two stories that could run CONCURRENTLY claim one path;
    # a story extending the file of a story it depends on is legal. Malformed
    # (non-dict) stories are skipped by collision_report and fall through to
    # save()'s schema validator, which owns shape.
    #
    # Only block on collisions THIS write is responsible for. edit-story flips
    # bypass run() (impact-zone constraint), so a collision can already sit on
    # disk between two other stories; re-checking the whole sprint on every
    # add-story would then refuse an unrelated, disjoint, schema-valid new
    # story — breaking the "a clean new story can always be added" guarantee.
    # introduced_collisions attributes a path only when its colliding-story set
    # GREW versus the on-disk baseline (both sides sister-expanded) — a
    # pre-existing collision unchanged by this write is never re-blocked.
    # data was sister-expanded in place above (when a layout+root resolved), so
    # tell introduced_collisions not to re-expand the current side — avoids a
    # redundant second filesystem glob over every story's domain.
    introduced = introduced_collisions(data, smm_dir, current_expanded=True)
    if introduced:
        raise ValueError(file_domain_lock.format_collision_report(introduced))

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
    # run() raises ValueError on a file_domain collision (and other validation
    # failures). Surface it as a clean, formatted message + exit 1 — parity with
    # sprint_cli_mutate, which wraps run() the same way — rather than letting the
    # collision report escape as an uncaught traceback with internal stack frames.
    try:
        run(data, args.smm_dir)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

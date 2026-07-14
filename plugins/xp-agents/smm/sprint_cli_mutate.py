#!/usr/bin/env python3
"""Structural-mutation handlers for the sprint CLI.

The subcommands here (create, add-story, update-story, update-story-if,
edit-story, build-capstone, update-story-branch) mutate sprint.json.
sprint_cli.py imports them and wires them into its argparse dispatch
table; the read-only query handlers and validate-domain stay there.

build-capstone is the one exception to "mutate sprint.json" — it only
prints a story dict to stdout — but it lives here anyway since it's a
structural-mutation payload the skill pipes into add-story.

Split out of sprint_cli.py in sprint-108 M1 to keep both modules under
the 500-line cap (decision d027fe5c9066). One-directional import:
sprint_cli -> sprint_cli_mutate -> sprint_store. No triage dependency —
that belongs to validate-domain, which stays in sprint_cli.py.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# sprint_save is imported lazily inside _cmd_create / _cmd_add_story (the
# only callers that need it) so importing this module for the cheaper
# mutation subcommands (update-story, edit-story, build-capstone, ...)
# doesn't pay the cost of loading sister_tests + BUILTIN_LAYOUTS
# construction. sprint_save is an engine-layer sibling in smm/ (relocated
# in sprint-108 M1) — no skill sys.path insert needed; structural-mutation
# subcommands drive its full pipeline (sister discovery + milestone
# transition + accept-marker handling), while status-only edits
# (_cmd_edit_story) bypass it via store.edit_story. build-capstone also
# imports lazily — system_context_store, inside _resolve_capstone_harness
# — but only on the path where --harness is omitted; an explicit --harness
# skips system_context entirely.
import sprint_store as store
from _append_impl import append_event
from event_builder import generate_id
from event_schema import EVENT_TYPE_DEBT


def _preserve_branch_names(incoming: dict, smm_dir: Path) -> None:
    """Carry recorded branch names across a same-id re-create (the re-slice).

    `create` writes its payload verbatim, and the sprint-start payload names no
    branch at either level — so re-creating the SAME sprint (to rewrite a goal
    or drop a story: the only tool for either, since nothing archives and there
    is no remove-story) erased the sprint's branch and every story's. The base
    resolver then could not find the sprint branch and fell back to the primary
    branch, and live teammate branches read as orphans.

    Keyed on sprint_id, never on file existence. A DIFFERENT id is the rollover
    — the next sprint's create deliberately overwrites the current file in
    place — and carried-forward stories are RENUMBERED there, so a branch
    carried across ids would name someone else's branch. Different id carries
    nothing.

    Fill-when-absent, never clobber: an incoming payload that names a branch
    wins, or a deliberate rename would be silently reverted. A story the
    re-slice drops loses its branch with it; the preserve carries branches for
    SURVIVING stories, it does not reinstate the old story list.

    The load is guarded because `create` is the repair path for a sprint file
    that can no longer be loaded — load_sprint raises SprintCorruptError on all
    three unusable-content causes: undecodable bytes, malformed JSON, and
    schema-validation failure (e.g. a file written before a schema change).
    An unguarded load here would turn the only repair tool into a traceback, so
    a failed read carries nothing, says so, and still writes. sprint_save's
    collision baseline fails open for the same reason — both legs are needed to
    keep the repair path open, and both rely on load_sprint normalizing every
    corruption cause to the one type they catch.

    Forward-coupling — Milestone 5 adds sprint ARCHIVING to _cmd_create. Two
    rules, both keyed on the same sprint_id comparison this function makes:
    archiving must not move or clear sprint.json BEFORE this preserve reads it
    (the preserve would find nothing and silently re-drop every branch), and it
    must fire only on a DIFFERENT sprint_id — the rollover. A same-id re-slice
    is not a completed sprint and must be neither archived nor cleared.
    test_same_sprint_id_carries_every_branch_name enforces both: an
    archive-before-preserve ordering, or an archive on a same-id create, fails
    it.
    """
    try:
        recorded = store.load_sprint(smm_dir)
    except (store.SprintCorruptError, OSError) as exc:
        print(
            f"WARN: existing sprint.json could not be read ({exc}); "
            "creating fresh — no branch names carried forward.",
            file=sys.stderr,
        )
        return

    if recorded is None or recorded.get("sprint_id") != incoming.get("sprint_id"):
        return

    carried: list[str] = []
    if not incoming.get("branch_name") and recorded.get("branch_name"):
        incoming["branch_name"] = recorded["branch_name"]
        carried.append(f"sprint={recorded['branch_name']}")

    recorded_stories = recorded.get("stories")
    prior_branch = {
        s.get("id"): s.get("branch_name")
        for s in (recorded_stories if isinstance(recorded_stories, list) else [])
        if isinstance(s, dict)
    }
    incoming_stories = incoming.get("stories")
    for story in incoming_stories if isinstance(incoming_stories, list) else []:
        if not isinstance(story, dict) or story.get("branch_name"):
            continue
        branch = prior_branch.get(story.get("id"))
        if branch:
            story["branch_name"] = branch
            carried.append(f"{story['id']}={branch}")

    if carried:
        print(
            f"Re-slicing {incoming.get('sprint_id')} — carried forward: "
            f"{', '.join(carried)}",
            file=sys.stderr,
        )


def _cmd_create(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    if isinstance(data, dict):
        # Before the write, not inside sprint_save.run(): add-story also routes
        # through run() on an existing sprint, and run()'s same-id overwrite is
        # pinned at that layer. The re-slice is a CLI-level concern.
        _preserve_branch_names(data, args.smm_dir)
    import sprint_save

    try:
        # Structural mutation — route through full pipeline (sister discovery
        # + milestone transition + accept-marker handling).
        sprint_save.run(data, args.smm_dir)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_add_story(args: argparse.Namespace) -> int:
    # Unlike create, add-story cannot repair an unreadable sprint — it appends
    # to the recorded story list, so it needs that list. But it fails the way
    # every other handler does (message + rc 1), not with a stack trace that
    # buries the actionable next step: `create` is the repair path.
    try:
        sprint = store.load_sprint(args.smm_dir)
    except (store.SprintCorruptError, OSError) as exc:
        print(
            f"Existing sprint.json could not be read ({exc}). Cannot add a story "
            "to a sprint that will not load — re-create the sprint to repair it.",
            file=sys.stderr,
        )
        return 1
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1
    raw = sys.stdin.read()
    try:
        story = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    new_id = story.get("id") if isinstance(story, dict) else None
    if new_id and any(s.get("id") == new_id for s in sprint.get("stories", [])):
        print(
            f"Duplicate story id: {new_id!r} already exists in sprint "
            f"{sprint.get('sprint_id', '<unknown>')}. add-story is idempotent "
            "on the id field — use edit-story to mutate an existing story.",
            file=sys.stderr,
        )
        return 1
    sprint["stories"].append(story)
    import sprint_save

    try:
        # Structural mutation (new story) — route through full pipeline.
        # Dup-id guard above stays AHEAD of run() per locked decision
        # (story-003 close): a dup never triggers run()'s side effects.
        sprint_save.run(sprint, args.smm_dir)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _record_forced_unmerged(smm_dir: Path, story_id: str, reason: str) -> None:
    """Write the debt event that PAYS for a merge-gate bypass.

    Raises on failure, and the caller lets that abort the mark-done: an override
    nobody can see is exactly the silent mark-done-past-a-failed-merge this gate
    exists to stop. The record is the price of the bypass, so it is taken FIRST —
    a recorded bypass whose status write then failed is harmless noise, while a
    status write whose record failed is the bug wearing the fix's clothes.
    """
    append_event(
        smm_dir,
        {
            "id": generate_id(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": EVENT_TYPE_DEBT,
            "agent_id": "sprint_cli",
            "content": (
                f"MERGE GATE BYPASSED for {story_id}: marked done via "
                f'--force-unmerged, with no verified merge. Reason: "{reason}". '
                f"Verify the work actually reached the base branch."
            ),
            "files": ["sprint.json"],
            "schema_version": 1,
        },
    )


def _cmd_update_story(args: argparse.Namespace) -> int:
    reason = getattr(args, "force_unmerged", None)

    if reason is not None:
        if not reason.strip():
            print(
                "Error: --force-unmerged requires a non-empty reason — an empty one "
                "is a silent bypass wearing an accountable one's costume.",
                file=sys.stderr,
            )
            return 1
        if args.status != "done":
            print(
                f"Error: --force-unmerged only applies to `done` (got "
                f"{args.status!r}); the merge gate fires nowhere else.",
                file=sys.stderr,
            )
            return 1
        try:
            _record_forced_unmerged(args.smm_dir, args.story_id, reason.strip())
        except (OSError, ValueError) as exc:
            print(f"Error: bypass not recorded ({exc}); refusing.", file=sys.stderr)
            return 1

    try:
        store.update_story_status(args.smm_dir, args.story_id, args.status)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_update_story_if(args: argparse.Namespace) -> int:
    """Atomic compare-and-swap on story status.

    Exits 0 when the on-disk status matched --expected and the write
    succeeded; 1 when the status differed (no-op, file untouched);
    2 on validation/missing-id/missing-sprint errors. Callers can
    distinguish "lost the race" (rc=1) from "bad input" (rc=2).
    """
    try:
        ok = store.update_story_status_if(
            args.smm_dir, args.story_id, expected=args.expected, new=args.new
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0 if ok else 1


def _cmd_edit_story(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        updates = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    # Status/metadata edits intentionally bypass sprint_save.run(). /xp-accept
    # and /xp-schedule drive edit-story for status flips and execution_mode
    # writes; firing the full run() pipeline on every flip would re-walk
    # sister discovery and re-fire milestone transition on every accept
    # (impact-zone constraint per plan-review e7b72bd57c84). store.edit_story
    # already routes through sprint_store.save_sprint directly — the same
    # atomic-write that sprint_save.save() wraps — so the architectural split
    # is preserved without duplicating the isinstance / immutable-fields /
    # load-find-update guards here.
    try:
        store.edit_story(args.smm_dir, args.story_id, updates)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_set_executor(args: argparse.Namespace) -> int:
    """Persist a story's executor_model / executor_effort — value-or-null, but
    only for the flags that are PROVIDED.

    A provided flag (even empty) writes the field: a real tier/effort as itself,
    an empty string as null. An OMITTED flag leaves the field untouched. That
    asymmetry is deliberate: executor_effort has a single writer (/xp-assign), so
    Step 0 clears its latch by passing `--effort ""` on the no-recommendation
    path (debt c93c9745f5ed); executor_model has TWO writers — /xp-assign AND a
    deliberate /xp-schedule per-story pre-seed — so Step 0 OMITS --model on that
    same path to preserve the pre-seed rather than clobber it.

    Accepted tradeoff (chosen over clearing): because the field can't distinguish
    a /xp-schedule pre-seed from a tier a prior /xp-assign wrote, preserving it on
    the inherit path also lets a prior concrete-tier assignment persist across a
    rare tier->inherit RE-assignment. The pre-seed (a documented feature) wins
    over that edge; a full fix would need separate provenance state.

    Reuses store.edit_story's shallow-merge; the schema accepts null for both
    fields and validates a non-null model/effort against its known vocabulary.
    """
    updates = {}
    if args.model is not None:
        updates["executor_model"] = args.model or None
    if args.effort is not None:
        updates["executor_effort"] = args.effort or None
    if not updates:
        return 0
    try:
        store.edit_story(args.smm_dir, args.story_id, updates)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _resolve_capstone_harness(surfaces: list[str], smm_dir: Path) -> str | None:
    """Resolve acceptance_execution.type from the capstone's OWN surfaces.

    Looks up each of `surfaces` (not every surface in the project — the
    capstone might span only some of them) against system_context's
    declared acceptance_surfaces. A single agreed harness wins; surfaces
    that disagree (a legitimate case in a polyglot repo — e.g. a TS
    surface on vitest and a Python surface on pytest) or that declare no
    harness fall back to None, which build_capstone_story renders as a
    placeholder rather than guessing a language.

    Never raises: a missing, corrupt, or symlinked system_context.json
    degrades to None + a stderr warning, mirroring the best-effort
    contract of system_context_store.acceptance_surface_names. Lazily
    imports system_context_store — only reached when --harness is absent.
    """
    if not surfaces:
        return None
    import system_context_store

    try:
        doc = system_context_store.load_system_context(smm_dir)
    except (ValueError, OSError) as exc:
        print(
            f"WARN: system_context.json could not be read ({exc}); "
            "capstone acceptance_execution.type left as a placeholder.",
            file=sys.stderr,
        )
        return None
    if doc is None:
        return None

    harness_by_surface: dict[str, str] = {
        s["name"]: s["harness"]
        for s in doc.get("acceptance_surfaces", [])
        if isinstance(s, dict)
        and isinstance(s.get("name"), str)
        and isinstance(s.get("harness"), str)
    }
    harnesses = {harness_by_surface[s] for s in surfaces if s in harness_by_surface}
    if len(harnesses) == 1:
        return next(iter(harnesses))
    if len(harnesses) > 1:
        print(
            f"WARN: capstone surfaces {surfaces} declare different harnesses "
            f"({sorted(harnesses)}); leaving acceptance_execution.type as a "
            "placeholder rather than guessing.",
            file=sys.stderr,
        )
    return None


def _cmd_build_capstone(args: argparse.Namespace) -> int:
    """Print a deterministic capstone story as JSON on stdout.

    Does not read or write sprint.json — the skill pipes the output into
    `add-story`. Comma-separated --surfaces and --depends-on are split
    into lists; empty strings yield empty lists.

    When --harness is omitted, resolves acceptance_execution.type from
    the capstone's own --surfaces via system_context's acceptance_surfaces
    (see _resolve_capstone_harness) — a single agreed harness wins,
    disagreement or absence degrades to a placeholder. An explicit
    --harness always wins over resolution.
    """

    def _split(raw: str) -> list[str]:
        return [p for p in (s.strip() for s in raw.split(",")) if p]

    surfaces = _split(args.surfaces)
    harness = args.harness or _resolve_capstone_harness(surfaces, args.smm_dir)

    story = store.build_capstone_story(
        args.story_id,
        args.milestone,
        surfaces,
        _split(args.depends_on),
        milestone_ref=args.milestone_ref,
        harness=harness,
    )
    print(json.dumps(story, indent=2))
    return 0


def _cmd_update_story_branch(args: argparse.Namespace) -> int:
    try:
        store.set_story_branch(args.smm_dir, args.story_id, args.branch_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0

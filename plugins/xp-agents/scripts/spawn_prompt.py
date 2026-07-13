#!/usr/bin/env python3
"""The teammate's prompt: is it the right one, and what gets prepended to it.

Extracted from spawn_teammate.py (which owns command construction, worktree and
marker lifecycle, and the story promote) to keep both files under the size cap.
One cohesive concern — the prompt text handed to the child — in two halves:
refusing a prompt that belongs to a DIFFERENT story, and building the worktree
preamble that leads the one we accept.

Why the guard exists: a prompt file outlives the story it was written for, and
story ids repeat every sprint, so the prompt sitting at worktree-story-003's path
is not necessarily THIS story-003's prompt. The sprint-scoped path (see
teammate_runner._project_dir) makes a cross-sprint collision unreachable; this
guard catches whatever reaches the path anyway (a prompt re-used inside one
sprint, a hand-passed --prompt-file), and it runs before spawn_teammate takes a
single side effect.

Self-contained — pure text in, text out, no SMM/plugin imports and no I/O beyond
reading the prompt file, so it needs no sys.path bootstrap (same property
teammate_runner holds, for the same reason). The sprint read that names the
namespace stays in spawn_teammate, where sprint_store is already a dependency.
"""

from pathlib import Path

# The refusal names itself with this token so the lead actually SEES it. The
# spawn is never run bare: /xp-assign pipes it (2>&1) into teammate_output_filter,
# which keeps only the non-JSON lines it recognises as diagnostics and drops the
# rest — so a refusal it cannot match reaches the lead as "No result event",
# without the path, the branch, or the remedy. The filter imports this constant
# rather than re-spelling the string, so the two ends cannot drift apart.
REFUSAL_PREFIX = "REFUSING TO SPAWN"


def worktree_preamble(wt_path: str) -> str:
    """Return the worktree-context preamble injected before the teammate prompt.

    Names the worktree path explicitly and the main-repo path derived from
    it, then instructs the teammate to re-root any absolute path under the
    main repo to the worktree. The preamble lands FIRST in the teammate's
    stdin so its rule is established before the prompt body's potentially
    misleading paths.

    Worktree layout (standardized by worktree.worktree_path):
    `<main_repo>/.claude/worktrees/<name>`.
    """
    main_repo = str(Path(wt_path).parent.parent.parent)
    return (
        "## Worktree Context (injected by spawn_teammate.py)\n"
        "\n"
        f"Your current working directory is the worktree at: `{wt_path}`\n"
        f"The main repository checkout is at:               `{main_repo}`\n"
        "\n"
        "All file paths in the prompt body that follows are intended to be "
        "RELATIVE to this worktree, even when they appear written as absolute "
        f"paths starting with `{main_repo}/`. Re-root any such absolute path "
        "to your worktree before reading or editing files. "
        f"Example: `{main_repo}/some/sub/path.py` becomes "
        f"`{wt_path}/some/sub/path.py`.\n"
        "\n"
        "The SMM directory (passed via $SMM_DIR) is intentionally OUTSIDE the "
        "worktree — use it unmodified.\n"
        "\n"
        "---\n"
        "\n"
    )


def load_prompt_for_story(
    prompt_file: str | Path,
    *,
    branch: str | None,
    story_id: str | None,
) -> str:
    """Read the teammate prompt, refusing one written for a DIFFERENT story.

    Nothing invalidates a prompt file, and story ids repeat every sprint, so the
    prompt sitting at this teammate's path is not necessarily the prompt for the
    story we are spawning. Assert it names the story before we act on it.

    Checked against the BRANCH, not the story id: sprint-116's story-003 prompt
    and sprint-117's story-003 prompt BOTH contain "story-003", so an id check
    passes on precisely the stale prompt that is the bug. Only the slug
    (story-003-perf-timers vs story-003-tools-remember-what-was-adopted) tells
    them apart, and the branch is id + slug — it is also the branch the worktree
    is actually cut on, so it is the thing that must match. It arrives on the
    command line (/xp-assign passes --branch), so this costs no I/O and takes no
    dependency on sprint.json.

    Without --branch (--in-place, or a pre-branch stage) we fall back to the
    story id. That check is WEAKER — it cannot tell two sprints' story-003
    apart — and the refusal message says so rather than implying a guarantee it
    cannot make. The sprint-scoped path (leg 1) is what covers that gap: a prompt
    from another sprint is not at this path to begin with.

    With neither branch nor story id (ad-hoc teammate) there is nothing to assert
    against, so the prompt is taken as-is.

    Refusal is loud and non-zero, and NEVER a silent regeneration: a rewrite here
    would paper over exactly the collision the lead must see. The stale file is
    left untouched for inspection.

    Called BEFORE any side effect — it is a pure read, and a guard that fires
    after create_worktree/claim/write_story_assignment leaves an orphan worktree
    and a clobbered name-keyed assignment behind on every refusal.
    """
    path = Path(prompt_file)
    try:
        text = path.read_text()
    except OSError as exc:
        raise SystemExit(
            f"{REFUSAL_PREFIX} {story_id or branch or path.name}: cannot read the "
            f"prompt at {path} ({exc}). Write the prompt for THIS story to that "
            f"path (--print-prompt-path prints it) and re-run."
        ) from exc

    target = branch or story_id
    if target is None or target in text:
        return text

    weaker = (
        ""
        if branch
        else (
            " (No --branch, so this is only a story-ID check — it cannot tell two "
            "sprints' same-numbered stories apart. Pass --branch for the strong "
            "check.)"
        )
    )
    raise SystemExit(
        f"{REFUSAL_PREFIX} {story_id or target}: the prompt at {path} does not "
        f"name {target!r}, so it was written for a DIFFERENT story — story ids "
        f"repeat every sprint and nothing invalidates a stale prompt. Spawning "
        f"would run the teammate on the wrong story.{weaker} Nothing was created "
        f"or modified; the prompt is left in place. Write this story's prompt to "
        f"that path (it is not regenerated for you) and re-run."
    )

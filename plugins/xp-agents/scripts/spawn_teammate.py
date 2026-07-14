#!/usr/bin/env python3
"""Spawn a CLI teammate — in a git worktree, or in the main checkout.

Launches an independent claude -p process that inherits $SMM_DIR so its hooks
write to the lead's SMM. Called by /xp-assign via Bash with run_in_background.
Default: create a git worktree (parallel isolation). With --in-place: run in the
main checkout on the already-checked-out story branch (solo delegation — a single
unit of work needs no isolation); skips the worktree, the worktree preamble, and
the rc=0 promote-to-reviewing.

Usage:
    python3 spawn_teammate.py \
        --name worktree-story-001 \
        --smm-dir /path/to/smm \
        [--prompt-file /path/to/prompt.txt] \
        [--story-id story-001] \
        [--branch paulingalls/story-001-foo] \
        [--model sonnet] \
        [--plugin-dir /path/to/plugins/xp-agents]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# `worktree` import is the side-effect bootstrap that adds smm/ to
# sys.path (mirrors scripts/_common.py); pinned first via `isort: split`
# so the `sprint_store` import below resolves.
import worktree  # isort: split

import identity
import in_place_marker
import sprint_store
import tier_wire

# The prompt text (is this prompt ours, and what leads it) and the subprocess tee
# + liveness watchdog live in sibling leaf modules; keep the names importable here
# so callers (and their tests) still see spawn_teammate.run_with_tee /
# project_log_dir.
from spawn_prompt import load_prompt_for_story, worktree_preamble
from teammate_runner import (
    project_log_dir,
    project_prompt_path,
    run_with_tee,
    safe_name,
)


def resolve_sprint_id(smm_dir: str | Path) -> str | None:
    """Return the active sprint id, or None when there is no usable sprint.

    The sprint id namespaces this teammate's prompt and log files (see
    teammate_runner._project_dir): story ids repeat every sprint, so without it
    last sprint's story-003 prompt sits where this sprint's story-003 spawns
    from. Resolved HERE, once, and passed down to every path call — the leaf
    modules that own those paths (teammate_runner, spawn_prompt) are both
    documented as importing no SMM modules, and reading the sprint inside either
    would void that. This module already imports sprint_store.

    The read is advisory (fail-open): spawn_teammate legitimately runs with no
    sprint at all (free branch, ad-hoc teammate), and a corrupt sprint.json must
    not brick every spawn — both degrade to the project-only namespace, exactly
    as before this scoping existed. That is safe because the degraded answer is
    the SAME for --print-prompt-path and for the spawn (one function, one file),
    so the lead and the teammate still meet at one path; and because loudness is
    delegated to a later, stricter step — load_prompt_for_story refuses a prompt
    that does not name the story's branch, however the path was resolved.
    """
    sprint = sprint_store.load_sprint_fail_open(Path(smm_dir))
    if sprint is None:
        return None
    sprint_id = sprint.get("sprint_id")
    return sprint_id if isinstance(sprint_id, str) and sprint_id else None


def cleanup_existing(name: str, cwd: str, *, owns_branch: bool = True) -> None:
    """Clear a stale worktree before (re)creating one at the same path.

    ``owns_branch`` decides whether the worktree's BRANCH dies with it, and it
    is the difference between an idempotent re-spawn and destroyed work:

    - True (spawn cut the branch itself, in the no-``branch=`` arm where
      ``worktree add -b <name>`` re-cuts it): force-delete it. A stale ref of
      the same name would otherwise block the re-add.
    - False (a branch was HANDED to ``create_worktree``): delete NOTHING. That
      branch was cut by /xp-assign and is where the teammate has been
      committing. Force-deleting it — which is what this did unconditionally —
      destroyed unmerged commits AND then failed the very next
      ``git worktree add <path> <branch>``, because the ref it was told to
      check out no longer existed.

    The branch was only HALF the story, and this is the other half. Sparing the
    branch spares what the teammate COMMITTED; the worktree DIRECTORY still went
    away under `--force`, taking everything it had not committed yet. A live
    teammate re-spawned under the same name lost its whole working tree, and the
    branch it was spared pointed at the last commit before the loss. The in-place
    path took an exclusive claim to stop exactly this (`claim_in_place_marker`);
    the worktree path had no check at all. `force=False` hands the decision to
    git, which refuses to remove a tree with modified or untracked files —
    covering the live teammate and the crashed-before-commit one alike.
    """
    if owns_branch:
        worktree.remove_worktree(name, cwd, force_branch=True)
    else:
        worktree.remove_worktree_dir(name, cwd, force=False)


def create_worktree(name: str, cwd: str, *, branch: str | None = None) -> str:
    """Create a git worktree for a teammate. Returns worktree path.

    When branch is provided, checks out that existing branch in the
    worktree instead of creating a new branch. Used by /xp-assign
    to place teammates on story branches — and spawn does not own that
    branch, so a stale worktree is cleared without touching it.
    """
    cleanup_existing(name, cwd, owns_branch=branch is None)

    wt = worktree.worktree_path(name, cwd)
    wt.parent.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt)

    if branch is not None:
        cmd = ["git", "worktree", "add", wt_path, branch]
    else:
        cmd = ["git", "worktree", "add", "-b", name, wt_path]
        current = identity.get_current_branch(cwd)
        if current:
            cmd.append(current)

    subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        check=True,
    )
    return wt_path


_ALLOWED_TOOLS = "Read,Write,Edit,Bash,Grep,Glob,Skill,Agent"


def build_command(
    name: str,
    model: str | None = None,
    plugin_dir: str | None = None,
    effort: str | None = None,
) -> list[str]:
    """Construct the claude -p command for a teammate.

    Prompt is piped via stdin, not passed as a CLI flag. When *model* is
    given, a --model flag selects the teammate's tier (e.g. sonnet for a
    delegated solo teammate); otherwise the claude -p default is inherited.

    When *plugin_dir* is given, a --plugin-dir flag loads that plugin into the
    headless teammate session. This is REQUIRED for the teammate to get the
    xp-agents skills, agents, and hooks: a worktree `claude -p` session does
    not apply the project-scoped marketplace enablement, so without
    --plugin-dir the plugin (and its full hook lifecycle) never loads.

    When *effort* is given, a --effort flag forwards the reasoning-effort
    level — but only when the resolved *model* is known to support it
    (tier_wire.effort_supported). Support is non-uniform across tiers (the
    cheapest tier rejects effort outright), so an unsupported model+effort
    pair is dropped with a stderr note rather than erroring the spawn: it
    fail-safes to the model default. When *model* is None the resolved tier
    is inherited from the orchestrator and unknown here, so effort is treated
    as unverifiable and dropped — never forward a param we can't confirm.
    """
    cmd = [
        "claude",
        "-p",
        "--name",
        name,
        "--dangerously-skip-permissions",
        "--allowedTools",
        _ALLOWED_TOOLS,
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]
    if model is not None:
        cmd += ["--model", model]
    if plugin_dir is not None:
        cmd += ["--plugin-dir", plugin_dir]
    if effort is not None:
        if model is None:
            sys.stderr.write(
                f"spawn_teammate: model inherited from orchestrator (unknown "
                f"here) — cannot verify effort {effort!r} support, dropping "
                f"--effort, using model default\n"
            )
        elif not tier_wire.effort_supported(model, effort):
            sys.stderr.write(
                f"spawn_teammate: model {model!r} does not support effort "
                f"{effort!r} — dropping --effort, using model default\n"
            )
        else:
            cmd += ["--effort", effort]
    return cmd


def write_story_assignment(smm_dir: Path, name: str, story_id: str | None) -> None:
    """Write story assignment file for commit attribution. No-op if story_id is None."""
    if story_id is None:
        return
    worktree.write_story_assignment(smm_dir, name, story_id)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Spawn a CLI teammate")
    parser.add_argument("--name", required=True)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument(
        "--prompt-file",
        required=False,
        default=None,
        help=(
            "Path to the teammate prompt. OPTIONAL: when omitted or empty, "
            "spawn resolves the deterministic project_prompt_path(--smm-dir, "
            "--name) itself — the same path --print-prompt-path returns. This "
            "avoids threading a queried path across separate Bash tool calls "
            "(shell state does not persist), which handed spawn an empty value."
        ),
    )
    parser.add_argument(
        "--print-log-path",
        action="store_true",
        help=(
            "Print the deterministic project-scoped forensic-log path for "
            "--name and exit 0 WITHOUT spawning. /xp-assign calls this to "
            "surface the live `tail -f` target to the lead — the path matches "
            "run_with_tee's own log so a tailer watches the file the tee writes."
        ),
    )
    parser.add_argument(
        "--print-prompt-path",
        action="store_true",
        help=(
            "Print the deterministic project-scoped prompt-file path for --name "
            "(creating its parent dir) and exit 0 WITHOUT spawning. /xp-assign "
            "calls this so the orchestrator writes the teammate prompt to a "
            "per-project location instead of a flat /tmp/prompt-<id>.txt that "
            "collides across concurrent sessions."
        ),
    )
    parser.add_argument("--story-id", default=None)
    parser.add_argument("--branch", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--plugin-dir", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help=(
            "Run the teammate in the main checkout (solo delegation) instead of "
            "a worktree: skip create_worktree + the worktree preamble, run in the "
            "process cwd, and skip the rc=0 promote-to-reviewing (the story stays "
            "in-progress/solo for /xp-accept's solo path)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Parse args and spawn the teammate."""
    args = parse_args(argv)
    # FIRST, before every path this name is joined into. `--name` is CLI input
    # authored by /xp-assign, and it lands unescaped in FIVE paths: the prompt
    # file, the tee log, the worktree directory, `.story-assignment-<name>` and
    # the in-place marker. The sprint id was already sanitized against traversal
    # for exactly this reason (teammate_runner._path_token) and the name — right
    # beside it in the same directory — was not, so a `../` in it walked out of
    # the namespace and, for the SMM-dir markers, out of the SMM dir. Refusing at
    # the boundary covers all five with one guard; the two leaf path builders
    # keep their own (teammate_runner.safe_name) so they cannot be called
    # unguarded from elsewhere.
    name = safe_name(args.name)

    # The namespace token for BOTH the prompt and the log. Resolved once, here,
    # and threaded through every path call below — the queries included, so what
    # --print-prompt-path hands the lead is the file the spawn actually reads.
    sprint_id = resolve_sprint_id(args.smm_dir)

    # Pure query: print the live forensic-log path the tee will write to, and
    # exit before any worktree/spawn side effect. /xp-assign surfaces this as
    # the mid-flight `tail -f` target.
    if args.print_log_path:
        print(project_log_dir(args.smm_dir, sprint_id=sprint_id) / f"{name}.log")
        return

    # Pure query: print the per-project prompt-file path and exit before any
    # side effect. The orchestrator writes the prompt there BEFORE spawning, so
    # — unlike the log dir, which spawn_teammate mkdir's itself before the tee —
    # nothing else guarantees the dir exists; create it here (best-effort) so
    # the external writer can write regardless of how it writes.
    if args.print_prompt_path:
        prompt_path = project_prompt_path(args.smm_dir, name, sprint_id=sprint_id)
        # The external writer REQUIRES this dir (unlike the log dir, which
        # run_with_tee degrades around), so a mkdir failure must fail loud here
        # rather than print a path the writer will then fail to write to.
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        print(prompt_path)
        return

    # Resolve the prompt path ONCE. When --prompt-file is omitted or empty, use
    # the deterministic project_prompt_path (derivable from --name + --smm-dir
    # already in this command) so no queried value has to survive a separate
    # Bash tool call. Used everywhere the prompt is read/preserved/unlinked.
    prompt_file = args.prompt_file or str(
        project_prompt_path(args.smm_dir, name, sprint_id=sprint_id)
    )

    # FIRST — before the worktree, the marker claim, and the name-keyed story
    # assignment. Reading the prompt is pure, and refusing here is the only
    # placement that leaves NOTHING behind: a guard at the point of use (where
    # the prompt was previously read) would already have created an orphan
    # worktree, clobbered another teammate's .story-assignment, and claimed the
    # in-place name — on a spawn we then refuse.
    prompt_body = load_prompt_for_story(
        prompt_file, branch=args.branch, story_id=args.story_id
    )

    cwd = os.getcwd()
    # In-place (solo delegation): run in the main checkout on the already-
    # checked-out story branch — no worktree to isolate a single unit of work.
    # Worktree (parallel): isolate the teammate in .claude/worktrees/<name>.
    run_cwd = cwd if args.in_place else create_worktree(name, cwd, branch=args.branch)
    # --plugin-dir is a correctness-critical invariant: without it the headless
    # teammate loads none of the xp-agents skills/agents/hooks (ungated). Self-
    # resolve from CLAUDE_PLUGIN_ROOT when omitted so a caller that forgets the
    # flag can't silently re-spawn the plugin-less teammate this release fixes;
    # an explicit --plugin-dir still wins.
    plugin_dir = args.plugin_dir or os.environ.get("CLAUDE_PLUGIN_ROOT")
    cmd = build_command(name, args.model, plugin_dir, args.effort)

    env = os.environ.copy()
    env["SMM_DIR"] = args.smm_dir
    env[identity._XP_TEAMMATE_ENV] = name

    # In-place teammates share the main checkout, so their cwd carries no
    # worktree path marker — commit_handling recovers the name from the leaky
    # XP_TEAMMATE_NAME env instead. Write a lifetime-scoped marker so attribution
    # only trusts that env WHILE this child runs; a lead that later inherits a
    # leaked var has no live marker and falls through to the heuristics. Removed
    # in the finally below.
    #
    # The marker is written TWICE, by us both times. Now, because it must exist
    # before the child's first hook runs or the child loses the identity race —
    # but at this point only our pid exists to record. Then again from on_spawn
    # below, once the child exists: WE are only a tee around it, and a SIGKILL up
    # here does not propagate to it (see run_with_tee), so the child's pid is the
    # one that must keep the marker alive when we die. Recording only ours would
    # let the probe reap a LIVE teammate's marker.
    combined_path: str | None = None
    # Our removal below proves ownership by CONTENT (the marker's first pid is
    # ours), which is unforgeable ONLY given that we took the name — a writer can
    # always forge that proof against itself by overwriting. So the name is CLAIMED
    # (exclusively linked into place), not written: if a live teammate already
    # holds it, we refuse to spawn rather than clobber its marker and then delete
    # it. And we don't even look at the path in the finally unless our claim
    # landed: what sits there otherwise is some earlier episode's leaked marker —
    # routinely a live one, since a SIGKILLed supervisor skips its finally while
    # its child runs on — and its (dead) supervisor's pid can have been recycled
    # to us.
    claimed_marker = False

    def _record_child_pid(child_pid: int) -> None:
        in_place_marker.rewrite_own_in_place_marker(Path(args.smm_dir), name, child_pid)

    try:
        if args.in_place:
            in_place_marker.claim_in_place_marker(Path(args.smm_dir), name)
            claimed_marker = True
        # Commit attribution: the teammate's name-keyed .story-assignment file is
        # the authoritative (Tier 1) signal. A worktree child is keyed via its cwd
        # worktree marker; an in-place child's cwd is the main checkout (no marker),
        # so commit_handling recovers the name from the exported XP_TEAMMATE_NAME
        # instead. Write the assignment in BOTH cases so attribution is explicit and
        # robust even when a second story is concurrently in-progress (rather than
        # relying on the single-in-progress heuristic).
        #
        # AFTER the claim, never before: this file is keyed by NAME, and until the
        # claim lands the name may still belong to a LIVE teammate. Writing it first
        # meant a REFUSED spawn had already overwritten that teammate's assignment —
        # sparing its marker (which then vouches for the name) while redirecting its
        # commits to the story that failed to spawn. Every name-keyed side effect
        # belongs on this side of the claim.
        write_story_assignment(Path(args.smm_dir), name, args.story_id)
        preamble = "" if args.in_place else worktree_preamble(run_cwd)
        combined = preamble + prompt_body
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".prompt.txt", delete=False
        ) as tf:
            tf.write(combined)
            combined_path = tf.name
        log_dir = project_log_dir(args.smm_dir, sprint_id=sprint_id)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Best-effort: run_with_tee already degrades to no-tee when it can't
            # open the log file, so keep the project-scoped (uncreated) dir and
            # let the tee open() fail. Do NOT fall back to a flat /tmp — teammate
            # names repeat across projects, so a shared /tmp/<name>.log
            # reintroduces the cross-project collision project_log_dir prevents.
            sys.stderr.write(
                f"WARN: log dir {log_dir} unavailable ({exc}); "
                f"spawning without forensic tee\n"
            )
        with open(combined_path) as combined_stdin:
            stdout_broken = run_with_tee(
                cmd,
                cwd=run_cwd,
                env=env,
                stdin=combined_stdin,
                name=name,
                log_dir=log_dir,
                on_spawn=_record_child_pid if args.in_place else None,
            )
        # A broken downstream stdout is NOT by itself a failed run: the output
        # filter writes its report BEFORE it exits and closes its read end, so
        # the pipe commonly breaks ~0.1s AFTER a fully successful run. The true
        # "the filter did not finish its job" signal is stdout_broken AND no
        # report on disk — only then did the filter die before recording the
        # report / clearing coordination.
        report_written = worktree.teammate_report_path(
            Path(args.smm_dir), name
        ).exists()
        filter_incomplete = stdout_broken and not report_written
        # Preserve the prompt for re-spawn ONLY when we leave the story
        # in-progress (filter_incomplete). On a promote — or a successful filter
        # that merely closed the pipe late — unlinking is correct.
        if not filter_incomplete:
            Path(prompt_file).unlink(missing_ok=True)
    finally:
        if claimed_marker:
            # Only if the marker is still OURS: a same-name teammate respawned
            # while we were running owns the path now, and deleting ITS marker
            # would demote a live teammate to the lead (see
            # remove_own_in_place_marker). Failing to delete is the safe
            # direction — a leaked marker reads dead and the reap collects it.
            in_place_marker.remove_own_in_place_marker(Path(args.smm_dir), name)
        if combined_path is not None:
            Path(combined_path).unlink(missing_ok=True)

    # rc=0 path: mechanical promote to reviewing under close-then-done.
    # On rc!=0 the run_with_tee call above raised CalledProcessError,
    # this code never runs, the story stays in-progress for debug, and
    # the prompt file is preserved so the orchestrator can re-spawn
    # without reconstructing the prompt.
    # The CAS guard inside update_story_status_if rejects the promote
    # when the story has already been advanced past in-progress (e.g. an
    # orchestrator flipped it to done mid-run) — closing the TOCTOU
    # window the prior get_story → update_story_status pair exposed.
    #
    # In-place (solo delegation) skips the promote: there is no worktree for
    # /xp-accept's reviewing path to detach onto, so the story stays
    # in-progress/solo and /xp-accept's solo (in-progress) path handles it.
    #
    # A filter that died mid-stream WITHOUT writing its report (filter_incomplete)
    # also skips the promote: the teammate finished (rc=0) but the filter never
    # wrote the report / cleared coordination, so promoting to reviewing would
    # hand the lead an unwritten report over stale state. Leaving the story
    # in-progress is the honest signal that the automated completion didn't
    # finish; recover the result from the raw log. A stdout break AFTER the
    # report was written is a benign late pipe-close and promotes normally.
    if filter_incomplete:
        sys.stderr.write(
            f"WARN: output filter closed mid-stream for {name}; teammate "
            f"completed but report/coordination were not recorded. Story left "
            f"in-progress — inspect the log under {log_dir}.\n"
        )
    if args.story_id is not None and not args.in_place and not filter_incomplete:
        sprint_store.update_story_status_if(
            Path(args.smm_dir),
            args.story_id,
            expected="in-progress",
            new="reviewing",
        )


if __name__ == "__main__":
    main()

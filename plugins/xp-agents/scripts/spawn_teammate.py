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

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# `worktree` import is the side-effect bootstrap that adds smm/ to
# sys.path (mirrors scripts/_common.py); pinned first via `isort: split`
# so the `sprint_store` import below resolves.
import worktree  # isort: split

import hook_liveness
import identity
import in_place_marker
import sprint_store

# The CLI surface (every flag this script accepts) lives in a sibling leaf
# module; keep the name importable here so `spawn_teammate.parse_args` IS
# `spawn_args.parse_args`. main() calls it through THIS module's global, so
# every caller and every `spawn_teammate.parse_args` test spelling is unchanged.
from spawn_args import parse_args

# The held-branch recovery lives in a sibling leaf module (split out when the
# teardown wiring pushed this file past 500 lines); keep the name importable
# here, for exactly the seam reason above — `create_worktree` reads THIS
# module's global, so `patch.object(spawn_teammate, "_release_branch_from_main")`
# is the interception point, and patching the leaf is not.
from spawn_branch_release import _release_branch_from_main

# Command-line construction (the claude -p argv shape) lives in a sibling leaf
# module; keep the name importable here so `spawn_teammate.build_command` IS
# `spawn_command.build_command` — every `mock.patch("...spawn_teammate.build_command")`
# site and every direct caller keeps working with zero edits.
from spawn_command import build_command, flag_value

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

# Worktree provisioning lives in a sibling leaf module; keep the name importable
# here, so `spawn_teammate.run_bootstrap` IS `worktree_bootstrap.run_bootstrap`.
#
# That identity holds AT IMPORT and says nothing about patching: these are two
# separate module globals that happen to hold one object, and patching REBINDS a
# global rather than mutating the object both point at. So `create_worktree` below
# reads THIS module's global, and the only name that intercepts it is
# `spawn_teammate.run_bootstrap`. Patch `worktree_bootstrap.run_bootstrap` and the
# stub is never called — the project's own declared bootstrap runs for real, under
# shell=True, which is the exact harm create_worktree's `smm_dir=None` default is
# there to prevent. Pinned by TestTheBootstrapPatchSeam.
from worktree_bootstrap import run_bootstrap


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


def cleanup_existing(
    name: str, cwd: str, *, owns_branch: bool = True, smm_dir: Path | None = None
) -> None:
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

    Sparing the branch was only HALF the story: it spares what the teammate
    COMMITTED, while the worktree DIRECTORY still went away under `--force`,
    so a live teammate re-spawned under the same name lost its whole working
    tree and the spared branch pointed at the last commit before the loss. The
    in-place path took an exclusive claim to stop exactly this
    (`claim_in_place_marker`); the worktree path had none. `force=False` is
    that half — git refuses to remove a tree holding modified or untracked
    files, covering live and crashed-before-commit teammates alike.

    ``smm_dir`` is what makes the declared ``stack.worktree_teardown`` run on
    the FORCED arm; it is opt-in at ``remove_worktree_dir``, so omitting it
    here left a re-spawn clearing a live stack's tree tearing down nothing.
    The force=False arm still gets none by design (see that docstring), and
    the None default is there for the reason ``create_worktree``'s is.
    """
    if owns_branch:
        worktree.remove_worktree(name, cwd, force_branch=True, smm_dir=smm_dir)
    else:
        worktree.remove_worktree_dir(name, cwd, force=False)


def create_worktree(
    name: str, cwd: str, *, branch: str | None = None, smm_dir: Path | None = None
) -> str:
    """Create a git worktree for a teammate. Returns worktree path.

    When branch is provided, checks out that existing branch in the
    worktree instead of creating a new branch. Used by /xp-assign
    to place teammates on story branches — and spawn does not own that
    branch, so a stale worktree is cleared without touching it.

    When smm_dir is provided the project's declared bootstrap runs in the new
    worktree before this returns (see run_bootstrap), and its declared teardown
    runs against the stale tree cleared first. It is an explicit argument and
    must NEVER become an ambient read of the environment or init.sh: ~15 tests
    and fixtures create throwaway worktrees through this function positionally,
    and an ambient read would fire the developer's OWN declared commands in
    every one of them. Default None = neither, which is what those callers want.
    """
    cleanup_existing(name, cwd, owns_branch=branch is None, smm_dir=smm_dir)

    wt = worktree.worktree_path(name, cwd)
    wt.parent.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt)

    if branch is not None:
        _release_branch_from_main(cwd, branch, smm_dir)
        cmd = ["git", "worktree", "add", wt_path, branch]
    else:
        cmd = ["git", "worktree", "add", "-b", name, wt_path]
        current = identity.get_current_branch(cwd)
        if current:
            cmd.append(current)

    try:
        subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        # CalledProcessError's message is the exit code and nothing else, and
        # this runs inside a backgrounded spawn — so the 128 the recovery above
        # does NOT cover (a sibling worktree holds the branch, the path is
        # already registered) reached the lead as a bare number with no reason.
        # Relay git's own words; the exception type is unchanged, so callers and
        # their tests still see CalledProcessError.
        sys.stderr.write(f"git worktree add failed: {(exc.stderr or '').strip()}\n")
        raise
    if smm_dir is not None:
        run_bootstrap(wt_path, smm_dir)
    return wt_path


def write_story_assignment(smm_dir: Path, name: str, story_id: str | None) -> None:
    """Write story assignment file for commit attribution. No-op if story_id is None."""
    if story_id is None:
        return
    worktree.write_story_assignment(smm_dir, name, story_id)


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
    # Worktree (parallel): isolate the teammate in an out-of-repo
    # `{project-id}/worktrees/<name>` tree (sibling of the SMM dir, story-024),
    # and provision it — a fresh worktree has none of the project's gitignored
    # state. The bootstrap hangs off create_worktree rather than sitting here
    # precisely so in-place cannot reach it: there is no worktree to provision,
    # and this expression is what guarantees that, with no guard to forget.
    run_cwd = (
        cwd
        if args.in_place
        else create_worktree(name, cwd, branch=args.branch, smm_dir=Path(args.smm_dir))
    )
    # --plugin-dir is a correctness-critical invariant: without it the headless
    # teammate loads none of the xp-agents skills/agents/hooks (ungated). Self-
    # resolve from CLAUDE_PLUGIN_ROOT when omitted so a caller that forgets the
    # flag can't silently re-spawn the plugin-less teammate this release fixes;
    # an explicit --plugin-dir still wins. Both sides go through flag_value —
    # the same emptiness test build_command applies — because a bare truthiness
    # test calls a whitespace-only flag a value, skips the fallback, and then
    # build_command drops the flag anyway: the plugin-less spawn, from a
    # variable that only looked set.
    plugin_dir = flag_value(args.plugin_dir) or flag_value(
        os.environ.get("CLAUDE_PLUGIN_ROOT")
    )
    cmd = build_command(name, args.model, plugin_dir, args.effort)

    env = os.environ.copy()
    # RESOLVED, for the same reason run_bootstrap resolves it: this child's cwd
    # is run_cwd — the new worktree, not ours — so a relative --smm-dir would
    # resolve against the worktree in every hook the teammate runs, and point at
    # an SMM that isn't there. The bootstrap that just ran saw the absolute path;
    # handing the agent behind it a different one is a split brain.
    env["SMM_DIR"] = str(Path(args.smm_dir).resolve())
    env[identity._XP_TEAMMATE_ENV] = name

    # The child is its own SESSION, so it must not inherit ours. The liveness
    # heartbeat is keyed on the session id: writers key it on the id the harness
    # hands each hook, while the preload check keys it on these variables — so a
    # teammate carrying OUR id reads a marker its own hooks never write. Both
    # outcomes are wrong and neither is visible: it passes the check on the
    # LEAD's heartbeat even when its own hook runtime failed to load (on the tier
    # that runs unsupervised), or, once we have been idle past the threshold,
    # every one of its skill preloads refuses and withholds all context while its
    # hooks are demonstrably running. Dropping them leaves the child's own
    # harness free to export its real id; if it exports none, the documented
    # time-only fallback applies, which is a weaker check rather than a wrong one.
    for session_var in hook_liveness.SESSION_ID_ENV_CANDIDATES:
        env.pop(session_var, None)

    # In-place teammates share the main checkout, so their cwd carries no
    # worktree path marker — commit_handling recovers the name from the leaky
    # XP_TEAMMATE_NAME env instead. Claim a lifetime-scoped marker so attribution
    # only trusts that env WHILE this child runs; a lead that later inherits a
    # leaked var has no live marker and falls through to the heuristics. Released
    # in the finally below.
    #
    # The CLAIM takes a holder lock and keeps it for this whole episode, and that
    # lock — not the marker's content — is what makes the name ours. It is the
    # only proof that cannot be forged: a writer can always overwrite a marker and
    # then read its own pid back as "ownership", which is exactly how a supervisor
    # came to delete a LIVE teammate's marker. And the kernel releases the lock
    # when we die however we die, which no pid can promise (a pid gets recycled,
    # and a recycled pid wedges the name forever).
    #
    # The marker is written TWICE, by us both times. Now, because it must exist
    # before the child's first hook runs or the child loses the identity race —
    # but at this point only our pid exists to record. Then again from on_spawn
    # below, once the child exists: WE are only a tee around it, and a SIGKILL up
    # here does not propagate to it (see run_with_tee), so the child is the one
    # still writing the tree after our lock is gone. Its pid is the OR-leg that
    # keeps the marker alive — recording only ours would let the reap collect a
    # LIVE teammate's marker.
    combined_path: str | None = None

    def _record_child_pid(child_pid: int) -> None:
        in_place_marker.rewrite_own_in_place_marker(Path(args.smm_dir), name, child_pid)

    try:
        if args.in_place:
            in_place_marker.claim_in_place_marker(Path(args.smm_dir), name)
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
        # run_cwd is the worktree; cwd is the orchestrator's main checkout. Pass
        # the main checkout explicitly — the out-of-repo worktree (story-024) is
        # not an ancestor of it, so it can't be derived from run_cwd.
        preamble = "" if args.in_place else worktree_preamble(run_cwd, cwd)
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
        # A no-op unless we HOLD the name — which is the whole ownership test now,
        # so there is no separate "did we claim?" flag to keep in sync with it. A
        # refused or failed claim therefore removes nothing: what sits at that path
        # is someone else's marker, routinely a LIVE one (a SIGKILLed supervisor
        # skips its finally while its `claude` child runs on), and deleting it
        # would demote that teammate to the lead.
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

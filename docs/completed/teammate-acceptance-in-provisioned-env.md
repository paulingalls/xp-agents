# Design: Serial, Main-Repo Acceptance for Teammate Stories

> **SUPERSEDED (2026-07-16) by `docs/spikes/005-worktree-bootstrap-provisioning.md`.**
> This doc's §"Scope decision" claimed "teammates run their own unit tests fine in
> the bare worktree" and rejected per-worktree provisioning on that basis.
> spike-005 measured the opposite on a real bun/Expo monorepo: a bare worktree's
> typecheck and test run both false-RED (TS2882, exit 2; bare `bun test`, exit 1,
> a dozen unresolvable modules) — the "Provisioning the worktree is OUT" rejection
> below no longer holds. The history below is left unedited; only this banner
> reflects the correction.

> **Status: PROPOSED** (idea — not yet planned or built). Scoped to
> **teammate mode only**; solo mode already runs acceptance in the
> provisioned main checkout.
>
> Origin: free session 2026-06-20. User report — accepting each teammate
> story fails its acceptance/e2e harness because the worktree is a bare
> checkout (no installed packages), and because parallel teammates running
> stateful e2e suites collide on shared resources (ports, servers, DBs).

## Problem

Teammate-mode `/xp-accept` runs a story's acceptance command **inside the
teammate's worktree** — `skills/xp-accept/SKILL.md:86-88` subshell-wraps
`(cd <worktree-abs-path> && <command>)` when the story id appears in the
preload's `TEAMMATE_WORKTREES` block. Two independent failures result:

1. **No provisioned environment.** `worktree_create.py` (the `WorktreeCreate`
   hook) does a bare `git worktree add` — it shares `.git` but installs
   nothing. So the worktree has the *code* but no `node_modules` / `.venv` /
   build artifacts. Any harness that needs installed deps fails there.

2. **Concurrent stateful collisions.** Acceptance/e2e suites grab exclusive
   shared resources — a port, a dev server, a test DB, a browser, a
   docker-compose stack. Run several at once across teammates and they stomp
   each other → false failures. **Provisioning does not fix this.** Even
   perfectly-provisioned worktrees can't safely run a stateful e2e suite
   N times in parallel.

These are distinct. Problem 1 is about *where deps live*; problem 2 is about
*acceptance being an exclusive, serializable operation*.

## Scope decision (what's in / out)

- **Unit / TDD tests stay in the worktree, unchanged.** Confirmed with the
  user: teammates run their own unit tests fine in the bare worktree (they're
  in-process and need no shared stack). The commit loop
  (`red → green → /code-review → /xp-quality-review → commit`, see
  `ACCEPTANCE_TESTING_DOCTRINE.md`) does not change.
- **Provisioning the worktree is OUT.** Since the teammate's own loop already
  works, we do not need a per-worktree `setup_command` / `npm ci`. That would
  add per-worktree install cost (× N teammates) *and still not solve the
  collision problem*. Rejected.
- **Only the story loop (acceptance/e2e) for teammate stories moves.** It
  relocates from "parallel, in the bare worktree" to "serial, in the
  provisioned main checkout."

## Why not the PR-first framing

The original instinct was: teammate pushes branch → opens PR → accept reviews
the PR → checks out in main repo → tests → merges. The "test in the main repo"
half is right. The PR/push half should be dropped:

- The plugin treats `gh` and remotes as **optional with graceful
  degradation** — every push/PR call no-ops cleanly with no remote
  (`close_common.py:91-142`: "skipped: gh not on PATH" / "skipped: no remote
  configured"). Gating accept on a PR makes a remote + GitHub a *hard*
  dependency for the core accept loop, breaking fully-local users.
- A PR is unnecessary to reach a provisioned environment: the main checkout
  already shares `.git` with the worktree, so the story commits are reachable
  locally without ever pushing.

"Review surface" (PR) and "where the harness runs" (provisioned env) are
separable. Only the second is the requirement here.

## Key enabling fact

Installed dependencies (`node_modules`, `.venv`, build outputs) are
**gitignored** — present in the working directory but not tracked by git.
So pointing the main checkout's *tracked* files at the story's code (via
checkout or merge) leaves the installed deps in place. The main checkout is
already provisioned (it's where the human works), so acceptance can run
against the story's code there **without reinstalling anything**.

## Proposed design

Teammate-story acceptance runs **serially, in the main checkout**, by
temporarily pointing the main working tree at the story's code, running the
harness, then restoring. `/xp-accept`'s reviewing-story loop is already
serial (one story at a time), so the serialization that fixes problem 2 comes
for free — no new sprint status, no new lock.

Two candidate mechanisms (both preserve installed deps via the gitignore
fact above):

### Mechanism A — detached-HEAD checkout of the story tip (recommended)

```
# in the main checkout (orchestrator sits on the sprint base)
git checkout --detach <story-tip-sha>   # tracked files = story code; deps intact
<run acceptance harness — provisioned, serial>
git checkout <sprint-base>              # restore
```

- Tests the story **in isolation** (its own branch tip).
- Detached HEAD avoids git's "branch already checked out in worktree" refusal
  (the branch is held by the teammate worktree; we check out the *commit*,
  not the branch).
- Restore is a plain `git checkout <sprint-base>` — no merge state to unwind.
- Simplest, lowest-risk. Integration breakage vs the current sprint base is
  still caught later by the real `/xp-story-close` merge and the
  `/xp-sprint-close` cross-cutting review.

### Mechanism B — ephemeral merge-preview (integration variant)

```
git merge --no-commit --no-ff <story-branch>   # integrated tree, deps intact
<run acceptance harness>
git merge --abort                              # ALWAYS, pass or fail
```

- Tests the **integrated** result (story merged onto current sprint base),
  catching conflicts / integration breakage earlier than Mechanism A.
- The preview is **always aborted** — it is a harness, never the real merge.
- Costs: must handle merge conflicts (abort + surface as an acceptance-blocking
  signal, don't run the harness on a conflicted tree), and a crash mid-run
  leaves a merge-in-progress that the next `/xp-accept` must detect and abort.

**Recommendation: start with A.** It solves both reported problems with the
least new machinery and risk. B is a reasonable later upgrade if early
integration signal proves worth the added conflict/recovery handling.

### Reconciliation with accept-before-merge (must-hold invariant)

`TEAMMATE_ACCEPT_BEFORE_MERGE.md` established that the **permanent** merge must
happen *after* accept, so that `/xp-story-close`'s close-reviewer still sees a
live story diff (source ≠ target) and the per-story close pipeline — built for
*unmerged* source branches — works (bugs `9d53a1ca7a9d`, `4860d3666cef`).

This design preserves that fully: the checkout/merge-preview is **ephemeral and
always restored**. The story stays on its own unmerged branch afterward. The
real merge still happens later in `/xp-story-close` Step 7 (always at
orchestrator cwd, `--cwd .`), exactly as today. We are changing *where the
acceptance harness executes*, not the merge timing.

### Preconditions, restore, recovery

- **Clean main working tree required** before the checkout/preview. The
  orchestrator should hold no uncommitted changes at accept time (it does
  not — it's running acceptance, not editing). Guard: refuse and ask if dirty.
- **Restore is mandatory** in a `finally`-equivalent: always return the main
  checkout to the sprint base, even on harness failure or abort.
- **Recovery:** at `/xp-accept` start, detect an interrupted state (detached
  HEAD or in-progress merge in the main checkout from a crashed prior run) and
  restore before proceeding.
- **Setup/teardown cwd consistency:** today `acceptance_execution.setup` runs
  from the main repo while `command` runs from the worktree — different cwds
  (a latent inconsistency). Under this design both run in the main checkout,
  so per-story setup (e.g. start a server) and the command share one cwd, and
  serial execution means no two setups contend for the same port/stack.

## File-by-file sketch (not final)

- `skills/xp-accept/SKILL.md` — Step 1: for a story in `TEAMMATE_WORKTREES`,
  replace the `(cd <worktree> && cmd)` wrap with: checkout story tip (or
  merge-preview) in the main checkout → run setup + command bare → restore.
  Add the clean-tree precondition and the start-of-loop recovery check.
- `skills/xp-accept/scripts/preload.sh` — the `TEAMMATE_WORKTREES` block needs
  the story **tip SHA** (and/or branch) for the checkout, plus the current
  sprint-base ref to restore to. Add a dirty-tree / interrupted-state flag.
- `scripts/branching.py` — a helper to resolve a teammate story's tip SHA +
  restore ref, and (Mechanism A) a guarded `checkout --detach` / restore, or
  (Mechanism B) the merge-preview + abort, with the recovery probe. Keep the
  git mechanics in one tested place, mirroring existing `close_common`/
  `branching` separation.
- No changes to `worktree_create.py`, `system_context` schema, or the gh/PR
  path — provisioning and remotes are untouched.

## Risks / open questions

- **Mutating the human's main checkout transiently.** Mechanism A/B swap the
  main working tree's tracked files for the duration of one acceptance run.
  Bounded and restored, but anything else reading the main tree during that
  window sees story code. Acceptable inside the serial accept loop; flag it.
  (A dedicated preview worktree with **symlinked** installed deps would avoid
  touching the main checkout, but deps are per-directory — clean only for
  global-store ecosystems like `uv`/`pnpm`, not `node_modules`. Possible later
  refinement, not the default — it needs per-project config we're trying to
  avoid.)
- **Long serial e2e suites are slower than parallel.** Accepted: parallel was
  producing *false* failures (problem 2). Correctness > wall-clock here. The
  acceptance window is meant to be short (doctrine); if it drags, the harness
  is the problem.
- **Story dependency / ordering.** Mechanism B previews against the *current*
  sprint base, so a story accepted after another tests on top of the prior
  merge — correct integration order. Mechanism A tests in isolation and defers
  integration signal to close/sprint-close. Decide per the A-vs-B choice.
- **Detached-HEAD vs branch checkout.** Must use `--detach` on the tip SHA;
  a plain `git checkout <story-branch>` fails because the branch is held by the
  teammate worktree.

## Relationship to doctrine

Consistent with `ACCEPTANCE_TESTING_DOCTRINE.md`'s two-loop model: the commit
loop (TDD) stays in the worktree; the story loop (acceptance) is what moves.
This design only specifies *where the story loop's harness executes for
teammate stories* — serial, in the provisioned main checkout — and leaves the
definition of "done" (acceptance criteria verified against the running system)
unchanged.

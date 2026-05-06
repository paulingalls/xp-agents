# Incremental teammate acceptance via `reviewing` self-promotion

**Plugin:** `xp-agents`
**Origin:** Sprint-065 Wave-2 execution (2026-05-06). Four parallel teammates spawned; story-017 finished while 014/018/020 were still running. Wanted to merge 017 immediately but `/xp-accept` is designed to iterate over **all** in-progress stories — running it would either fail on the still-running ones or require manual cherry-picking.
**Status:** Draft — feed into next `/xp-sprint-start` planning.
**Related:** Supersedes the Friction #3 portion of the now-deleted `docs/ideas/3-preload-reviewing-and-accept-marker.md` (which proposed the same plumbing change but framed it as a defensive fix). Friction #4 from doc 3 split out into doc 9.

## Why

Today's teammate flow:

1. `/xp-assign` (teammate mode) eager-promotes all scheduled stories to `in-progress` and creates branches.
2. Teammates work in parallel, commit, exit. Story stays `in-progress` until the orchestrator processes it.
3. Orchestrator waits for **all** teammates to finish, then runs `/xp-accept`. Step 1.0 promotes `in-progress → reviewing` per story before running its acceptance command.

The wait-for-slowest pattern is structural, not necessary. When teammate A finishes 5 minutes in and teammate B takes 30, A's merge is artificially delayed by 25 minutes for no XP reason — A's branch is independent, its file_domain is disjoint, its acceptance command can run the moment A's last commit lands.

Sprint-065 reproduction: 017 (prompt-side text edit) finished in ~3 min while 020 (3-phase bundled chain) was still on phase 1. With incremental acceptance, 017 could have been merged + the sprint base advanced ~25 min sooner. Wave 3 stories rebasing on a fresher base would have less drift to absorb.

## The shape

Two coordinated changes:

### Change 1 — Teammates self-promote `in-progress → reviewing` on successful completion

The teammate process knows when it has finished its TDD + simplify + quality-review + commit cycle cleanly (it exits 0). Add a final step to the teammate prompt template (or a teammate-side hook):

```bash
python3 ${PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} \
  update-story ${STORY_ID} reviewing
```

This signal — "story is ready for acceptance" — must be distinguishable from "still working" so the orchestrator can scan for it.

**Failure semantics:** if the teammate exits non-zero (acceptance failed mid-cycle, simplify uncovered blocking issue), it leaves the story in `in-progress`. Reviewing-state means "I, the teammate, attest my AC command exited 0; orchestrator may run it again".

### Change 2 — `/xp-accept` preload + skill processes `reviewing` stories independently

Three cooperating shifts:

- Preload widens its filter from `in-progress` to `reviewing` only (or "in-progress that the orchestrator will promote, plus reviewing that's already there"). The semantics question: does the orchestrator still process in-progress that are stale (a teammate started but never finished)? Probably yes for solo-mode handoff; teammate-mode treats `in-progress` as "still running, leave alone" and `reviewing` as "ready to verify".
- Skill iterates over `reviewing` stories, runs each AC, marks done/deferred. Orchestrator can re-invoke `/xp-accept` repeatedly as more teammates finish.
- The 5-state lifecycle docs in `/xp-accept` SKILL.md update to reflect: `reviewing` is set by **teammate** (or orchestrator in solo mode) at "AC was just run by the producer, ready for second-pass verification".

### Change 3 — orchestrator re-invokes `/xp-accept` on teammate completion notifications

Today the orchestrator has the task-notification signal when a teammate exits. With Changes 1+2 in place, the orchestrator's natural cadence becomes:

```
spawn 4 teammates
loop:
  wait for next task-notification
  if any reviewing-state stories exist:
    /xp-accept (processes them; dispatches /xp-story-close per accepted)
  if no in-progress AND no reviewing remain:
    break
/xp-sprint-review
```

This is a polling loop on `reviewing`-state count, driven by the existing notification mechanism. No new infra.

## Solo mode applicability

In solo mode, the main agent is BOTH the producer AND the orchestrator. There's no parallelism to harvest in a single-story session — but carry-over sessions routinely have multiple `in-progress` stories from prior solo work, and today's `/xp-accept` iterates over **all** of them in one invocation. That's the same wait-for-slowest problem teammate mode has.

The unified protocol from Changes 1–2 generalizes cleanly:

- **Solo agent self-promotes too.** After committing a story's last needed commit cleanly + AC green, the main agent runs `sprint_cli.py update-story <id> reviewing` BEFORE invoking `/xp-accept`. Same one-line bash step teammates use.
- **`/xp-accept` becomes producer-agnostic.** Both teammate and solo arrive at the same "story is in `reviewing` state, verify it" entrypoint. Today's Step 1.0 (`in-progress → reviewing` promotion) becomes idempotent — skips if already `reviewing`, runs otherwise — so legacy callers (a session that forgot to self-promote) still work.
- **Per-story `/xp-accept` invocation.** With the producer's attestation explicit, the main agent can `/xp-accept story-A` immediately after committing A, without waiting for B/C/D to be ready. (If `/xp-accept` doesn't take a `--story-id` flag today, add one — but the simpler alternative is "scan for any `reviewing` stories and process them," which gives the same incremental behavior without an arg.)

### Why not a commit-hook-driven auto-promote?

Tempting (zero-touch from the user's POV), but messy:

- A story can have multiple intermediate green commits before the last one. The hook can't tell "this is the LAST commit" without an out-of-band signal.
- AC commands can be slow (full test suite). Running them synchronously in `PostToolUse:Bash` blocks the agent for tens of seconds per commit.
- Async background AC runs add machinery (track in-flight runs, route results back) that producer-side `update-story reviewing` sidesteps for a one-line CLI call.

Self-promote-via-explicit-CLI is the honest place to put the producer's attestation. The producer (teammate process or main agent) knows when it's done; the orchestrator (also the main agent in solo mode) reads that attestation from sprint state. Clean separation, no marker hacks.

### Solo mode — additional file domain

- `plugins/xp-agents/skills/xp-accept/SKILL.md` — call out: "in solo mode, the main agent self-promotes via `sprint_cli.py update-story <id> reviewing` after a clean commit + green AC, then invokes `/xp-accept`. This mirrors teammate-mode handoff."
- `plugins/xp-agents/PROCESS_GUIDE.md` — update the per-commit review-cycle prose to include the self-promote step
- `plugins/xp-agents/tests/integration/test_accept_lifecycle.py` — pin solo self-promote → `/xp-accept` → `/xp-story-close` happy path

## Open questions

1. **Does teammate self-promote belong in the prompt template or a hook?** Prompt template is simpler (one bash step at the end); hook is more robust (fires regardless of prompt drift). Sprint-062 tried prompt-driven self-promote and Friction #3 was the result — the orchestrator's `/xp-accept` preload wasn't ready. With Change 2 in place, prompt-driven works; with Change 2 deferred, neither works.
2. **What if the teammate's AC command flakes?** Reviewing-state means "teammate ran it green at exit". Orchestrator re-runs it for verification (existing behavior). If orchestrator's re-run fails, it offers debug/override/defer per Step 1's automated-fail branch. No change to that contract.
3. **How does the orchestrator avoid spurious `/xp-accept` invocations?** Cheap check before invoking: `count-status reviewing > 0`. If zero, skip. The notification + cheap-check loop is robust.
4. **Solo mode — does anything change?** Solo mode's flow is `/xp-assign` → solo work → `/xp-accept`. Solo orchestrator naturally promotes `in-progress → reviewing` in Step 1.0. The SKILL.md's promote step still applies; the preload widening is purely additive.

## File domain (sketch)

- `plugins/xp-agents/skills/xp-accept/SKILL.md` — Step 1.0 becomes idempotent (skip if already `reviewing`); preload section documents widened filter
- `plugins/xp-agents/skills/xp-accept/scripts/preload.sh` — read both `in-progress` AND `reviewing` (with status carried in output so the skill can route)
- `plugins/xp-agents/scripts/spawn_teammate.py` OR teammate prompt template — append the self-promote bash step on success
- `plugins/xp-agents/TEAMMATE_GUIDE.md` — document the new contract (teammates exit at `reviewing` when AC is green)
- `plugins/xp-agents/tests/integration/test_accept_lifecycle.py` — extend: reviewing-only preload, mixed reviewing+in-progress preload, teammate-self-promote pin
- `plugins/xp-agents/skills/xp-assign/SKILL.md` — Post-Spawn section updates to "loop on task-notifications, run /xp-accept when reviewing > 0"

## Sequencing

Two stories, ordered:

1. **Story A — preload widening + skill rework.** `/xp-accept` reads both states; SKILL.md updates the lifecycle prose. Behavior-preserving for today's flow (teammates still leave at `in-progress`; orchestrator still promotes via Step 1.0). Ships independently of Change 1.
2. **Story B — teammate self-promote + xp-assign loop.** Adds the teammate's final `update-story reviewing` step and reworks the orchestrator post-spawn loop. Depends on Story A being shipped (otherwise teammates self-promote and orchestrator misses them per sprint-062 Friction #3).

Could be one M-large story if the test surface is well-bounded; two S-medium stories if we want intermediate green commits between them.

## Provenance

- Sprint-065 Wave-2 execution: 017 finished while 014/018/020 still running; `/xp-accept` couldn't process 017 alone without manual orchestration.
- Doc 3 already proposed the preload-widening fix (Friction #3 direction 2) but framed it as defensive against teammate-prompt drift. This doc reframes the same plumbing as the substrate for an incremental-acceptance pipeline.

# Story Branch Lifecycle Doctrine

## Purpose

Define **when** story branches come into existence, **where** they
fork from, **who** lives on them, and **how** they get cleaned up.
Replaces today's mix of sprint-start eager branch creation,
teammate-* branch namespace, and ad-hoc branch creation paths
scattered across `/xp-work-selection` and `/xp-assign`.

This doctrine is plugin-internal: it governs the interaction between
`/xp-sprint-start`, `/xp-assign`, `/xp-accept`, `spawn_teammate.py`,
and the `PreToolUse:Bash` / `PostToolUse:Bash` hooks. It does not
change what stories are or how they're decomposed — it only changes
the branch artifacts that represent them.

---

## The Problem

Today's story branch lifecycle has three overlapping symptoms:

1. **Eager creation at the wrong time.** `/xp-sprint-start`'s Step 9
   creates `<user>/story-NNN-<slug>` branches for every story in the
   sprint, before `/xp-review-plan` runs and before `/xp-assign`
   decides execution mode. Many of these branches end up unused.
   Sprint-036 created six story branches; five stayed at fork-point
   and one was advanced (story-002, only because that teammate
   manually rebased onto it).

2. **Two parallel branch namespaces.** `spawn_teammate.py` creates a
   *separate* branch named `teammate-step-N` inside each worktree,
   ignoring the story branch the sprint-start skill produced. Commits
   land on `teammate-step-N`; sprint-close merges from
   `teammate-step-N`; the named story branches go nowhere. Two
   parallel systems, neither talking to the other.

3. **Ad-hoc creation duct-tape.** When `/xp-work-selection` adds
   stories to a sprint after sprint-start has already run (sprint-036
   added stories 003-006 this way), sprint-start's Step 9 has
   already passed. Branch creation for the new stories happens via a
   separate `branching.py create` loop bolted into the kickoff/
   work-selection flow. Three different skills now have branch-
   creation responsibilities that don't compose.

The root cause is timing: branches are execution artifacts but
they're being created at decomposition time. The decision "this
story will exist" and the decision "this story will be worked on
this iteration" are different decisions. Conflating them produces
the symptoms above.

---

## Principle

**A story branch represents a commitment to executing a story this
iteration.** It exists from the moment that commitment is made
(`/xp-assign` time) until the work it carries has either merged into
sprint or been deferred. No earlier, no separate-namespace clones,
no orphaned siblings.

The corollary: stories that exist in `sprint.json` but aren't being
worked on right now don't get branches. They live as manifest
entries until somebody (the main agent, a teammate, a future
`/xp-assign` call after `/xp-work-selection` adds them in-progress)
actually picks them up.

---

## Execution Units and Branching Shapes

The branching shape isn't determined by execution *mode* (solo vs.
teammate) — it's determined by how the work is *grouped*. The unit
that matters is the **execution unit**: a single agent (main, or
spawned teammate) working on one or more stories in sequence.

| Execution unit | Branching shape | Used for |
|---|---|---|
| One agent, one story | One branch off sprint | Single solo story; one teammate, one independent story |
| One agent, N dependent stories | Chain — each branch off the previous tip | Solo plow-through; sequential teammate bundling stories with hard deps |
| N agents, N independent stories | N siblings off sprint | Parallel teammates working on stories with disjoint file_domains and no hard runtime deps |

**Hard runtime dependency** = a story's diff includes an import
statement, function call, or other reference that resolves only
against another story's not-yet-merged code. Detected from plan +
sprint context (typically by reading file_domain + interface_contracts
+ design_sources). The current `/xp-assign` already does this
informally; this doctrine codifies the existing pattern, it doesn't
introduce new logic.

**Soft dependency** (story-B describes story-A's work in prose, but
doesn't import it) does not require chaining — soft-dependent
stories run in parallel safely.

Sprint-036 example, retroactively:

- story-001 (`scaffold_detect.py`) and story-002 (SKILL.md +
  test_scaffold_skill imports scaffold_detect) had a hard runtime
  dep. **Chained inside one sequential teammate.**
- stories 004, 005, 006 had disjoint file_domains and no cross-story
  imports. **Parallel siblings off sprint, three teammates.**
- story-003 (research, file_domain=[]) had no code work. **Main
  agent did this directly without a teammate.**

That mapping is what `/xp-assign` produced for this sprint. The
doctrine just makes the rule explicit.

---

## Lifecycle By Phase

### `/xp-sprint-start`

- Decomposes the milestone into stories. Writes sprint.json.
- Creates the **sprint branch** only (the integration target).
- **Does not create story branches.**
- Step 9's "create story branches" loop is removed.

### `/xp-review-plan`

- No branch work, today or tomorrow. Unchanged.

### `/xp-assign`

- Decides execution units (which stories ship, in what unit
  groupings, which run in parallel teammates vs. solo).
- For each in-progress story that this iteration will work on:
  - Computes the branch's parent (sprint tip for first story in a
    unit; previous story's tip for subsequent stories in a chain).
  - Creates the story branch via `branching.py create --story
    story-NNN --slug <slug> --base <parent-ref>`.
  - Records the branch name on the story in sprint.json (`branch_name`
    field — new optional field, additive change).
- For parallel teammate units: spawns each teammate's worktree on
  its assigned story branch (Option A from prior conversation —
  worktree checks out the story branch, no `teammate-*` branch
  layer).

The `branching.py create --story` command gains a `--base` flag.
Today it forks off sprint by default; with the flag, callers can
specify a different parent (the previous story's tip in a chain).
Default behavior preserved when `--base` is omitted.

### Solo plow-through (during the work)

- Main agent commits on the current story branch.
- After each commit, `PostToolUse:Bash` emits a one-line nudge:
  > *If this commit completed story-NNN's acceptance criteria, branch
  > off this commit for the next story before continuing:*
  > `branching.py create --story story-NNN+1 --slug <slug> --base HEAD`*.
  > *Otherwise keep working on this branch.*
- Agent self-assesses, switches if done, ignores if not.

The nudge fires every commit during solo with multiple in-progress
stories. Cost is one line of `additionalContext`. Encouragement-not-
punishment matches the codebase's empirical-driver pattern: ship the
gentler mechanism first, promote to a hard gate only if retros show
drift.

### `/xp-accept` — happy path (auto-switch)

When `/xp-accept` marks a story done:

1. Read sprint.json. Find the next in-progress (or ready) story by
   declaration order.
2. If a next story exists with no chain dependency on the just-
   accepted one: create-or-checkout its branch off sprint.
3. If a next story exists with a chain dependency: create-or-
   checkout its branch off the just-accepted story's tip.
4. If no next story exists: stay on the sprint branch and report
   sprint-complete.
5. Tell the main agent: *"story-NNN marked done; checked out
   `<expected-branch>` for the next story."*

This handles the happy path without a question per story. The agent
keeps working.

### `/xp-accept` — session-end (walk the chain)

If the user runs `/xp-accept` against multiple in-progress stories
at session-end (the plow-through-then-accept-all flow):

1. Walk in-progress stories in declaration order.
2. For each: verify AC against the story's branch (using the
   acceptance_execution.command if present, or guided manual check
   otherwise).
3. For each that **passes**: merge to sprint with `--no-ff` so
   each story is a grep-able boundary. Delete the branch.
4. For each that **fails**: see the next section.

Sprint-close (auto-chained from `/xp-sprint-review`) sees a sprint
branch with all merged stories already integrated. Existing
sprint-close behavior unchanged.

### AC Fail Mid-Chain — Cascade as Default

If `/xp-accept` finds story-N's AC failing while story-N-1 passed
and story-N+1 also passed:

- **Cascade**: story-N is deferred → story-N+1 was built on top of
  story-N's suspect work → story-N+1 also defers.
- The user fixes story-N (now or in a future iteration), or accepts
  the cascade and the deferred chain carries forward to next sprint.
- Sprint absorbs only the prefix of the chain that passed (story-N-1
  and earlier).
- All deferred branches stay alive for the next iteration; their
  `branch_name` records on sprint.json carry over.

The alternative — surgical extraction (cherry-pick story-N+1 onto
sprint without story-N) — is technically possible via cherry-pick or
interactive rebase, but introduces conflict-resolution complexity and
breaks story-N+1's diff attribution. **Cascade is the default;
surgical is out of scope for v1 of this doctrine.** If cascading
deferrals become a recurring retro Fix, revisit.

### Sprint close

Story branches that merged are already deleted by `/xp-accept`.
Story branches that deferred stay alive for the next iteration.
Sprint-close (or `/xp-sprint-close`) merges sprint to its target as
today; nothing in this layer changes.

---

## Reliability Mechanism

### What happens when

| Phase | Mechanism | Layer |
|---|---|---|
| First story branch creation | `/xp-assign` creates explicitly | Skill (deterministic) |
| Mid-chain transition (happy path) | `/xp-accept` auto-switches | Skill (deterministic) |
| Mid-commit drift detection | `PostToolUse:Bash` nudge | Hook (advisory) |
| Wrong-branch commit | (No mechanism — accepted) | — |

### What's explicitly not built

- **No `PreToolUse:Bash` block** on commit-time branch/story
  mismatch. Earlier draft proposed this; rejected on the grounds
  that wrong-branch commits are rare in practice and recovery is
  cheap (`git reset --hard HEAD~1; git checkout <branch>; recommit`,
  ~30 seconds). The friction of a per-commit gate isn't worth the
  prevention of a rare mistake.
- **No commit-message-parsing logic in hooks.** The nudge doesn't
  parse `[story-NNN]` prefixes; it fires unconditionally during
  solo with multiple in-progress stories and lets the agent
  self-assess. Less hook code, fewer false positives.

If retro evidence later shows wrong-branch commits are common
enough to be a problem, the doctrine can be amended to add a
PreToolUse block following the empirical-driver pattern (same
trajectory the Resolves-Event gate followed: advisory → hard gate
based on observed skips).

---

## Migration: Hard Cutover

This doctrine reshapes branch lifecycle across multiple skills
simultaneously. A soft migration would leave the codebase with two
disagreeing branch creation paths (sprint-start eager + assign
lazy), worse than either alone. **Hard cutover** in a single
release.

### Removed

- `/xp-sprint-start` Step 9 ("Create Story Branches"). Sprint-start
  no longer touches story branches.
- `teammate-*` branch namespace. `spawn_teammate.py` creates the
  worktree on the assigned story branch directly. No second branch
  layer.
- `_close_fixtures.py` and integration tests asserting `teammate-step-N`
  branch existence.
- `xp-accept` skill's "TEAMMATE_WORKTREES" preload section (lists
  `teammate-step-NNN` names) — replaced by listing story branches.
- Ad-hoc branch creation in `/xp-work-selection` for stories added
  after sprint-start. Stories added there go straight to ready;
  branches happen at the next `/xp-assign` call.

### Added

- `/xp-assign` story-branch creation logic (the lifecycle phase
  table above).
- `branching.py create --story` `--base <ref>` flag.
- `branch_name` optional field on each story in sprint.json
  (additive, backward-compatible — when absent, falls back to
  `<user>/story-NNN-<slug>` slug heuristic).
- `/xp-accept` happy-path auto-switch (skill prose addition).
- `/xp-accept` session-end walk-the-chain logic (skill prose
  addition + AC-fail cascade behavior).
- `PostToolUse:Bash` nudge for solo-mode mid-chain transition.
- New tests asserting the new flow: assign creates branches,
  accept switches, nudge fires under the right conditions.

### Not changed

- Sprint branch creation (`/xp-sprint-start` Step 8). Still
  sprint-start's job.
- Plan branch creation. Still `/xp-plan` Step 5b's job.
- Free branch creation. Still `/xp-kickoff` Step 2.5's job.
- `branching.py create-sprint`, `create-plan`, `create-free`. All
  unchanged.
- Sprint-close, plan-close, free-close. All unchanged at the
  branch-merge level — their inputs (story branches feeding into
  sprint) are produced earlier in the lifecycle now, but the close
  flow itself is unchanged.

---

## Resolved Design Calls

1. **Branch creation timing:** `/xp-assign`, lazy. Sprint-start
   only creates sprint branch.

2. **Branching shape, by execution unit (not by mode):**
   - Single story per agent → single branch off sprint.
   - N dependent stories per agent → chain off previous tip.
   - N independent stories across N agents → siblings off sprint.

3. **Teammate worktree branches:** None separate. Each teammate's
   worktree checks out its assigned story branch directly.

4. **Hard vs. soft dependency:** Hard = import-level diff
   reference; soft = descriptive prose only. Hard deps require
   bundling into one execution unit (chain). Soft deps run in
   parallel.

5. **Mid-chain reliability:** PostToolUse nudge, no PreToolUse
   block. /xp-accept auto-switches on the happy path. Wrong-branch
   commits are accepted as a rare-and-cheap-to-recover failure
   mode; promote to hard gate only via empirical driver.

6. **AC-fail mid-chain:** Cascade as default. Surgical extraction
   deferred to v2 of this doctrine if retros show cascade is
   regularly the wrong call.

7. **Schema:** `branch_name` optional field on sprint.json stories.
   Additive, backward-compatible.

8. **Migration:** Hard cutover. No deprecation cycle.

9. **Hard-dependency detection in `/xp-assign`:** stay LLM-driven.
   `/xp-assign` reads plan + sprint context + file_domain +
   interface_contracts and uses LLM judgment to decide which
   stories chain. The sprint.json `dependencies` field stays
   informational, not load-bearing. Trade-off accepted: keeps
   one LLM-compliance failure mode in exchange for catching deps
   the field doesn't yet encode (cross-reference in prose,
   semantic dep that isn't import-shaped, etc.). If the LLM
   regularly misses obvious chain decisions, revisit and promote
   `dependencies` to load-bearing.

10. **Worktree directory naming:** `worktree-story-NNN/`. The
    directory mirrors the branch it carries
    (`<user>/story-NNN-<slug>`). Cleanup tooling keys off
    story-id, not teammate-id. The "teammate" framing in directory
    paths goes away with the namespace.

11. **Orphan story-branch triage at kickoff:** extend the existing
    orphan triage. Kickoff's preload computes
    `ORPHAN_STORY_BRANCHES` alongside `ORPHAN_FREE_BRANCHES`,
    listing story branches whose sprint has been closed, deferred,
    or whose `branch_name` no longer matches an in-progress story.
    User picks merge / keep / delete per branch via
    AskUserQuestion, same flow free-branch orphans use today.

12. **Nudge wording versioning:** add a test pinning the canonical
    phrasing. Mirrors v2.30.6's pattern (the
    `test_close_reviewer_records_concerns_as_smm_events` test
    pinned agent prompt content). One assertion in the hooks test
    suite catches accidental rewording. The canonical text is
    treated as a versioned interface — changes go through
    deliberate test updates, not silent edits.

---

## Remaining Open Questions

None at the doctrine level. Implementation-time questions (exact
nudge wording, the interface_contracts heuristics LLM uses to
detect hard deps, the test fixture shapes for orphan-story-branch
triage) get answered when the corresponding milestone's stories
are decomposed.

---

## Phasing

This doctrine becomes its own execution plan after the
scaffolding-doctrine plan
(`paulingalls/plan-scaffold-acceptance-v1`) ships. Five
milestones:

- **M-1: Schema + CLI.** Add `branch_name` field to sprint.json
  story schema (with backward-compat fallback). Add `--base` flag
  to `branching.py create --story`. Pure additive, no behavior
  change. Lays the foundation.
- **M-2: `/xp-assign` lazy creation.** Move story branch creation
  from sprint-start Step 9 to assign. Remove sprint-start Step 9.
  Update `dependencies` field to be load-bearing for execution-
  unit decisions. Update tests.
- **M-3: Worktree on story branch.** `spawn_teammate.py` creates
  worktree on the assigned story branch. Remove `teammate-*`
  branch namespace. Update `_close_fixtures.py`, integration
  tests, `xp-accept` preload.
- **M-4: Reliability layer.** `/xp-accept` happy-path auto-switch.
  `/xp-accept` session-end walk-the-chain with cascade. PostToolUse
  nudge for solo-mode mid-chain transition. Tests for each.
- **M-5: v3.0 release** (paired with the security-tier doctrine,
  if both ship together — they're independent at the code layer
  but both are breaking changes worth bundling into one major
  release).

---

## Status

**Draft.** Not yet in any execution plan. Forthcoming as a peer of
the security-tier doctrine; both target v3.0.

**Sources / context:**

- This-session conversation: user asked "since teammates run on
  worktrees, do we need branches for them?" → analysis showed
  double-naming problem → "should story branch creation happen in
  /xp-assign?" → analysis showed sprint-start was wrong place →
  reliability discussion (PreToolUse block vs. PostToolUse nudge)
  → user's "encourage right behavior, not punish wrong" reframing
  → "create new branch" vs "run /xp-accept" nudge variants → user
  noted file_domain rule mostly closes the parallel-teammate
  dependency question → execution-unit framing.
- Sprint-036 retrospective evidence: story-002's teammate manually
  rebased onto story-001's branch (because the contract was
  unclear); other teammates committed to `teammate-step-N` and
  story branches stayed at fork-point.
- Existing infrastructure: `branching.py create --story`,
  `branching.py create-sprint`, `spawn_teammate.py`,
  `_close_fixtures.py`, `xp-accept/SKILL.md`, kickoff orphan
  triage.

**Concerns this doctrine answers (would resolve at v3.0):**

- Implicit: today's wasted story-branch artifacts at fork-point
  generate retro noise. No specific concern event filed yet, but
  the pattern is visible in sprint-036's git log.
- Open question carried by the security-doctrine plan
  (paragraph: "Worktree-directory-vs-branch-naming worth being
  explicit about") — addressed here.

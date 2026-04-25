# Branch Lifecycle: Sprint Close, Plan Close, and Free Sessions

## Purpose

Define the post-sprint and post-plan branch lifecycle — how work
flows from sprint branches to plan branches to the primary branch,
with holistic reviews at each integration point. Also defines branch
management for free sessions. Extends the Branching Doctrine with
the missing "what happens after sprint-review" lifecycle.

**Primary branch** means `main` at Stages 1-2, and the integration
branch (`develop`, `staging`, etc.) at Stage 3. Main is
releases-only at Stage 3 — the plugin never merges directly to main
at Stage 3.

---

## Problem

Sprint-030 completed (5/5 stories delivered) but the sprint branch
was never merged to main. No PR was created, no review ran, and the
session continued on a stale sprint branch. Root causes:

1. **No merge function.** `branching.py` has `merge_story_branch()`
   but no sprint-branch merge equivalent.
2. **PR creation is prompt-only.** The sprint-reviewer agent prompt
   includes `gh pr create` instructions, but the agent's
   `allowed-tools` don't include `gh` or `branching.py` — the
   commands silently can't execute.
3. **No post-sprint checkout.** Nothing returns the session to main
   (or the plan branch) after a sprint completes.
4. **No plan-level branch.** Multi-sprint execution plans have no
   integration branch — sprints merge directly to main even when the
   plan isn't complete.

---

## Design

### Execution Plan Branches

Each execution plan optionally declares a **plan branch** — a
long-lived feature branch that accumulates milestones until the plan
is complete.

```json
{
  "title": "Acceptance Testing Infrastructure",
  "branch": "paulingalls/plan-acceptance-testing",
  "sources": [...],
  "milestones": [...]
}
```

- **`branch` field** (optional, nullable). When set, sprint branches
  merge into the plan branch instead of the primary branch. When
  null or absent, sprint branches merge directly to the primary
  branch.
- **Created after plan confirmation.** After `/xp-plan` presents the
  milestones and the user confirms, the agent recommends whether a
  plan branch makes sense (multi-milestone, not independently
  shippable). The user decides yes/no. If yes, the branch is created
  and recorded in the plan. If no, `branch` stays null.
- **Plan branch base** is always the primary branch at creation time
  (main at Stages 1-2, integration branch at Stage 3).

#### When to Use a Plan Branch

- Multi-milestone plans where intermediate milestones aren't
  independently shippable.
- Work that needs to accumulate before it's ready for main (the v2
  pattern — long-lived feature branch).
- Parallel execution plans that need isolation from each other.

#### When NOT to Use a Plan Branch

- Single-milestone plans.
- Plans where each milestone is independently valuable on main.
- Quick changes where the sprint branch → main flow suffices.

### Branch Hierarchy

```
primary branch (main at Stage 1-2, integration branch at Stage 3)
  └── plan branch (optional, per execution plan)
       └── sprint branch (per sprint, Stage 2+)
            └── story branch (per story, Stage 1+)
```

At each level, the child merges into its parent when done. Reviews
happen at every merge point — XP says turn good practices up to 11.

### Merge Targets by Configuration

| Plan branch? | Stage | Story merges to | Sprint merges to | Plan merges to |
|--------------|-------|-----------------|------------------|----------------|
| No | 1 | main | (no sprint branch) | — |
| No | 2 | sprint branch | main | — |
| No | 3 | sprint branch | integration branch | — |
| Yes | 1 | main | (no sprint branch) | main |
| Yes | 2 | sprint branch | plan branch | main |
| Yes | 3 | sprint branch | plan branch | integration branch |

Stage 3 with a plan branch: sprint merges to plan branch (not the
integration branch directly). The plan branch itself merges to the
**integration branch** when the plan completes — not main. At
Stage 3, main is releases-only; the release process is outside the
plugin's scope.

---

## `/xp-sprint-close` Skill

A new inline skill that runs after `/xp-sprint-review` completes.
Handles the branch lifecycle for the sprint that just ended.

### Trigger

- Automatically suggested at the end of `/xp-sprint-review`.
- Can be run standalone to clean up a forgotten sprint branch.

### Prerequisites

- Sprint review must have completed (sprint.json shows all stories
  done or deferred).
- Must be on the sprint branch (or able to identify it).

### Flow

```
Step 1: Detect merge target
  ├── Read execution_plan.json → check for plan branch
  ├── Read system_context.json → get branching stage
  └── Determine target: plan branch > integration branch > main

Step 2: Create PR (if gh available)
  ├── Push sprint branch to remote (if not already pushed)
  ├── gh pr create --base <target> --head <sprint-branch>
  │     Title: "Sprint <id>: <goal>"
  │     Body: stories delivered, velocity, milestone status
  └── If gh unavailable: note for user, continue with local merge

Step 3: Fork sprint review agent
  ├── If PR exists: pass PR number to agent
  ├── If no PR: pass git diff <target>...HEAD to agent
  ├── Agent performs standard + sprint-level review
  │   (see "Sprint/Plan Review Agent" section below)
  └── Agent returns structured findings

Step 4: Present findings and address feedback
  ├── Main agent presents review findings to user
  ├── User reviews findings
  ├── Fix any issues (new commits on sprint branch)
  └── Re-review if significant changes (re-fork agent)

Step 5: Merge
  ├── Ask user: "Ready to merge?"
  ├── If PR exists: gh pr merge (or user merges manually)
  ├── If no PR: git merge --no-ff <sprint-branch> into <target>
  └── Merge style: --no-ff (preserves sprint history as merge commit)

Step 6: Cleanup
  ├── Delete sprint branch (local)
  ├── Delete remote sprint branch (if pushed): git push origin --delete
  ├── Checkout target branch
  └── Record status event: "Sprint branch merged and cleaned up"
```

### Error Handling

- **Merge conflicts:** Present to user, do not auto-resolve. Sprint
  branch should be rebased onto target before merging if conflicts
  exist.
- **gh unavailable:** Fall back to local merge. Note in summary that
  no PR was created.
- **gh not authenticated:** Same as unavailable — fall back gracefully.
- **Dirty working tree:** Refuse to start. Ask user to commit or
  stash.

### Implementation Notes

- This is an **inline skill** (not forked) — it runs in the main
  agent's context because it needs interactive user feedback and
  branch switching.
- The **review step** is forked to a review agent (see below) to
  protect the main agent's context from large diffs.
- Sprint-close records its own events (status, decision) to the SMM.

---

## `/xp-plan-close` Skill

A new inline skill that runs when the last milestone of an execution
plan is delivered and the plan has a plan branch.

### Trigger

- `/xp-sprint-review` marks the last milestone as `delivered` →
  suggests running `/xp-plan-close`.
- Can be run standalone to close out a completed plan.

### Prerequisites

- All milestones must be `delivered` (or explicitly deferred).
- A plan branch must exist in `execution_plan.json`.

### Flow

```
Step 1: Verify plan completion
  ├── Read execution_plan.json
  ├── Check all milestones are delivered or deferred
  └── If not complete: report status and exit

Step 2: Detect merge target
  ├── Stage 1-2: target = main
  ├── Stage 3: target = integration branch
  └── Read from system_context.json branching_strategy

Step 3: Create PR (if gh available)
  ├── Push plan branch to remote
  ├── gh pr create --base <target> --head <plan-branch>
  │     Title: "<plan title>"
  │     Body: milestones delivered, overall scope, duration
  └── If gh unavailable: continue with local merge

Step 4: Fork plan review agent
  ├── If PR exists: pass PR number to agent
  ├── If no PR: pass git diff <target>...<plan-branch> to agent
  ├── Agent performs standard + plan-level review
  │   (see "Sprint/Plan Review Agent" section below)
  └── Agent returns structured findings

Step 5: Present findings and address feedback
  ├── Main agent presents review findings to user
  ├── User reviews findings
  ├── Fix any issues
  └── Re-review if significant changes (re-fork agent)

Step 6: Merge
  ├── Ask user: "Ready to merge?"
  ├── Merge plan branch → <target> (--no-ff)
  └── Tag if appropriate (user decides)

Step 7: Cleanup
  ├── Delete plan branch (local + remote)
  ├── Checkout target branch
  ├── Archive execution plan (plan_cli.py archive)
  └── Record status event: "Plan completed and merged to <target>"
```

---

## Free Session Branch Management

Free sessions (no sprint, no plan) still need branch discipline at
Stage 1+. The user shouldn't commit directly to a protected branch
during exploratory work.

### Auto-Create on Kickoff

When `/xp-kickoff` detects a **free session** at Stage 1+ and the
current branch is protected (main, or integration branch at
Stage 3):

1. Auto-create a feature branch: `<user>/free-<YYYY-MM-DD>-<slug>`
   where slug is derived from the user's session goal (first 3-4
   words, slugified).
2. Checkout the feature branch.
3. Record a status event noting the branch creation.

If the user is already on a non-protected branch, skip — they've
already set up their own branching.

### Branch Naming

- Pattern: `<user>/free-<date>-<goal-slug>`
- Example: `paulingalls/free-2026-04-24-fix-branch-lifecycle`
- The date prefix makes orphan detection trivial — any free branch
  older than the current session is a candidate for cleanup.

### Cleanup: The Orphan Problem

Sessions can end abruptly (terminal closed, timeout, crash). There's
no reliable "session done" signal. The safety net is the **next
session's kickoff**.

**Stop hook (best-effort):** When the session ends normally, the
Stop hook detects we're on a free-session branch and raises a
concern: "You're on branch `<name>` with N commits. Run
`/xp-free-close` to review and merge, or leave it for next session."
This is advisory — Stop hooks can't do interactive prompts.

**Kickoff orphan detection (safety net):** At the start of every
session, `/xp-kickoff` checks for orphaned free-session branches:

```bash
git branch --list '<user>/free-*'
```

For each orphaned branch (not the current branch):
1. Show the branch name, age, and commit count.
2. Ask the user: **merge, keep, or delete?**
   - **Merge:** Run the same review + merge flow as sprint-close
     (PR if gh available, `/review`, merge to primary branch).
   - **Keep:** Leave the branch. It will show up again next session.
   - **Delete:** Delete without merging (confirm if unmerged commits
     exist).

### `/xp-free-close` Skill

Optional skill the user can run to cleanly close a free session's
branch. Same flow as `/xp-sprint-close` but simplified:

```
Step 1: Detect merge target (primary branch)
Step 2: Create PR (if gh available)
Step 3: Run /review
Step 4: Present findings, address feedback
Step 5: Ask user: merge?
Step 6: Merge + cleanup + checkout primary branch
```

If the user doesn't run this, the orphan detection at next kickoff
catches it.

---

## Sprint/Plan Review Agent

A new forked agent (`xp-close-reviewer`) that handles the code
review step for sprint-close, plan-close, and free-close. Forking
protects the main agent's context from large diffs.

### Why a Forked Agent

- Sprint/plan diffs can be large (sprint-030 was 819 additions).
  Reading the full diff in the main agent's context eats tokens
  needed for the interactive merge/cleanup flow.
- Same pattern as `xp-code-reviewer` (quality review) — proven
  approach in this codebase.
- Agent returns a structured summary; main agent presents it.

### Agent Inputs

The skill prepares a review input file with:

- `mode`: `"sprint"`, `"plan"`, or `"free"` — determines focus areas
- `pr_number`: PR number if available, null otherwise
- `target_branch`: merge target for diff computation
- `sprint_data`: stories, velocity, milestone (sprint/plan mode)
- `plan_data`: milestones, overall goal (plan mode only)

### Agent Review Instructions

The agent receives these instructions (embedded in agent definition,
not dependent on `/review`):

**Standard review (all modes):**

1. If `pr_number` is set: run `gh pr view <number>` and
   `gh pr diff <number>` to get PR details and diff.
2. If `pr_number` is null: run `git diff <target>...HEAD` to get
   the diff.
3. Analyze the changes for:
   - **Code correctness** — bugs, logic errors, edge cases
   - **Project conventions** — naming, patterns, file organization
   - **Performance implications** — hot paths, O(n) concerns
   - **Test coverage** — are changes tested? gaps?
   - **Security considerations** — injection, auth, data exposure
   - Specific suggestions for improvements
   - Potential issues or risks

**Sprint-level focus (mode = "sprint"):**

4. Cross-cutting concerns across stories — shared patterns that
   diverged, inconsistent error handling, mixed conventions
5. Duplication or near-duplication between stories — code that
   should be extracted or unified
6. API/interface coherence — do the pieces fit together cleanly?
7. Strategic opportunities visible only at sprint scope — patterns
   worth extracting, abstractions that emerged
8. Test coverage gaps across the sprint — are story boundaries
   covered by integration tests?

**Plan-level focus (mode = "plan"):**

4. Architectural coherence across all milestones — does the
   accumulated design hold together?
5. Feature completeness — does the plan achieve its stated goal?
6. Technical debt introduced across sprints — shortcuts that
   compounded
7. Strategic opportunities for the next plan — what should be
   built next?
8. Security posture of the accumulated changes — new attack
   surface?

**Free-session focus (mode = "free"):**

4. Same as standard review — no sprint/plan context to analyze.

### Agent Output

Structured findings, most actionable first:
- Blocking issues (must fix before merge)
- Suggestions (should fix)
- Observations (nice to know)
- Strategic notes (sprint/plan level only)

### Allowed Tools

```yaml
allowed-tools:
  - Bash(gh pr view *)
  - Bash(gh pr diff *)
  - Bash(git diff *)
  - Bash(git log *)
  - Read
  - Grep
  - Glob
```

Read-only — the review agent never modifies code. Fixes happen in
the main agent's context after the review returns.

### Maintenance Note

The standard review instructions are based on the built-in `/review`
skill's prompt. The `/review` skill only accepts PR numbers (not raw
diffs), so we embed equivalent instructions in the agent. If
`/review` improves upstream, sync the standard review section of the
agent definition to match. The prompt is small (~15 lines) and
unlikely to change frequently.

---

## Review Scope by Level

XP says if reviews are good, turn them up. Three review levels, each
seeing a progressively wider scope:

| Level | Trigger | Scope | Catches |
|-------|---------|-------|---------|
| Commit | `/simplify` + `/xp-quality-review` | Single commit | Local quality, bugs, style |
| Sprint | `/xp-sprint-close` | All stories in sprint | Cross-cutting concerns, duplication, API coherence |
| Plan | `/xp-plan-close` | All milestones in plan | Architectural drift, feature completeness, strategic gaps |

Each level uses `/review` but with different context injection to
focus the reviewer on level-appropriate concerns.

---

## Changes to Existing Skills

### `/xp-plan` (create flow)

After the user confirms the milestones (Step 4), add:

1. Agent recommends whether a plan branch makes sense based on
   milestone count and shippability ("This plan has 4 milestones
   that build on each other — recommend a plan branch so
   intermediate work doesn't land on main until the plan is
   complete.").
2. Ask the user: "Create a plan branch?" Yes/No.
3. If yes: create plan branch (`<user>/plan-<slug>`) off the
   primary branch, record in `execution_plan.json` as `branch`.
4. If no: leave `branch` as null.

The recommendation is advisory — the user always decides.

### `/xp-sprint-start`

When creating the sprint branch (Stage 2+):

1. Check if execution plan has a `branch` field.
2. If yes: create sprint branch off the **plan branch** (not the
   primary branch).
3. If no: create sprint branch off the primary branch (main at
   Stage 2, integration branch at Stage 3).

### `/xp-sprint-review`

After the sprint-reviewer subagent completes:

1. Suggest running `/xp-sprint-close` to handle branch lifecycle.
2. If the milestone just marked `delivered` is the last milestone
   in the plan AND a plan branch exists: suggest `/xp-plan-close`
   after sprint-close.

### `/xp-kickoff`

Add to the kickoff sequence (after session mode detection):

1. If free session at Stage 1+ and on a protected branch:
   auto-create a free-session feature branch.
2. Check for orphaned free-session branches (`<user>/free-*`).
   For each, ask: merge, keep, or delete.

### `branching.py`

Add functions:

- `get_primary_branch(smm_dir)` — returns `main` at Stages 1-2,
  `integration_branch` at Stage 3. Central function — all merge
  target logic flows through this.
- `merge_branch(cwd, branch, target)` — merge any source branch into
  `target` with `--no-ff`. Used by sprint-close and plan-close.
- `get_merge_target(smm_dir, cwd)` — returns the appropriate merge
  target for the current sprint branch (plan branch >
  primary branch).
- `create_plan_branch(cwd, slug, smm_dir)` — create a plan branch
  off the primary branch.
- `create_free_branch(cwd, slug, smm_dir)` — create a free-session
  branch off the primary branch.
- `list_free_branches(cwd, user_ns)` — list orphaned free-session
  branches for cleanup.

### `execution_plan_schema.py`

Add optional `branch` field to plan schema:

- Type: string or null.
- Validated as a valid git branch name pattern.
- Written by `/xp-plan`, read by `/xp-sprint-start` and
  `/xp-sprint-close`.

---

## Interaction with `gh` Availability

The lifecycle must work without `gh`. PR creation and GitHub-based
merge are enhancements, not requirements.

| Capability | With `gh` | Without `gh` |
|-----------|-----------|--------------|
| PR creation | `gh pr create` | Skipped, note in summary |
| Review (agent) | Agent runs `gh pr diff` | Agent runs `git diff` |
| Merge | `gh pr merge` or local | Local `git merge --no-ff` |
| Remote cleanup | `git push --delete` | Skipped (local only) |

The user is always told what happened and what was skipped.

**Note on `/review`:** The built-in `/review` skill only accepts PR
numbers and cannot review a raw diff. The `xp-close-reviewer` agent
embeds equivalent review instructions and adds scope-specific focus
areas, so it works in both modes (PR-based and diff-based) without
depending on `/review`.

---

## Schema Changes

### `execution_plan.json`

```json
{
  "title": "...",
  "branch": "paulingalls/plan-acceptance-testing",  // NEW, optional
  "sources": [...],
  "overview": "...",
  "milestones": [...]
}
```

### `system_context.json` (no changes)

The existing `branching_strategy.integration_branch` field (Stage 3)
is used as-is. Plan branches are orthogonal — they're per-plan, not
per-project.

---

## Lifecycle State Machine

### Sprint Sessions

```
Sprint in-progress
  │
  ▼
/xp-sprint-review (subagent: analysis, velocity, milestone update)
  │
  ▼
/xp-sprint-close (main agent: PR, review, merge, cleanup)
  │
  ├── Sprint branch → plan branch (if plan branch exists)
  │     │
  │     ├── More milestones remaining → next sprint starts
  │     │
  │     └── Last milestone delivered
  │           │
  │           ▼
  │         /xp-plan-close (PR, review, merge → primary branch)
  │
  └── Sprint branch → primary branch (if no plan branch)
        │
        ▼
      Done. On primary branch.
```

### Free Sessions

```
/xp-kickoff detects free session + protected branch
  │
  ▼
Auto-create <user>/free-<date>-<slug>
  │
  ▼
User works (commits go to free branch)
  │
  ├── User runs /xp-free-close → PR, review, merge, cleanup
  │
  └── Session ends without close
        │
        ▼
      Next session kickoff detects orphan → merge/keep/delete
```

---

## Open Questions

- **Auto-suggest vs auto-run.** Should `/xp-sprint-review` auto-chain
  into `/xp-sprint-close`, or just suggest it? Leaning: suggest, let
  the user trigger. Sprint-review is analysis, sprint-close is action.
- **Plan branch rebase policy.** If the primary branch advances while
  a plan branch is in flight, should `/xp-sprint-start` rebase?
  Leaning: no automatic rebase. Raise a concern if plan branch
  diverges significantly.
- **Sprint branch pushed on creation vs on close.** Currently sprint
  branches stay local. Should `/xp-sprint-start` push at Stage 2+?
  Leaning: push on close (when creating the PR), not on creation.
- **Review prompt customization.** Resolved: `xp-close-reviewer`
  agent embeds review instructions (based on `/review`'s prompt)
  plus scope-specific focus areas. Works with PR or raw diff. No
  dependency on the built-in `/review` skill.
- **Free branch goal slug.** Should the slug come from the session
  goal recorded in work selection, or should the user name it?
  Leaning: auto-slug from goal, user can rename.
- **Free branch PR review threshold.** Should `/xp-free-close` skip
  the review for tiny changes (1-2 commits, <50 lines)? Leaning: no,
  always review. Consistency over optimization.

---

## Status

Design draft. Intended as the source for an execution plan that
implements sprint-close, plan-close, and free-session branch
lifecycle skills. Addresses the gap discovered in sprint-030 where
no post-sprint branch management existed.

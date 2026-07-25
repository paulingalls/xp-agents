# Branching Doctrine

## Purpose

Define how branches and integration flow map to the plugin's work units
(story → sprint → milestone), what discipline the plugin enforces, and
how projects that arrived from a looser configuration migrate to the
supported floor.

---

## Principle

The plugin is opinionated about the floor. Projects that adopt
xp-agents are typically building a production product with multiple
contributors, CI, and review discipline — not a weekend prototype. The
floor reflects that.

- **Stage 2 — Integration** is the **enforced floor**. Every project
  the plugin actively manages operates at Stage 2 or higher.
  Sprint branches off `main`; story branches off the sprint branch;
  milestones land on `main` via PR.
- **Stage 3 — Release flow** is **supported and recommended** for
  projects with multiple environments (dev/staging/prod), scheduled
  releases, downtime sensitivity, or regulated release discipline.
  Stage 3 layers an integration branch (`develop`/`staging`) between
  sprint branches and `main`.
- **Stages 0 and 1 are not supported targets.** Stage 0 (trunk
  commits straight to `main`) sits below the floor and receives a
  migration prompt at session start. Stage 1 (story branches off
  `main`, no sprint integration) is auto-promoted to Stage 2 the next
  time `branching.py` resolves the project's stage. Both are
  documented in the "Legacy / Migration" section below for migration
  purposes only.

**Free sessions are the lightweight escape hatch**, available at every
stage. A free session creates a single `<user>/free-YYYY-MM-DD-<slug>`
branch off the primary branch and merges back via `/xp-free-close`. It
is the right answer for a five-minute fix, a one-off chore, or
exploratory work that doesn't justify a sprint — the path users should
reach for instead of dropping the project to a lower stage.

---

## Supported Stages

### Stage 2 — Integration (enforced floor)

**Structure.**
- Sprint gets its own branch: `<user>/sprint-NNN-<slug>` off `main`.
- Stories branch off the sprint branch.
- Story done (acceptance green) → merge-commit into sprint branch
  (local, direct).
- Milestone delivery (sprint-review flips milestone to `delivered`) →
  **PR** from sprint branch to `main`. CI gates the merge.
- Merge style: merge-commit (`--no-ff`) at every integration point.

**Why this is the floor.** Stage 2 is the lowest configuration that
delivers all four production-discipline guarantees the plugin assumes:

1. **Per-sprint integration boundary.** A sprint branch collects N
   stories before they land on `main`, so reviewers see one coherent
   PR per milestone instead of N micro-PRs.
2. **PR-gated review.** Milestone delivery goes through a PR, which is
   where CI runs, where branch-protection rules apply, and where
   stakeholders comment.
3. **Per-story rollback granularity.** Story branches preserve TDD
   commit history; reverts target story merge-commits cleanly.
4. **Recoverable if a sprint goes sideways.** The sprint branch can
   be abandoned without polluting `main`.

**Plugin behavior.**
- Auto-creates the sprint branch on `/xp-sprint-start`.
- Auto-creates story branches off the sprint branch on story start.
- Gates `main` and sprint-branch commits — `main` is PR-only; the
  sprint branch only accepts merges from story branches, not direct
  commits.
- `/xp-accept` green → dispatches `/xp-story-close`, which merges the
  story branch into the sprint branch and deletes it.
- `/xp-sprint-review` flips the milestone to `delivered`;
  `/xp-sprint-close` then pushes the sprint branch and opens the PR to
  `main`. PR merge happens outside the plugin (human review + CI).

### Stage 3 — Release flow (supported, optional)

**Structure.**
- `main` holds released code only (typically tagged releases).
- An **integration branch** holds current development:
  `develop` or `staging`.
- Sprint branches off the integration branch; stories branch off the
  sprint branch as in Stage 2.
- Milestone delivery → PR from sprint branch to the **integration
  branch**, not `main`.
- Release cut: separate PR from integration branch → `main`,
  typically tagged, typically gated by release criteria.

**Recommended when** any of these apply:

- Multiple deployed environments need to be kept in sync.
- Releases are scheduled (weekly/monthly), not continuous.
- Compliance or change-management policy requires a release record
  separate from the integration log.
- The project ships SDKs or libraries where consumers depend on
  stable tagged versions.

**Plugin behavior.**
- All Stage 2 behaviors, plus:
- PR target for milestone delivery is the integration branch (name
  declared in `system_context.json`).
- Direct commits gated on **both** `main` and the integration branch.
- Release cuts are customer-initiated; the plugin does not auto-cut
  releases in v1.

---

## Free Sessions

Free sessions exist at every stage as the **low-ceremony escape
hatch** for work that doesn't fit a sprint:

- A typo fix, a dependency bump, a docs tweak.
- An exploratory spike to learn whether an approach is viable before
  committing to a sprint.
- A one-off chore: regenerating a fixture, rotating a test secret,
  cleaning up a stale ignore file.

**Branch shape.** `<user>/free-YYYY-MM-DD-<slug>` cut directly off the
primary branch (Stage 2: `main`; Stage 3: the integration branch). No
sprint branch, no plan branch, no milestone.

**Merge path.** `/xp-free-close` runs review, pushes the branch, and
opens a PR (or merges locally if `gh` is unavailable). Same review
gates as a sprint-derived PR — free does not mean unreviewed.

**When to use a free session vs starting a sprint.**

- **Free.** Single concern, one or two commits, no need to coordinate
  with a milestone, fits in one session.
- **Sprint.** Multiple stories, acceptance criteria worth tracking,
  cross-story dependencies, or work that benefits from milestone
  framing.

If you find yourself reaching for "Stage 1 because the sprint setup
feels heavy for this," reach for a free session instead. That is the
ceremony-light path the plugin supports.

---

## Legacy / Migration

The two stages below are **not supported as adoption targets**. They
exist in this document so projects arriving from them know what they
look like, why the plugin moved past them, and how to migrate.

### Stage 0 — Trunk (below floor)

**What it looks like.** Everything commits to `main`. No branches,
no PRs, no integration step. Solo workflows or pre-project
prototypes typically start here.

**Why it is not a supported target.** Stage 0 supplies none of the
four guarantees enumerated in §Stage 2 — no integration boundary, no
PR-gated review, no rollback granularity, no recoverable sprint
abandonment. As soon as a project has more than one contributor,
CI, or production users, Stage 0 actively hides risk: changes land
on `main` with no review surface to catch them.

**Free sessions cover the looser-work use case.** The "I just want
to commit and go" workflow that Stage 0 enables is preserved by
free sessions — same number of commits, same lack of sprint
ceremony, but the change still lands via PR with a review gate.

**Migration to Stage 2.** When `/xp-kickoff` runs at session start
on a Stage 0 project, Step 0 first runs `/xp-system-context` (which
records the stack and sets the branching stage), then prompts the
customer to migrate via `/xp-stage-migration`. On accept, that skill
writes the Stage 2 floor directly (`edit-branching-field stage`) — no
sprint or plan required, which a fresh project lacks. A project may
decline and explicitly declare Stage 0 in `system_context.json`, but
migration concerns continue if signals (contributor count, CI presence,
branch-protection rules) suggest the project has outgrown it.

### Stage 1 — Story branches (deprecated waystation)

**What it looks like.** Every story gets its own branch
(`<user>/story-NNN-<slug>` off `main`). On acceptance, the story
branch merges directly back into `main` — no sprint branch, no
milestone PR. Historically Stage 1 served solo serious work and
trusted small teams that wanted per-story isolation but didn't want
sprint scaffolding.

**Why it is not a supported target.** Stage 1 sits halfway between
Stage 0's no-isolation and Stage 2's integration boundary, and the
half-step costs more than it pays. Stories merge straight to `main`
with no sprint-level integration, so:

- No PR-gated review point — story-branch merges are local, so CI
  never sees a coherent integrated change.
- Reviewers face N micro-PRs per milestone instead of one,
  multiplying the review tax.
- A failed story leaves stale branches and partial state on `main`
  rather than confined to a discardable sprint branch.

**Free sessions cover the looser-work use case.** The two draws
that historically motivated Stage 1 — per-change branch isolation
and skipping sprint ceremony — are both preserved by free sessions,
which run through the same review surface that Stage 2 sprints use.
A free branch isolates the work and merges via PR, which is closer
to the spirit of "review before main" than Stage 1's
local-merge-back-to-main ever was.

**Migration to Stage 2 (auto-promote).** As of v3.1, projects on
Stage 1 are auto-promoted to Stage 2 the next time `branching.py`
resolves the project's stage. The promotion mutates
`system_context.json` in place and records a one-time `decision`
event (`metadata.action=stage_auto_promote`) so the change is
auditable. No customer action required; the next sprint runs at
Stage 2. Once promoted, every read returns Stage 2 and the new
gate applies repo-wide — including to any Stage 1 story branches
already in flight. Land those branches manually (via PR to
`main`) before starting Stage 2 work, since `/xp-accept` will
no longer have a Stage 1 merge path to take.

---

## User Namespacing

Multiple users can run xp-agents against the same repo. Branches are
always user-namespaced to prevent collisions.

- **Namespace source.** A recorded
  `branching_strategy.user_namespace` in `system_context.json` WINS
  when present and usable. It is user-editable (`system_context_cli
  edit-branching-field`); unusable values — leading dash, whitespace,
  or a second `/` segment the branch-name parsers cannot read back —
  are ignored here and rejected at write time.
  Only when no usable override is recorded does the namespace come
  from git identity: `git config user.email` → local-part slug
  (`paul@paulingalls.com` → `paul`), then `user.name` slug if email
  is unset, then the literal `user`.
  `identity.user_namespace()` is the one answer branch WRITERS mint
  under; `identity.git_user_namespace()` exposes the git-derived value
  alone.
- **Readers search both.** `branching.list_user_branches` (behind
  `list_free_branches`, `list_story_branches` and so kickoff's orphan
  triage and free-close discovery) and
  `branch_resolution._slug_rebuilt_sprint_branches` glob the recorded
  namespace AND the git-derived one, deduped. Branches cut before the
  override was read carry the git prefix, and a reader that saw only
  the override would hide all of a user's existing work on the very
  upgrade that introduces one. This widens to the same user's older
  prefix, never to another user's.
- **Branch shapes.**
  - `<user>/story-NNN-<slug>` — including teammate branches. A
    teammate does **not** get a branch shape of its own; it inherits
    the spawning user's namespace and the ordinary story shape, with
    the slug suffix optional (`identity._STORY_BRANCH_RE` accepts
    both). Only the *worktree* carries the `worktree-story-NNN` name.
  - `<user>/sprint-NNN-<slug>`
  - `<user>/plan-<slug>`
  - `<user>/free-YYYY-MM-DD-<slug>`
  - `<user>/scaffold` — one shared branch per
    `/xp-scaffold-acceptance` invocation, surface-independent, so a
    multi-surface loop lands on it rather than chaining.
- **Rationale.** Two users creating `story-042` independently never
  collide on push. Reviewers see at a glance who originated a branch.
  Teammate branches stay visually grouped with their lead's work.

---

## Gate and Auto-Create

Both mechanisms cooperate. They are defense-in-depth.

**Auto-create** runs at work transition points (sprint start, story
start, free start) when the working tree is clean. It creates and
checks out the appropriate branch.

**Gate** runs at commit time (PreToolUse:Bash on `git commit`) and
raises a concern if the current branch is protected at the project's
declared stage.

Auto-create prevents most wrong-branch situations. The gate catches
what slips through — pre-kickoff work, manual checkouts, crashed
sessions, human error.

### Escape Hatch for Legitimate `main` Commits

Some commits legitimately belong on `main` — release commits, version
bumps, changelog updates, one-off chores. These use a
commit-message subject-line prefix (the gate inspects the first
line of the commit message):

- `[release]` — version bumps, changelog updates, tag preparation
- `[chore]` — one-off maintenance not tied to a story (dependency
  bumps, config tweaks, housekeeping)

A third prefix, `[sprint-direct]`, is also recognized by the gate
but is reserved for the `/xp-story-close` merge window that
`/xp-accept` dispatches — end users do not type it manually.

The gate detects these prefixes, allows the commit, and records it as
a `status` event labeled with the prefix. Silent direct-to-main commits
without a prefix remain a concern.

### Preconditions for Auto-Create

- **Clean working tree.** If dirty, raise a concern and ask; do not
  autostash — autostash hides work.
- **Up-to-date base.** If local base branch is behind origin, fetch
  and either rebase or prompt, per policy.
- **Branch does not already exist.** If it does, check it out
  (resuming a story mid-flight); do not recreate.

Failures fail loud — no partial state, no silent continuation on the
wrong branch.

### Stage-Appropriate Gate Enforcement

| Stage | `main` gated? | integration branch gated? | sprint branch gated? |
|-------|---------------|---------------------------|----------------------|
| 0 | No (declared-only; receives migration prompt at session start) | — | — |
| 2 | Yes (PR-only) | — | Yes (accepts merges from story branches, not direct commits) |
| 3 | Yes (release-PR only) | Yes (concern + escape) | Yes (same as Stage 2) |

Stage 1 is omitted: any project resolving to Stage 1 is auto-promoted
to Stage 2 before the gate evaluates the commit.

---

## Migration Between Stages

### Detection Signals

`/xp-system-context` inspects the repo and proposes a stage:

- `git shortlog -sn --all --since="90 days ago"` — contributor count.
  >1 = team signal.
- `.github/workflows/`, `.gitlab-ci.yml`, `.circleci/`, `jenkins*.yml`
  — CI presence.
- Existing branches: `develop`, `staging`, `release/*`, `rc/*` — release
  flow signals.
- Recent commit cadence to `main` (direct commits vs merge commits) —
  how much trunk discipline already exists.
- `CODEOWNERS`, `.github/pull_request_template.md`, branch-protection
  references in README — review-discipline signals.

These signals produce a **recommended** stage. The customer either
migrates, or explicitly declares a different stage in
`system_context.json` with rationale.

### Migration Nudges (Concerns)

The interesting migration gradient under the current floor is
**Stage 2 → Stage 3** — some projects benefit from a release-flow
configuration, others are right to stay at Stage 2 indefinitely.
When signals justify Stage 3, `/xp-system-context` raises an
actionable concern with specific next steps:

> *"Repo signals suggest Stage 3 may fit (`develop` branch present,
> `release/*` tags in history, deploy workflows targeting both
> `staging` and `production`), but the project is declared at
> Stage 2 with milestone PRs landing on `main`. To migrate, re-run
> `/xp-system-context` and declare Stage 3 with the integration
> branch name; subsequent milestone PRs will retarget the
> integration branch and `main` becomes release-only. To dismiss,
> re-run `/xp-system-context` and re-confirm Stage 2 with rationale
> (e.g., 'single deployment environment, continuous release')."*

Both paths route through `/xp-system-context`, which writes the
declaration via the `system_context_cli.py edit-branching` surface
— end users do not edit the SMM JSON by hand, and there is no
need to touch `branching_strategy` outside this skill. Stage 0 →
Stage 2 migrations follow the same pattern via `/xp-stage-migration`,
invoked from kickoff **Step 0**.

The plugin's role is the declaration: changing branch-protection
rules, retargeting open PRs, and reserving `main` for releases are
follow-up actions the customer takes outside the plugin.

Concerns are never hard blocks — they surface the gap and point at the
next step. The customer resolves by migrating, or by declaring the
current stage explicitly with rationale.

### Explicit Stage Declaration

A project declares its stage explicitly via `/xp-system-context`,
which records the declaration in `system_context.json`. The
rendered "Branching Strategy" view (e.g., in human-readable
summaries) looks like:

```markdown
## Branching Strategy

- **Stage:** 2 (sprint integration, milestone PRs to main)
- **Integration branch:** main
- **Protected branches:** main
- **Users (namespaces):** paul, alice
- **PR target for milestone delivery:** main
- **Rationale:** 3-person team; CI on main; no staging environment
  yet. Will revisit Stage 3 when staging lands.
```

Explicit declaration overrides signal-based inference. It commits the
customer to that stage — the plugin enforces the corresponding gate
and auto-create behavior from there. (Stage 1 declarations are
auto-promoted to Stage 2 by `branching.py`; see Legacy / Migration.)

---

## How Skills Use This Doctrine

- **`/xp-system-context`** — detects branching signals, proposes a
  stage, writes the "Branching Strategy" section, raises migration
  concerns for signal/declaration mismatches.
- **`/xp-sprint-start`** — creates the sprint branch. Sprint branches
  are mandatory under the Stage 2 floor. It does **not** create the
  first story branch: `/xp-schedule` JIT-creates it on a solo
  frontier, and `/xp-assign` creates each teammate branch at spawn.
- **`/xp-accept`** — on story green, dispatches `/xp-story-close`,
  which merges the story branch into the sprint branch and deletes
  it. Accept itself does not touch branches.
- **`/xp-sprint-review`** — flips the milestone to `delivered` and
  records velocity. It does not push or open a PR.
- **`/xp-sprint-close`** — pushes the sprint branch (Step 2) and
  opens the PR to the integration branch (Step 3; Stage 2: `main`,
  Stage 3: `develop` or `staging`), then merges and cleans up.
- **`/xp-free-close`** — pushes the free branch and opens a PR (or
  merges locally without `gh`). Used after any free session
  regardless of stage.

---

## Analysis vs Scaffolding

`/xp-system-context` is read-only. It does **not** configure branch
protection rules, enable CI workflows, write PR templates, or push
branches on the customer's behalf. It raises concerns that tell the
customer what's missing and what to do.

A dedicated scaffolding skill for branching setup (branch-protection
rules, CI workflows, PR templates) is deferred. Acceptance scaffolding
has since shipped as `/xp-scaffold-acceptance`; a branching-setup
equivalent still belongs in its own holistically-designed skill
alongside the broader workflow-setup story.

---

## Team Scenarios

These behaviors address multi-contributor and long-lived branch
workflows. Implemented in M-5 of the branch-lifecycle plan.

### Pre-Existing Branch Detection

When `create-sprint` or `create-plan` finds a branch that already
exists locally (from a prior session, a failed attempt, or another
contributor), the CLI reports `resumed: <branch>` instead of
`created: <branch>`. The calling skill detects the prefix and
prompts the user interactively:

- **Sprint branch:** "Adopt this branch for the new sprint, or
  delete and recreate?"
- **Plan branch:** "Adopt this branch for the new plan, or choose
  a different slug?"

The CLI never silently overwrites or resumes without signaling. The
user always knows whether they're on a fresh branch or an existing
one.

### Divergence Handling

When a plan branch falls behind the primary branch (because primary
advanced while the plan is in flight), `check-divergence` counts
the gap. At 10+ commits behind (configurable), it raises a concern
with a suggested action:

```
git merge main
```

The suggestion is always **merge, not rebase**. Rebase rewrites
shared history — unsafe when multiple contributors share a plan
branch. Merge preserves all commits and surfaces conflicts at merge
time rather than silently rewriting.

The divergence check runs automatically at sprint-start (after
creating the sprint branch off the plan branch). The threshold is
configurable via `--threshold N`.

### Rebase Discipline

No automatic rebase anywhere in the branch lifecycle. The plugin
uses `--no-ff` merges at every integration point (story → sprint,
sprint → plan, plan → primary). This preserves the full commit
history and makes merge boundaries visible in `git log --graph`.

When conflicts arise during a merge (sprint-close, plan-close),
the plugin surfaces them to the user — it never auto-resolves.
Conflict resolution is a human decision.

### Remote Push Timing

All branches stay local until close time:

| Branch type | When pushed |
|-------------|-------------|
| Story | Never pushed — merged locally into sprint/main |
| Sprint | Pushed by `/xp-sprint-close` (for PR creation) |
| Plan | Pushed by `/xp-plan-close` (for PR creation) |
| Free | Pushed by `/xp-free-close` (for PR creation) |

Pushing at close (not at creation) keeps the remote clean. Only
branches ready for review and merge appear on the remote. Without
`gh`, the push is skipped and the merge happens locally.

---

## Implementation References

| Concern | File |
|---------|------|
| Branch lifecycle + divergence check | `plugins/xp-agents/scripts/branching.py` (`get_branching_stage` auto-promotes Stage 1 → 2) |
| CLI dispatch (`created:` / `resumed:` output) | `plugins/xp-agents/scripts/branching_cli.py` |
| `main` / sprint commit gates | `plugins/xp-agents/scripts/pre_tool_bash.py` |
| User namespace derivation | `plugins/xp-agents/scripts/identity.py` |
| `branching_strategy` schema validation | `plugins/xp-agents/smm/system_context_schema.py` |
| Stage declaration surface | `plugins/xp-agents/smm/system_context_cli.py` (`edit-branching`) |
| Stage detection | `plugins/xp-agents/agents/xp-system-analyzer.md` (Step 3.5) |
| Sprint branch creation | `plugins/xp-agents/skills/xp-sprint-start/SKILL.md` |
| Story branch creation (solo JIT / teammate at spawn) | `plugins/xp-agents/skills/xp-schedule/SKILL.md`, `plugins/xp-agents/skills/xp-assign/SKILL.md` |
| Plan branch creation + pre-existing detection | `plugins/xp-agents/skills/xp-plan/SKILL.md` |
| Story branch merge / delete | `plugins/xp-agents/skills/xp-story-close/SKILL.md` |

Post-sprint branch lifecycle (sprint/plan branch cleanup beyond the
per-story delete-on-accept) is designed separately in
`docs/completed/BRANCH_LIFECYCLE.md`.

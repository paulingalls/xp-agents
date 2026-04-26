# Branching Doctrine

## Purpose

Define how branches and integration flow map to the plugin's work units
(story → sprint → milestone), and how projects migrate from ad-hoc flow
toward production-grade branching discipline as they mature.

---

## Principle

Branching discipline is a spectrum. Every project sits somewhere on it
and may migrate toward higher discipline as it matures. The plugin's
job is to meet the project where it is and nudge it forward — not to
impose release-flow ceremony on a weekend prototype, nor to silently
tolerate "commit-straight-to-main" on a production system with four
contributors and CI.

**The plugin's floor is Stage 1.** Projects that adopt this plugin are
typically building a production product, not a proof-of-concept. Stage 0
is named for completeness and describes the state of repos before the
plugin adopts them. Once the plugin is active, Stage 1 or higher is
expected. A project explicitly declaring Stage 0 is tolerated but will
keep receiving migration concerns if signals suggest otherwise.

---

## Stages

Four named stages. Each is a discrete, coherent package of branching
behavior.

### Stage 0 — Trunk (below plugin floor)

**Structure.** Everything commits to `main`. No branches, no PRs, no
integration step.

**Appropriate for.** Solo prototype, throwaway experiment, "what if"
exploration before the project is really a project.

**Plugin behavior.** Tolerated when declared, but the plugin does not
enforce Stage 0 as a target. Migration concerns continue if signals
suggest the project has grown past it.

### Stage 1 — Story branches

**Structure.**
- Every story gets its own branch: `<user>/story-NNN-<slug>` off `main`.
- Story done (acceptance green) → merge-commit directly to `main`.
- No sprint branch. No PRs.
- Merge style: merge-commit (preserves TDD granularity in history).

**Appropriate for.** Solo serious work, trusted two-person teams,
private codebases with no CI dependency.

**Plugin behavior.**
- Auto-creates `<user>/story-NNN-<slug>` on story transition to
  `in-progress`.
- Gates direct `main` commits with an actionable concern, with a
  commit-message escape hatch for legitimate main commits (see below).
- `/xp-accept` green → merge story branch into `main` (merge-commit),
  delete story branch.
- No milestone PRs — acceptance is the quality gate; merge follows.

### Stage 2 — Integration

**Structure.**
- Sprint gets its own branch: `<user>/sprint-NNN-<slug>` off `main`.
- Stories branch off the sprint branch.
- Story done → merge-commit into sprint branch (local, direct).
- Milestone delivery (sprint-review flips milestone to `delivered`) →
  **PR** from sprint branch to `main`. CI gates the merge.
- Merge style: merge-commit everywhere.

**Appropriate for.** Team projects, open source, any repo with CI/CD
workflows, any repo with branch protection rules.

**Plugin behavior.**
- Auto-creates sprint branch on `/xp-sprint-start`.
- Auto-creates story branches off the sprint branch.
- Gates `main` + sprint-branch commits (sprint branch only accepts
  merges from story branches, not direct commits).
- `/xp-accept` green → merge story branch into sprint branch, delete
  story branch.
- `/xp-sprint-review` milestone → `delivered` → opens PR from sprint
  branch to `main`. PR merge happens outside the plugin (human/CI).

### Stage 3 — Release flow

**Structure.**
- `main` holds released code (tagged releases only).
- An integration branch holds current development: `develop` or
  `staging`.
- Sprint branches off the integration branch; stories branch off sprint
  as in Stage 2.
- Milestone delivery → PR from sprint branch to the **integration
  branch**, not `main`.
- Release cut: separate PR from integration branch → `main`, typically
  tagged, typically gated by release criteria.

**Appropriate for.** Production systems with multiple environments
(dev/staging/prod), downtime sensitivity, scheduled releases, or
regulated release discipline.

**Plugin behavior.**
- All Stage 2 behaviors, plus:
- PR target for milestone delivery is the integration branch (name
  declared in `system_context.md`).
- Release cuts are customer-initiated; the plugin does not auto-cut
  releases in v1.
- Gates direct commits to both `main` and the integration branch.

---

## User Namespacing

Multiple users can run xp-agents against the same repo. Branches are
always user-namespaced to prevent collisions.

- **Namespace source.** `git config user.email` → local-part slug
  (`paul@paulingalls.com` → `paul`). Fallback: `user.name` slug if
  email is unset.
- **Branch shapes.**
  - `<user>/story-NNN-<slug>`
  - `<user>/sprint-NNN-<slug>`
  - `<user>/teammate-story-NNN` — replaces the current bare
    `teammate-story-NNN`; teammates inherit the spawning user's
    namespace rather than the teammate's own git config.
- **Rationale.** Two users creating `story-042` independently never
  collide on push. Reviewers see at a glance who originated a branch.
  Teammate branches stay visually grouped with their lead's work.

---

## Gate and Auto-Create

Both mechanisms cooperate. They are defense-in-depth.

**Auto-create** runs at work transition points (sprint start, story
start) when the working tree is clean. It creates and checks out the
appropriate branch.

**Gate** runs at commit time (PreToolUse:Bash on `git commit`) and
raises a concern if the current branch is protected at the project's
declared stage.

Auto-create prevents most wrong-branch situations. The gate catches
what slips through — pre-kickoff work, manual checkouts, crashed
sessions, human error.

### Escape Hatch for Legitimate `main` Commits

Some commits legitimately belong on `main` — release commits, version
bumps, changelog updates, one-off chores. These use a commit-message
prefix:

- `[release]` — version bumps, changelog updates, tag preparation
- `[chore]` — one-off maintenance not tied to a story (dependency
  bumps, config tweaks, housekeeping)

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
| 0 | No | — | — |
| 1 | Yes (concern + escape-hatch prefix) | — | — |
| 2 | Yes (PR-only) | — | Yes (accepts merges from story branches, not direct commits) |
| 3 | Yes (release-PR only) | Yes (concern + escape) | Yes (same as Stage 2) |

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
`system_context.md` with rationale.

### Migration Nudges (Concerns)

When signals justify a higher stage than the project currently operates
at, `/xp-system-context` raises an actionable concern with specific
next steps:

> *"Repo signals suggest Stage 2 is appropriate (4 contributors in last
> 90 days, `.github/workflows/ci.yml` present, 12 merged PRs in
> history), but current pattern is Stage 1 (direct-to-main merges on
> story accept). Consider migrating: require PRs for milestone
> delivery, enable branch protection on `main`, wire sprint-branch CI
> runs. To dismiss, declare Stage 1 explicitly in `system_context.md`
> with rationale."*

Concerns are never hard blocks — they surface the gap and point at the
next step. The customer resolves by migrating, or by declaring the
current stage explicitly.

### Explicit Stage Declaration

A project declares its stage explicitly in `system_context.md`:

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
customer to that stage — the plugin enforces Stage-2 behaviors from
there.

---

## How Skills Use This Doctrine

- **`/xp-system-context`** — detects branching signals, proposes a
  stage, writes the "Branching Strategy" section, raises migration
  concerns for signal/declaration mismatches.
- **`/xp-sprint-start`** — creates the sprint branch (Stage 2+); writes
  the first story branch off the sprint branch (or off `main` at
  Stage 1).
- **`/xp-accept`** — on story green, merges the story branch into its
  parent (sprint branch at Stage 2+, `main` at Stage 1), deletes the
  story branch.
- **`/xp-sprint-review`** — on milestone flipping to `delivered`, opens
  a PR from the sprint branch to the integration branch (Stage 2:
  `main`; Stage 3: `develop` or `staging`).

---

## Analysis vs Scaffolding

`/xp-system-context` is read-only. It does **not** configure branch
protection rules, enable CI workflows, write PR templates, or push
branches on the customer's behalf. It raises concerns that tell the
customer what's missing and what to do.

A dedicated scaffolding skill for branching setup is deferred — same
reasoning as for acceptance: scaffolding is opinionated and intrusive,
and belongs in its own holistically-designed skill alongside the
broader workflow-setup story.

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

## Open Questions (Deferred)

- **Release cut automation.** Stage 3 only. Deferred.
- **Escape-hatch interaction with acceptance testing.** Non-issue:
  acceptance is story-level (`/xp-accept`), not commit-level.
  `[release]` commits don't interact with story acceptance.
- **Branch cleanup policy.** Story branches: delete local on accept
  (implemented). Sprint/plan branch cleanup: see
  `docs/ideas/BRANCH_LIFECYCLE.md`.

Resolved in Team Scenarios (M-5):
- ~~Remote push policy~~ → see §Remote Push Timing
- ~~Force-push and rebase discipline~~ → see §Rebase Discipline
- ~~Handling pre-existing branches~~ → see §Pre-Existing Branch Detection

---

## Status

Implemented. Core branching doctrine is integrated into:

- `scripts/branching.py` — branch lifecycle operations + divergence check
- `scripts/branching_cli.py` — CLI dispatch (created/resumed output)
- `scripts/pre_tool_bash.py` — main/sprint branch commit gates
- `scripts/identity.py` — user namespace derivation
- `smm/system_context_schema.py` — branching_strategy validation
- `agents/xp-system-analyzer.md` — stage detection (Step 3.5)
- `skills/xp-sprint-start/SKILL.md` — sprint/story branch creation + divergence check
- `skills/xp-plan/SKILL.md` — plan branch creation + pre-existing detection
- `skills/xp-accept/SKILL.md` — story branch merge/delete

Post-sprint branch lifecycle is designed separately in
`docs/ideas/BRANCH_LIFECYCLE.md`.

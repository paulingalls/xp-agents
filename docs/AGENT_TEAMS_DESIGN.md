# Agent Teams Design — Sprint-Driven XP

## Overview

This document maps XP sprint practices to Claude Code Agent Teams. The core insight: Agent Teams provide the parallel execution engine, xp-agents provides the persistence, ceremony, and coordination layer. Neither alone delivers sprint-driven development — together they do.

Agent Teams are experimental (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), with known limitations that shape this design. The most significant: teams don't survive session resumption. The sprint state must live outside the team.

---

## Vocabulary

| Term | Definition |
|---|---|
| **Session** | A single Claude Code invocation. Has a start (SessionStart hook), work period, and end (SessionEnd hook). Ephemeral — context window, Agent Teams, and all runtime state die at session end. The atomic unit of compute. |
| **Iteration** | One complete plan/work/accept cycle. Cannot cross session boundaries, but multiple iterations can occur within a single session (e.g., accept story A, then plan and implement story B). Marked by an `iteration_complete` status event from `accept_done.py`. |
| **Sprint** | A unit of deliverable work toward a goal. One or more iterations. Persists across sessions via SMM. Has a goal, user stories, and a definition of done. Ends when all stories are done or remaining stories are deferred. |
| **User story** | A customer-meaningful unit of work within a sprint. Has acceptance criteria including e2e test definitions. Right-sized to fit within one iteration (XL stories are split during sprint planning). Persists in `sprint.md` across sessions. |
| **Task** | An implementation step within a story. File-level, TDD-ordered. Ephemeral to the iteration — created during iteration planning, maps to Agent Teams platform tasks. |
| **Acceptance criteria** | Concrete, testable conditions that prove a story is done. Defined at sprint planning time, verified at accept time. Includes e2e test definitions. |
| **File domain** | The set of files/directories a task owns. Used to verify non-overlapping task assignments and enforce coordination boundaries. |
| **T-shirt size** | Rough estimate for user stories: S, M, L, XL. Used during sprint planning to right-size stories. XL = must split. L = full iteration. M = standard. S = can bundle multiple in one iteration. |

---

## Sprint Lifecycle (Cross-Session)

A sprint spans one or more iterations. An iteration cannot cross session boundaries, but a session may contain multiple iterations (each a complete plan/work/accept cycle). The sprint persists in the SMM; each session is ephemeral.

### Sprint Start (First Iteration)

```
Prerequisite: execution_plan.md exists (created via /xp-plan)

/xp-sprint-start reads execution_plan.md
  → Selects [planned] milestones for this sprint
  → Decomposes selected milestone into user stories with context gradient
  → Each story gets acceptance criteria (including e2e test definitions)
  → T-shirt size each story:
      XL → split into smaller stories
      L  → solo iteration, full session
      M  → standard, one per iteration
      S  → bundle multiple in one iteration
  → Order by priority and dependencies
  → Customer confirms sprint scope
  → Writes sprint.md + sprint start event to events.jsonl
  → First iteration begins (plan → work → accept)
```

For the very first session, `/xp-kickoff` detects no active sprint (no `sprint.md`). If `product_spec.md` doesn't exist either, the lead runs `/xp-product-spec` first to gather requirements, then `/xp-sprint-start` to plan the first sprint.

### Mid-Sprint Iterations (Subsequent Sessions)

```
Kickoff (sprint-aware /xp-kickoff)
  → Session retro (reflect before planning — surfaces unanswered questions, Try items)
  → Execution plan check: execution_plan.md exists? NO → /xp-plan
  → Sprint check: sprint.md exists? NO → /xp-sprint-start
  → Housekeeping with Sprint pillar (curates SMM, surfaces unverified assumptions in Risks)
  → Story selection: show ready stories, lead picks for this iteration
      Pick next story(ies) by priority — must fit in one iteration
      Multiple S stories can be bundled if non-overlapping
      Questions about stories resolved here with full sprint context
      Selected stories marked in-progress in sprint.md
  → Clear accept marker (new iteration starting)

No standalone question triage step — questions are handled in the phase where they naturally arise (retro, housekeeping, story selection, plan review), with the best context and the right mindset.

Plan → plan review → execution mode recommendation
  → Plan reviewer recommends solo/subagent/team based on parallelizability

Work (commit-gated review cycle)
  → Red → green → commit (gated: simplify → quality review → security triage)

Accept (/xp-accept, gated at Stop)
  → Verify acceptance criteria for in-progress stories
  → Run e2e tests defined in criteria
  → Mark stories done or deferred in sprint.md
  → In team mode: PR review → merge → integrated e2e
  → Sets accept marker

Stop
  → Accept gate: in-progress stories require /xp-accept before stopping
  → TDD gate: tests must pass
```

### Sprint End (All Stories Done or Deferred)

```
Sprint review (/xp-sprint-review)
  → What shipped vs what was planned (reads sprint.md)
  → Stories completed, deferred, or added mid-sprint
  → Updates execution_plan.md: delivered milestones marked [delivered: sprint-XXX]
  → Writes sprint end event to events.jsonl (velocity stats)

Sprint retro (/xp-sprint-retro)
  → Patterns across all iterations in the sprint
  → Velocity: stories planned vs delivered
  → Were T-shirt sizes accurate?
  → Did the planning game produce right-sized stories?
  → Process improvements for next sprint

Prepare next sprint
  → Deferred stories carry forward to the next sprint
  → /xp-sprint-start reads updated execution_plan.md for next sprint
```

### Failed Stories

A story that fails acceptance goes back to `ready` with failure notes. If time allows, retry in the current iteration. Otherwise it carries to the next iteration. A story that couldn't be completed in its iteration was sized wrong — it should have been split during planning. The sprint retro should flag this for future sizing calibration.

### What Persists Across Sessions

| What | Where | Purpose |
|---|---|---|
| Execution plan | `execution_plan.md` | Full product vision with feature status — feeds sprint planning |
| Sprint goal + stories | `sprint.md` | Current sprint backlog with status, acceptance criteria, priority |
| Velocity data | SMM (`sprint` end event) | Stories planned vs delivered, for future sizing |
| Constraints, risks, wisdom | SMM (curated four-pillar view) | Accumulated project knowledge |
| Session retros | SMM (retrospective events + files) | Trend analysis for sprint retro |

### Planning Hierarchy

| Level | When | Produces | Granularity | Persists? |
|---|---|---|---|---|
| **Execution plan** | Project start | Milestones with change/impact zones | Project-level | Yes — `execution_plan.md` |
| **Sprint planning** | Sprint start | User stories with acceptance criteria, T-shirt sizes, priority order | Customer-meaningful | Yes — `sprint.md` |
| **Iteration planning** | Each session | Tasks with file domains, TDD ordering, parallelization analysis | Implementation-level | No — ephemeral to session |

Product spec answers: **what** is the full product vision?
Sprint planning answers: **which** features are we building now and **how do we know they're done?**
Iteration planning answers: **how** do we build it and **who** does what?

Three levels of persistence:
- **`execution_plan.md`** — ordered milestones with change zones and delivery status. Persists across sprints.
- **`sprint.md`** — current sprint's stories with acceptance criteria and status. Persists across sessions within a sprint.
- **Platform task list** — `~/.claude/tasks/{team-name}/`. Ephemeral, per-team.

The `/xp-assign` skill bridges sprint.md and the platform: it reads stories and creates platform tasks. The lead closes the loop during Accept by verifying acceptance criteria and updating story status in sprint.md.

---

## Iteration Lifecycle (Plan/Work/Accept Cycle)

An iteration is one complete cycle within a session. Every session follows this structure:

### Solo Iteration

```
1. Kickoff (/xp-kickoff, gated at UserPromptSubmit)
   → Retro (reflect before planning)
   → Product spec + sprint checks
   → Housekeeping with Sprint pillar
   → Story selection: pick stories, mark in-progress
   → Clear accept marker

2. Plan (gated at PreToolUse:Write until reviewed)
   → Decompose selected stories into steps
   → Plan review:
     - Quality: right-sized? TDD-ordered? Dependencies correct?
     - Acceptance criteria: what e2e tests prove this works?
     - Execution mode: solo, subagents, or Agent Team?
     - Parallelization: which items can run concurrently? Non-overlapping domains?

3. Work (commit-gated review cycle at PreToolUse:Bash)
   → Red: write failing test (PreToolUse:Write nudges test-first ordering)
   → Green: make it pass
   → Commit: PreToolUse:Bash gates on code file threshold:
       Below threshold → security triage only → commit
       At/above threshold → review cycle:
         /simplify → /xp-quality-review → /xp-security-triage → commit
       Review cycle marker resets after commit

4. Accept (/xp-accept, gated at Stop)
   → Verify acceptance criteria for in-progress stories
   → Run e2e tests defined in criteria
   → Mark stories done or deferred in sprint.md

5. Stop (gated: accept + TDD)
   → Accept gate: blocks if in-progress stories without /xp-accept
   → TDD gate: blocks if tests failing
   → Session end
```

### Team Iteration

When the plan review recommends Agent Teams (cleanly separable domains, genuinely parallel work):

```
1. Kickoff
   → Same as solo

2. Plan
   → Same as solo, but plan review also identifies:
     - Parallel groups with non-overlapping file domains
     - Acceptance criteria per user story AND for the integrated result

3. Spawn
   → Lead runs /xp-assign
   → Skill reads plan, structures tasks with domains and criteria
   → Lead creates Agent Team with tasks

4. Work (each teammate, in parallel)
   → Same commit-gated review cycle as solo (PreToolUse:Bash enforces)
   → Each teammate works within their assigned file domain
   → .coordination.json enforces domain boundaries

5. Accept (/xp-accept, gated at Stop)
   → Lead waits for all teammates to complete
   → If worktrees:
       1. Teammate sends message to lead: "PR #N ready for review"
       2. Lead delegates PR review to a review subagent (preserves lead context)
       3. Lead merges via `gh pr merge`; if merge fails, lead resolves conflicts
       4. Short-lived worktrees rarely conflict; accept that risk
   → If shared checkout: review commits post-hoc or via TaskCompleted hook
   → Run e2e tests against the integrated result
   → Verify acceptance criteria for each story
   → Mark stories done or deferred in sprint.md

6. Stop (gated: accept + TDD)
   → Same gates as solo
```

### Key Design Points

- **Simplify IS the refactor step** in red/green/refactor. It's not a separate ceremony — it's the third beat of TDD.
- **Review cycle is commit-gated, not stop-gated.** When code file count since last review reaches threshold (3+), PreToolUse:Bash blocks the commit until all three reviews complete in sequence: simplify → quality review → security triage. This prevents skipping reviews and works identically for solo agents and teammates.
- **Quality review applies courage.** After simplify recommends changes, quality review checks: did the agent actually implement them? Did they take shortcuts? Are they drifting from SMM constraints? This is valuable for both solo and teammate work.
- **Acceptance is distinct from quality review.** Quality review checks code quality during work. Accept checks that the feature actually works end-to-end after all work is done.
- **In team mode, accept is the synchronization point.** Individual teammates verify their own unit tests, but only the lead can run e2e tests against the integrated result.

---

### When to Use Agent Teams

Agent Teams are the heavy option. Most work should stay solo or use subagents.

| Mode | When | Examples |
|---|---|---|
| **Solo agent** | Sequential tasks, tightly coupled files, small changes. The default. | Bug fixes, refactors, single-module features |
| **Subagents** | Parallel read-only exploration within a single session | Competing hypotheses, multi-file investigation, research |
| **Agent Teams** | Genuinely parallel implementation across cleanly separable domains | New modules with no file overlap, cross-layer features (frontend/backend/tests each independent), large greenfield work |

**Don't use Agent Teams for:** sequential tasks, same-file edits, work with many dependencies, or routine changes. The coordination overhead isn't worth it. A single session or subagents are more effective.

The plan reviewer is in the right position to make this call. It sees the full plan and knows whether the work is sequential, parallelizable, or a mix. It can recommend the execution mode:
- "This is sequential work, execute it in order" → solo
- "Steps 2 and 3 are independent research" → subagents
- "This decomposes into 3 independent modules with no file overlap — consider `/xp-assign`" → teams

---

## Architecture: Two Layers

### Agent Teams Layer (Claude Code platform)

Provides the execution primitives:

| Component | What it does |
|---|---|
| **Team lead** | Main session. Creates team, spawns teammates, coordinates |
| **Teammates** | Independent claude processes coordinated by the lead. Own context windows. Not subagents, but fire SubagentStart/SubagentStop in the lead's hook system. |
| **Task list** | Shared, with states: pending / in-progress / completed. Supports dependencies |
| **Messaging** | Direct (to one teammate) or broadcast. Automatic delivery |
| **Self-claim** | Teammates pick up next unassigned, unblocked task autonomously (file-locked) |
| **Plan approval** | Lead can require teammates to plan before implementing |
| **Quality hooks** | `TeammateIdle` and `TaskCompleted` — exit 2 to reject/continue |

### xp-agents Layer (this plugin)

Provides persistence, ceremonies, and XP enforcement:

| Component | What it does |
|---|---|
| **SMM** | Sprint state persists across sessions even when teams are ephemeral |
| **Sprint entity** | Groups user stories with a goal, tracks progress across sessions |
| **User stories** | Event type with acceptance criteria, dependencies, status |
| **Ceremonies** | Sprint start, planning game, review, retrospective — orchestrated by lead |
| **Hook enforcement** | TDD, lint, conflicts, security, simplify — applies to every teammate automatically |
| **Behavioral guide** | XP values injected into every teammate via SubagentStart |

---

## Teammates vs Subagents

Teammates and subagents are different things that share some hook infrastructure:

| | Subagents | Teammates |
|---|---|---|
| **What they are** | Lightweight instances within a single session (Agent tool) | Independent claude processes coordinated by the lead |
| **Context** | Share lead's session, limited tool access configurable | Own context window, full tool access, don't inherit lead's history |
| **Worktree isolation** | `isolation: worktree` in agent frontmatter | Prompt-driven — tell the lead "use worktrees for teammates" |
| **Lifecycle** | SubagentStart/SubagentStop | Also fire SubagentStart/SubagentStop (quirk of the platform) |
| **Hook events** | PreToolUse/PostToolUse fire | PreToolUse/PostToolUse fire. Stop/SessionStart/SessionEnd/UserPromptSubmit do NOT fire. |
| **Examples in xp-agents** | xp-retrospective, xp-plan-reviewer | Sprint implementation teammates |
| **Model** | Can vary (not yet for teams) | All teammates run same model as lead (Opus 4.6 required) |

Key implication: we cannot define plugin agent files with frontmatter to control teammates. Teammate behavior is shaped by (1) the spawn prompt from the lead, (2) task descriptions, and (3) hooks that fire during their work — especially SubagentStart context injection.

---

## Role Separation

### Team Lead = XP Coach + Customer Proxy

The lead **does not write code**. It orchestrates:

- **Sprint start**: goal setting, spec gathering, planning game
- **Mid-sprint**: spawn teammates via `/xp-assign`, handle questions, unblock dependencies, review PRs, merge
- **Sprint end**: review, retrospective, prepare next sprint
- **Interrupt-driven**: responds to teammate messages, `TeammateIdle` events, `TaskCompleted` events, customer questions

The lead is the customer proxy. When a teammate raises a blocking question:
1. If answerable from sprint specs/SMM — lead answers directly
2. If genuinely new — lead escalates to the actual customer via `AskUserQuestion`

### Teammates = Developers

Teammates **write code**:

- Claim an unblocked user story from the task list
- Execute with full xp-agents hook enforcement (TDD, lint, conflicts, security)
- Small, frequent commits
- Create PR when item is complete (worktree mode) or commit directly (shared checkout)
- Signal done — lead reviews and merges
- Pick up next unblocked item

---

## Best Practices

### Team Size and Structure

Start with 3-5 teammates. This balances parallel work with manageable coordination. Having 5-6 tasks per teammate keeps everyone productive without excessive context switching. Token costs scale linearly — a 3-teammate team runs roughly 3-4x the tokens of a single session doing the same work sequentially.

### Clean Domain Separation Is Everything

Don't let agents touch the same files. Agent teams work best when you can cleanly separate domains — frontend agent stays in the frontend directory, backend agent stays in the backend directory. No overlap. If agents constantly need to read each other's output or modify shared files, the coordination overhead eats into the very parallelism you're trying to gain.

The planning game is where this gets decided. If the plan can't be decomposed into non-overlapping file domains, Agent Teams are the wrong tool.

### Plan First, Then Hand Off

The most effective pattern is: plan first (plan mode), review the plan (`/xp-review-plan`), then hand the plan to a team for parallel execution (`/xp-assign`). Don't jump straight into spawning teammates. Get the architecture and task breakdown right first.

### Feed Context Into Task Descriptions

Teammates don't inherit the lead's conversation history. Whatever context the lead built up before starting the team, teammates won't have it. Our SubagentStart hook injects the curated SMM + behavioral guide automatically, but task descriptions should also embed specific details — file paths, API contracts, acceptance criteria.

### Keep the Lead Coordinating, Not Implementing

The lead should delegate, not implement. Use delegate mode if needed. The lead's job is: spawn team, monitor progress, review work, handle questions, merge changes.

The lead's context window fills fast. Key mitigations:
- **PR reviews → subagent** — lead spawns a review subagent for each PR, gets back a summary. Accept batching (all PRs reviewed at once during Accept) further reduces overhead.
- **Periodic compaction** — lead's context compacts naturally. PostCompact reinjects SMM + sprint status.
- **Lean on the task list** — task states are on disk (`~/.claude/tasks/{team-name}/`), not in context. Lead reads them when needed.
- **Limit broadcast messages** — teammates message lead only for blockers, not status updates. Status is in the SMM.

### Stay Engaged

The user is the project manager. Check progress with Ctrl+T and redirect approaches that aren't working. Agent teams work best as a supervised workflow. Regular check-ins catch problems before they compound.

---

## Worktree Strategy

Worktree isolation for teammates is available but prompt-driven — the lead requests it in the team spawn prompt. It is NOT controlled via agent frontmatter (that's a subagent concept).

### Tradeoffs

| | Without worktrees | With worktrees |
|---|---|---|
| **Conflict detection** | `.coordination.json` works perfectly (absolute paths match) | Needs repo-relative path normalization (absolute paths differ per worktree) |
| **Git operations** | Interfere — `git status` shows all teammates' changes, `git add .` is dangerous | Clean — each teammate has independent staging, status, commits |
| **Feedback timing** | Fail-fast — conflicts blocked at write time | Deferred — conflicts surface at merge/PR time |
| **PR workflow** | Not natural — teammates commit to same branch | Natural — each worktree can branch and PR |
| **Complexity** | Simpler | More git infrastructure to manage |

### Decision Criteria

The `/xp-assign` skill should choose based on the plan:

- **No worktrees** (default): clean domain separation, teammates work on completely different files. `.coordination.json` prevents overlap. Best for most cases, especially when the planning game produces non-overlapping task assignments.
- **Worktrees**: when tasks involve git-heavy workflows (branching, PRs), when the lead wants formal PR review, or when git operation isolation is important (larger teams where `git add .` risk is higher).

### Path Normalization for Worktree Safety

If worktrees are used, `.coordination.json` needs repo-relative paths instead of absolute paths for cross-worktree conflict detection. Current `normalize_path()` uses `os.path.realpath()` which produces absolute paths — the same logical file has different absolute paths in different worktrees:

- Main checkout: `/Users/paul/project/src/app.py`
- Worktree A: `/Users/paul/project/.claude/worktrees/teammate-1/src/app.py`

Fix: normalize to repo-relative paths using `git rev-parse --show-toplevel` to strip the worktree prefix. This makes coordination work across worktrees while remaining backward-compatible for solo mode.

---

## Team Launch Mechanism

### `/xp-assign` Skill

A lead-invoked skill that reads the current plan and creates an Agent Team. The plan reviewer recommends it when the plan has genuinely parallelizable, cleanly separable work.

**Flow:**
1. Plan reviewer reviews the plan, identifies parallel groups with non-overlapping file domains
2. Plan reviewer tells the lead: "This plan has 3 independent modules — run `/xp-assign`"
3. Lead runs `/xp-assign`
4. Skill preload reads the plan file, prepares task structure
5. Skill prompt tells the lead:
   - How many teammates to spawn (based on parallel group count, capped at 5)
   - Task descriptions with acceptance criteria, file domains, and context from the plan
   - Whether to request worktrees (based on overlap analysis)
   - XP rules to include in the spawn prompt (TDD, small commits, PR workflow)

**The skill does NOT spawn the team directly** — it instructs the lead on exactly what to do. The lead creates the team using the platform's built-in mechanism, informed by the skill's structured output.

### What the Spawn Prompt Should Include

The lead's prompt to create the team should include:
- Task descriptions with file domains and acceptance criteria
- "Do not modify files outside your assigned domain"
- "Follow TDD — write tests first"
- "Make small, frequent commits"
- Worktree request if applicable: "Use worktrees for each teammate"
- Context: relevant architectural decisions, API contracts, conventions from the SMM

SubagentStart automatically injects the full curated SMM + behavioral guide on top of this.

---

## XP Practices Mapped to Agent Teams

### Planning Game (Two Levels)

**Sprint planning** (once per sprint):

| XP Concept | Mechanism |
|---|---|
| Customer sets priorities | Lead collects sprint goal via `AskUserQuestion` |
| Stories with acceptance criteria | Lead decomposes goal into user stories with e2e test definitions |
| Estimates | T-shirt sizing: S/M/L/XL. XL stories must be split. |
| Dependencies identified | Story dependencies determine iteration ordering |

**Iteration planning** (each session):

| XP Concept | Mechanism |
|---|---|
| Pick next stories | Lead selects by priority from backlog — must fit one iteration |
| Decompose into tasks | Plan mode produces implementation steps with file domains |
| Plan review | Quality + acceptance criteria + execution mode + parallelization |
| Developer picks task | In team mode, teammates self-claim from shared task list |

### Small Releases

| XP Concept | Agent Teams Mechanism |
|---|---|
| Release early and often | Teammates make small, frequent commits |
| Integration | Worktree mode: per-item PRs. Shared checkout: direct commits to branch |
| Working software | Each merged PR / committed item is a working increment |

Merge strategy: **per-story, not per-sprint**. Each completed user story produces a deliverable. Lead reviews and merges. This:
- Unblocks dependent items sooner
- Keeps merge conflicts small
- Gives the lead incremental verification points
- Matches existing `bash_post_tool.py` commit size checks

### TDD

| XP Concept | Agent Teams Mechanism |
|---|---|
| Test first | `pre_tool_write.py` TDD order check applies to every teammate (PreToolUse — confirmed working) |
| Tests must pass | Stop doesn't fire for teammates. `TeammateIdle` + `TaskCompleted` handlers enforce TDD. |
| Red-green-refactor | Each teammate follows the cycle independently |

### Pair Programming → PR Review

| XP Concept | Agent Teams Mechanism |
|---|---|
| Two sets of eyes | Teammate implements, lead reviews work |
| Knowledge sharing | Decisions and discoveries broadcast via SMM |
| Quality gate | Lead can reject with feedback |

Traditional pair programming doesn't map to Agent Teams (teammates work independently). Lead review is the closest analog. Skip `/xp-quality-review` on teammates — lead reviews instead, avoiding double cost.

### Collective Code Ownership

| XP Concept | Agent Teams Mechanism |
|---|---|
| Anyone can change any code | All teammates share the same codebase |
| Shared understanding | SMM injected into every teammate via SubagentStart |
| Conflict prevention | `.coordination.json` tracks working_on across teammates |

The SMM is the mechanism for collective ownership. Every teammate gets the curated SMM + behavioral guide at spawn via SubagentStart.

**Cross-teammate communication** uses native Agent Teams messaging primitives (`message` for direct, `broadcast` for all). No custom communication hooks needed:
- **Routine discoveries** — teammate records a `concern` event in the SMM for persistence. No interruption.
- **Urgent breaking changes** — teammate messages the lead. Lead decides whether to broadcast to affected teammates.
- **Dependency unblocking** — handled automatically by the platform's task dependency system.

Prompt nuggets don't fire for teammates (UserPromptSubmit is lead-only), so mid-session SMM updates aren't visible to running teammates. This is fine — urgent items go through messaging, non-urgent items are in the SMM for the next iteration. The teammate behavioral guide should say: "If you discover something that affects other teammates' work, message the lead immediately."

### Continuous Integration

| XP Concept | Agent Teams Mechanism |
|---|---|
| Integrate frequently | Per-item merges |
| Tests run on integration | Lead verifies tests pass before merging |
| Broken build = stop everything | Lead can broadcast to teammates if integration breaks |

### On-Site Customer

| XP Concept | Agent Teams Mechanism |
|---|---|
| Customer available | Human available via `AskUserQuestion` |
| Customer sets priorities | Sprint goal and spec gathering at sprint start |
| Quick answers | Lead as customer proxy for questions answerable from specs |
| Escalation | Lead escalates genuinely new questions to human |
| Availability gaps | Judgment call on impact — low-impact: record assumption, validate at retro. High-impact: `AskUserQuestion` (blocks, but avoids train wrecks). |

Caution: assumptions that make it into code tend to auto-resolve (the resolution mechanism marks them done), so they never get revisited. The session retro must actively surface unvalidated assumptions to prevent silent drift.

### Retrospective

| XP Concept | Agent Teams Mechanism |
|---|---|
| Session retro | Keep/Fix/Try from the previous session (existing) |
| Sprint retro | Broader analysis across all sessions in the sprint |
| Velocity tracking | Items completed vs planned, carry-over rate |
| Process improvement | Try items become behavioral experiments for next sprint |

Two levels of retrospective:
- **Session retro** (existing `/xp-run-retrospective`): tactical, what happened since last session
- **Sprint retro** (new `/xp-sprint-retro` skill): strategic, patterns across the sprint. Analyzes all session retros from the sprint, sprint velocity (items_planned vs items_delivered vs items_carried), user story completion times, and which stories were reassigned or failed. Did we deliver the sprint goal? What slowed us down? Were estimates accurate? Did the planning game produce right-sized items?

### Sustainable Pace

| XP Concept | Agent Teams Mechanism |
|---|---|
| Don't overcommit | Sprint backlog sized to what can be delivered |
| Track velocity | Items per sprint, used for future planning |
| Carry-over signals | Items carried to next sprint indicate overcommitment |

Sprint 1 has no velocity history — estimate-free, measure what gets done. Sprint 2+: sprint retro reports items_planned vs items_delivered. Long-term: velocity stabilizes and feeds back into the planning game.

---

## New Event Types

### `sprint`

Marks sprint boundaries in the event log. Written by lead at sprint start and end. These are lightweight markers for retro analysis and compaction rules — the full sprint state lives in `sprint.md`.

```json
{
  "type": "sprint",
  "content": "Build user management REST API with auth",
  "metadata": {
    "sprint_id": "sprint-001",
    "action": "start",
    "goal": "Build user management REST API with auth"
  }
}
```

```json
{
  "type": "sprint",
  "content": "Sprint complete: 8/10 stories delivered",
  "metadata": {
    "sprint_id": "sprint-001",
    "action": "end",
    "stories_planned": 10,
    "stories_delivered": 8,
    "stories_carried": 2
  }
}
```

Note: user stories are NOT event types — they live in `sprint.md`, not `events.jsonl`. The event log tracks sprint boundaries for retro analysis; the sprint file tracks the full backlog.

### Goal Completion

In 1.0, goal completion flows through the user — housekeeping asks "are any of these done?" For Agent Teams, the lead manages story lifecycle directly:

- **User stories** have acceptance criteria defined in `sprint.md`. During Accept, the lead verifies criteria are met (runs e2e tests, reviews PRs) and updates story status directly in `sprint.md`.
- **Sprint goals** are complete when all stories in `sprint.md` are done or deferred. The lead writes the `sprint` end event and `/xp-sprint-review` updates `execution_plan.md`.
- **Session goals** are resolved by agents mid-session when the work ships. In sprint mode, story selection replaces per-session goal collection.

Story status lifecycle in `sprint.md`: `ready` → `in-progress` → `done` | `deferred`

---

## Hook Compatibility — Empirical Results (2026-03-23)

### Teammates in the Hook System

Empirical testing confirmed that teammates are independent claude processes that nonetheless appear in the lead's hook system as if they were subagents. This is a platform quirk — SubagentStart/SubagentStop fire for teammates even though they aren't subagents.

| Question | Result |
|---|---|
| Does **Stop** fire for teammates? | **NO.** Stop only fires for the lead. |
| Does **SessionStart** fire for teammates? | **NO.** Only fires for the lead. |
| Does **SessionEnd** fire for teammates? | **NO.** Only fires for the lead. |
| Does **UserPromptSubmit** fire for teammates? | **NO.** Only fires for lead prompts. Messaging a teammate directly does NOT trigger it. |
| Do **plugin hooks** fire for teammates? | **YES.** PreToolUse and PostToolUse fire for teammates with their agent_id and agent_type. |
| Do teammates get unique **session_ids**? | **NO.** All teammates share the lead's session_id. |
| Does **SubagentStart** fire when teammates spawn? | **YES.** agent_type is the teammate's custom type (e.g., "agent-updater"). |
| Does **SubagentStop** fire when teammates finish? | **YES.** Same agent_type. |
| What does **TeammateIdle** provide? | `teammate_name`, `team_name`, `session_id`, `permission_mode`. No agent_id or agent_type. |
| What does **TaskCompleted** provide? | `task_id`, `task_subject`, `task_description`, `teammate_name`, `team_name`. No agent_id. |

### What This Means for xp-agents

**Hooks that work for teammates unchanged:**
- PreToolUse (Write/Edit/Bash) — conflict detection, TDD order, commit-gated review cycle (simplify → quality review → security triage)
- PostToolUse (Write/Edit/Bash) — status tracking, lint, commit parsing
- SubagentStart — SMM + behavioral guide injection (teammates appear here with their agent_type)
- SubagentStop — review step completion tracking

**Hooks that DON'T fire for teammates (lead-only):**
- Stop — no longer used for review gates (moved to PreToolUse:Bash). TDD enforcement at stop time is lead-only.
- SessionStart — no kickoff marker, no retro prep for teammates
- SessionEnd — no session_end event for teammates
- UserPromptSubmit — no customer_input logging, no kickoff gate, no prompt nuggets

**New hooks needed for teammates:**
- TeammateIdle — TDD enforcement (tests must pass before going idle)
- TaskCompleted — TDD enforcement (tests must pass before task marked complete)

### Teammate Detection

Two patterns depending on the hook event:

```python
# In SubagentStart/SubagentStop/PreToolUse/PostToolUse:
# agent_type is the teammate's custom name (e.g., "agent-updater")
def is_teammate_by_agent_type(input_data: dict) -> bool:
    agent_type = input_data.get("agent_type", "")
    if not agent_type:
        return False
    # Not a built-in subagent and not our xp- agents
    if agent_type in ("Explore", "Plan", "general-purpose", "Bash"):
        return False
    if agent_type.startswith("xp-"):
        return False
    return True

# In TeammateIdle/TaskCompleted:
# Has teammate_name field (definitive)
def is_teammate_event(input_data: dict) -> bool:
    return bool(input_data.get("teammate_name"))
```

### Hooks That Work for Teammates (Confirmed)

| Hook | Event | Status |
|---|---|---|
| `pre_tool_write.py` | PreToolUse:Write | Conflict detection, TDD order, plan review gate |
| `pre_tool_bash.py` | PreToolUse:Bash | Security triage gate, file-modification heuristic |
| `post_tool_use.py` | PostToolUse:Write | Status/working_on tracking, conflict detection |
| `lint_check.py` | PostToolUse:Write | Runs linter on written file |
| `bash_post_tool.py` | PostToolUse:Bash | Commit parsing, test results, simplify nudge |
| `subagent_start.py` | SubagentStart | SMM + behavioral guide injection |
| `subagent_stop.py` | SubagentStop | Completion recording |

### Hooks That DON'T Fire for Teammates (No Changes Needed)

| Hook | Event | Why It's Fine |
|---|---|---|
| `session_start.py` | SessionStart | Teammates don't trigger SessionStart — no kickoff marker conflict |
| `retrospective.py` | SessionStart | Teammates don't trigger SessionStart — no retro prep corruption |
| `session_end.py` | SessionEnd | Teammates don't trigger SessionEnd — no event log pollution |
| `kickoff_gate.py` | UserPromptSubmit | Teammates don't trigger UserPromptSubmit — no blocking |
| `user_prompt_log.py` | UserPromptSubmit | Teammates don't trigger UserPromptSubmit — no false customer_input |
| `prompt_nugget.py` | UserPromptSubmit | Teammates don't get nuggets (lead-only), but they DO get SMM via SubagentStart |

### Commit-Gated Review Cycle

Simplify, quality review, and security triage are enforced at **commit time via PreToolUse:Bash**, not at Stop/TeammateIdle. This ensures no commits are missed and works identically for solo agents and teammates.

**Marker file: `.review-cycle-{agent_id}.json`**

```json
{
  "last_review_commit": "abc123def",
  "simplify_done": false,
  "quality_review_done": false,
  "security_review_done": false
}
```

Stored in the SMM directory. Follows the existing `.simplify-{agent_id}.json` tracker pattern. One file per agent.

**PreToolUse:Bash (git commit) — gate logic:**

```python
marker = load_review_marker(smm_dir, agent_id)

# Use git to count code files since last review
staged = git_diff("--cached", "--name-only")
since_review = git_diff("--name-only", f"{marker['last_review_commit']}..HEAD")
code_files = [f for f in set(staged + since_review) if is_code_file(f)]

if len(code_files) >= threshold:
    if not marker["simplify_done"]:
        block("Run /simplify first")
    elif not marker["quality_review_done"]:
        block("Run /xp-quality-review first")
    elif not marker["security_review_done"]:
        block("Run /xp-security-triage first")
    # All done → allow commit
elif not marker["security_review_done"]:
    block("Run /xp-security-triage first")
# Otherwise → allow commit
```

The `elif` chain enforces strict ordering: simplify before quality review, quality review before security triage.

**PostToolUse:Bash (git commit) — bookkeeping:**

After the commit succeeds, update the marker with the new commit hash and reset all flags:

```python
new_hash = git_rev_parse("HEAD")
update_marker(smm_dir, agent_id, {
    "last_review_commit": new_hash,
    "simplify_done": False,
    "quality_review_done": False,
    "security_review_done": False,
})
```

**Who sets the flags:**

| Step | Completion signal | Sets flag |
|---|---|---|
| Simplify | SubagentStop (simplify subagents complete) | `simplify_done: true` |
| Quality review | SubagentStop (quality review subagent completes) | `quality_review_done: true` |
| Security triage | Triage skill/hook completes | `security_review_done: true` |

**Review cycle flow:**

```
Agent tries to commit (threshold met)
  → BLOCKED: "Run /simplify"
  → agent runs /simplify → implements recs → tries to commit
  → BLOCKED: "Run /xp-quality-review"
  → agent runs quality review → implements recs → tries to commit
  → BLOCKED: "Run /xp-security-triage"
  → agent runs security triage → tries to commit
  → ALLOWED → PostToolUse:Bash updates marker (new hash, flags reset)
```

Each review step produces recommendations, the agent implements them, and tries to commit again — hitting the next gate in sequence. No cascade: the `elif` chain enforces strict ordering.

**Same enforcement for solo and teammates:** PreToolUse:Bash fires for all agents. No separate Stop/TeammateIdle logic needed for these gates.

### Remaining TeammateIdle/TaskCompleted Gates

| Gate | Mechanism | Rationale |
|---|---|---|
| TDD (tests pass) | TeammateIdle + TaskCompleted | Can't merge broken tests — enforced when teammate signals done |

TeammateIdle and TaskCompleted use exit 2 + stderr to block. They do NOT support matchers — handlers must do their own filtering.

### Output Mechanism Differences

| Event | Block mechanism | Feedback mechanism |
|---|---|---|
| Stop | `{"decision": "block", "reason": "..."}` via stdout | Reason shown to agent |
| TeammateIdle | `exit 2` + stderr | Stderr fed back to teammate, continues working |
| TaskCompleted | `exit 2` + stderr | Stderr fed back to agent, task NOT marked complete |
| PreToolUse | `exit 2` + stderr OR `permissionDecision: "deny"` | Stderr/reason shown to agent |

---

## Conflict Prevention

### Three Layers

1. **Planning** — `/xp-assign` decomposes work into non-overlapping file domains. Each task gets a `file_domain` declaring which files/directories it owns. This is the primary mechanism — if domains are clean, conflicts don't happen.

2. **Coordination** — `.coordination.json` blocks overlapping writes at PreToolUse time. Deterministic, real-time, already works for teammates. This is the safety net that catches domain violations.

3. **Isolation** (optional) — Worktree isolation prevents git operation interference. Prompt-driven, not enforced by the plugin. A nice-to-have for git hygiene, not required for conflict prevention.

### Path Normalization

Current `normalize_path()` uses absolute paths (`os.path.realpath()`). This works when all teammates share the same checkout. If worktrees are used, the same logical file has different absolute paths per worktree — coordination.json wouldn't detect the conflict.

**Fix needed for worktree support:** normalize to repo-relative paths using `git rev-parse --show-toplevel` to strip the worktree prefix. This makes coordination work across worktrees while remaining backward-compatible for solo and shared-checkout modes.

---

## Integration Points

### Gate Architecture

All enforcement is deterministic and commit-gated. The full gate chain:

| Hook Event | Gate | Enforcement |
|---|---|---|
| **UserPromptSubmit** | Kickoff gate | BLOCK until `/xp-kickoff` completes (product spec → sprint → retro → housekeeping → story selection) |
| **PreToolUse:Write/Edit** | TDD order | NUDGE: test-first ordering |
| **PreToolUse:Write/Edit** | Plan review gate | BLOCK until plan reviewed |
| **PreToolUse:Write/Edit** | Conflict detection | BLOCK if file owned by another agent |
| **PreToolUse:Bash** (commit) | Review cycle | BLOCK: sequential /simplify → /xp-quality-review → /xp-security-triage (when code file threshold met). Below threshold: security triage only. Reads `.review-cycle-{agent_id}.json` marker. |
| **PostToolUse:Bash** (commit) | Marker update | Records new commit hash in marker file, resets review cycle flags |
| **Stop** | Accept gate | BLOCK if stories in-progress in sprint.md and `/xp-accept` hasn't run |
| **Stop** | TDD gate | BLOCK if tests failing |
| **TeammateIdle** | TDD gate | BLOCK if tests failing |
| **TaskCompleted** | TDD gate | BLOCK if tests failing |

Every phase of the iteration is gated: kickoff (UserPromptSubmit) → plan review (PreToolUse:Write) → review cycle (PreToolUse:Bash) → accept + TDD (Stop). Story selection happens during kickoff; acceptance happens before stop.

### Existing Hooks (Work for Teammates)

- **PreToolUse** (Write/Edit/Bash) — TDD nudge, conflict detection, plan review gate, commit-gated review cycle
- **PostToolUse** (Write/Edit/Bash) — status tracking, lint, commit parsing
- **SubagentStart** — injects curated SMM + behavioral guide at teammate spawn
- **SubagentStop** — records review step completion (simplify done → quality review done → cycle complete)

### Existing Hooks (Lead-Only, No Changes Needed)

- **SessionStart/SessionEnd/UserPromptSubmit/Stop** — don't fire for teammates, no guards needed

### New Hooks for Agent Teams

| Hook Event | Script | Purpose |
|---|---|---|
| `TaskCompleted` | `task_completed.py` | TDD gate (tests must pass before task can complete) |
| `TeammateIdle` | `teammate_idle.py` | TDD gate + check remaining work |

### Lead-Specific Skills

| Skill | Purpose |
|---|---|
| `/xp-plan` | Create or refine `execution_plan.md` — collaborative milestone decomposition from external sources. |
| `/xp-sprint-start` | Read `execution_plan.md` → select milestone → deep codebase dive → decompose into stories → write `sprint.md` |
| `/xp-assign` | Read plan, analyze file domains, structure tasks, instruct lead to create team |
| `/xp-accept` | Verify acceptance criteria for in-progress stories, run e2e tests, update `sprint.md`. Gated at Stop. |
| `/xp-sprint-review` | Compare delivered stories against sprint goal, update `execution_plan.md` milestone status |
| `/xp-sprint-retro` | Cross-session retrospective for the sprint |

### Teammate Behavioral Guide

The current behavioral guide is solo-focused — it tells agents to run kickoff, plan mode, etc. Teammates need different instructions. Options:

- Detect teammate in SubagentStart (via `is_teammate_by_agent_type()`) and inject a trimmed guide
- Add a "For teammates" section to the behavioral guide
- Rely on task descriptions and spawn prompt for teammate-specific rules

The SubagentStart detection approach is cleanest — it's already the injection point, and we already do tiered injection (Explore gets less context than others).

Teammate guide should include:
- **DO:** Claim tasks, write tests first, commit frequently, record decisions/assumptions/concerns, stay within assigned file domain
- **DON'T:** Run kickoff, do housekeeping, set goals, run retrospectives
- **SKIP:** EnterPlanMode (built-in plan approval handles this)
- **KEEP:** TDD discipline, concern recording. Commit-gated reviews (/simplify, /xp-quality-review, /xp-security-triage) are enforced automatically via PreToolUse:Bash — teammates cannot skip them.

---

## SMM Changes

### Four-File Architecture

Sprint and product state live in dedicated files, not the event log. This keeps the curated SMM lightweight — subagents that don't need sprint details (simplify, lint) aren't burdened with them.

```
smm/
├── events.jsonl              ← organic signals (status, concerns, decisions, sprint boundary markers)
├── SHARED_MENTAL_MODEL.md    ← curated four-pillar view (lightweight summary)
├── system_context.md          ← product/system description
├── execution_plan.md          ← milestones with change zones and delivery status
└── sprint.md                 ← current sprint: goal, stories with acceptance criteria and status
```

### Context Injection by Role

| Agent | Gets |
|---|---|
| Simplify/lint subagents | SMM only |
| Plan reviewer | SMM + sprint.md (needs story context to validate plan) |
| Teammates | SMM + their assigned stories from sprint.md |
| Retrospective | SMM + sprint.md (for velocity analysis) |
| Lead | Everything |

### Sprint-Aware Curated View

The curated `SHARED_MENTAL_MODEL.md` gains a Sprint pillar with a **summary**, not the full backlog:

```markdown
# Shared Mental Model

## Sprint
- Goal: Build user management REST API with auth
- Progress: 5/10 stories done, 2 in-progress, 3 ready
- Blockers: Token refresh depends on auth middleware (in-progress)
- Details: see sprint.md

## Intent
...

## Constraints
...

## Risks
...

## Wisdom
...
```

### Housekeeping Sprint Curation

Housekeeping curates the Sprint pillar by:
- Reading `sprint.md` (not the event log)
- Computing progress: N done, N in-progress, N ready, N blocked
- Identifying blockers (stories with unmet dependencies)
- Writing a summary to the Sprint section of curated SMM

### Compaction Rules for Sprint Events

Sprint boundary events in `events.jsonl`:
- `sprint` with `action: "start"` — retain while sprint is active
- `sprint` with `action: "end"` — retain for 1 sprint (velocity data for next planning)

User stories are no longer in the event log — no compaction rules needed for them.

### File Lifecycle

| File | Created by | Updated by | Lifecycle |
|---|---|---|---|
| `execution_plan.md` | `/xp-plan` | `/xp-plan` (new milestones), `/xp-sprint-review` (marks delivered) | Persists across sprints |
| `sprint.md` | `/xp-sprint-start` | Lead (story status during Accept) | Rewritten at each sprint start, deferred stories carry forward |

### `execution_plan.md` Format

```markdown
# Product Spec: User Management System

## Overview
A REST API for user management with authentication, authorization,
and admin capabilities.

## Features

### User Registration [delivered: sprint-001]
- Users can register with email and password
- Passwords stored securely (bcrypt)
- Duplicate emails rejected
- Email validation on registration

### JWT Authentication [delivered: sprint-001]
- Login returns JWT access + refresh tokens
- Protected routes validate tokens
- Token refresh endpoint
- Logout invalidates tokens

### Role-Based Access Control [planned]
- Admin and user roles
- Role assignment by admins
- Route-level role enforcement
- Default role on registration

### SSO Integration [planned]
- Support Google OAuth
- Support GitHub OAuth
- Link SSO accounts to existing users
- Auto-provisioning for new SSO users

## Technical Constraints
- Python 3.10+, FastAPI
- PostgreSQL for storage

## Non-Functional Requirements
- < 100ms response time for auth endpoints
- Rate limiting on login (5 attempts/minute)
```

Milestone status markers: `[planned]`, `[in-progress]`, `[delivered: sprint-XXX]`. `/xp-sprint-start` filters on `[planned]` to know what's left to build. New milestones added via `/xp-plan` always enter as `[planned]`.

### `sprint.md` Format

```markdown
# Sprint: Build user management REST API with auth

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: As a user I can register with email/password
- **Size:** M
- **Status:** done
- **Dependencies:** none
- **Acceptance Criteria:**
  - POST /register creates user with hashed password
  - Duplicate email returns 409
  - E2E: register → verify user exists in DB

### story-002: As a user I can authenticate with JWT tokens
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001
- **Acceptance Criteria:**
  - JWT tokens validated on protected routes
  - Invalid tokens return 401
  - Token refresh endpoint works
  - E2E: register → login → access protected route → verify token

### story-003: As an admin I can list all users
- **Size:** S
- **Status:** ready
- **Dependencies:** story-001
- **Acceptance Criteria:**
  - GET /admin/users returns paginated list
  - Requires admin role
  - E2E: create users → list → verify count
```

Priority is implicit by order — first story = highest priority. Story status: `ready` → `in-progress` → `done` | `deferred`. The lead updates status during Accept after verifying acceptance criteria.

---

## Platform Findings (from docs and empirical testing, 2026-03-23)

### Confirmed Behaviors

- **Teammates are independent processes** — not subagents, but appear in SubagentStart/SubagentStop hooks. Own context windows, own tool access.
- **Teammates load project context automatically** — CLAUDE.md, MCP servers, and skills. Plugin hooks and skills load for teammates.
- **Team config on disk** — `~/.claude/teams/{team-name}/config.json` with `members` array. Teammates can read this to discover each other.
- **Task list on disk** — `~/.claude/tasks/{team-name}/`. Our hooks could read this.
- **Plan approval is built-in** — lead can require teammates to plan before implementing.
- **File conflict is NOT enforced by platform** — "Two teammates editing the same file leads to overwrites" is best practice, not enforcement. Our `.coordination.json` is a genuine value-add.
- **Permissions set at spawn** — all teammates inherit lead's permission mode.
- **Teammate messaging** — direct (one-to-one) and broadcast. Automatic delivery.
- **Worktree isolation is prompt-driven** — tell the lead to use worktrees in the spawn prompt. Not controlled via agent frontmatter (that's a subagent concept).
- **All teammates run same model** — Opus 4.6 required. No per-role model selection yet.
- **Teammates share the lead's session_id** — from the hook system's perspective.

### Platform Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| Teams don't survive session resumption | Can't keep same team across sessions | Sprint state in SMM; recreate team each session |
| One team per session | Can't have sub-teams | Keep team flat; lead coordinates all teammates |
| No nested teams | Teammates can't spawn sub-teammates | Each teammate is a leaf worker |
| Lead is fixed | Can't rotate coach role | Lead is always the main session |
| Teammates don't inherit lead's history | Teammates lack planning context | SubagentStart injects SMM + behavioral guide; task descriptions embed specifics |
| Shutdown can be slow | Session end delayed | Design for graceful degradation |
| No PR/merge workflow | No integration mechanism | Lead manages merges; `/xp-assign` structures the approach |
| Prompt nuggets don't work for teammates | No mid-session signal injection | SubagentStart provides initial context; direct messaging for urgent updates |
| Same model for all teammates | Can't optimize cost with smaller models | Accept until platform adds per-role model selection |

### Platform Gaps (We Fill)

- **No conflict prevention** — platform only warns about same-file edits. Our `.coordination.json` blocks them deterministically.
- **No sprint/backlog concept** — platform has tasks but no multi-session persistence. Our SMM handles this.
- **No PR/merge workflow** — entirely on us to design the review-and-merge cycle.

---

## Prerequisites

This design builds on:
- **1.0 shipped and dogfooded** — friction points identified through retrospectives
- **Backlog & Planning Game (M9)** from ARCHITECTURE.md 2.0 vision
- **Requirements Decomposition (M10)** for automated spec gathering
- **Agent Teams feature stabilized** — currently experimental with known limitations

---

## Relationship to Existing 2.0 Vision

The 2.0 vision in ARCHITECTURE.md outlines M9 (Backlog & Planning Game), M10 (Requirements Decomposition), and M11 (Autonomous Decision-Making). This design refines M9 and M10 with concrete Agent Teams integration:

| ARCHITECTURE.md Vision | This Design |
|---|---|
| `user_story` event type | Stories live in `sprint.md`, not event log. Richer format with acceptance criteria, sizes, dependencies. |
| Planning game at SessionStart | Sprint-scoped planning game driven by `execution_plan.md` |
| Plan reviewer validates against backlog | Unchanged — plan reviewer checks items are right-sized, TDD-ordered. Also recommends execution mode (solo/subagent/team). |
| Burn down rendering | Sprint section in curated SMM with progress summary (reads `sprint.md`) |
| Requirements decomposition subagent | `/xp-product-spec` skill — conversation-driven spec gathering, produces `product_spec.md` |
| Customer confirms priorities once | Product spec captures full vision; sprint planning selects the next slice |

The key addition: **the sprint as a first-class lifecycle** that wraps the existing session lifecycle, with the team lead as the persistent orchestrator across ephemeral Agent Team instances.

---

## v1 Limitations That Affect v2

| Limitation | Impact on Teams | Required Change |
|---|---|---|
| **Prompt nuggets don't work for teammates** | Teammates can't see mid-session signals from other agents | Direct messaging or broadcast for urgent items; accept async for rest |
| **Stop gates don't fire for teammates** | No simplify, quality review, or TDD enforcement at stop time | Simplify/quality/security: commit-gated via PreToolUse:Bash (fires for all agents). TDD: TeammateIdle + TaskCompleted. |
| **Behavioral guide is solo-focused** | Process section tells teammates to run kickoff, plan mode, etc. | Detect teammate in SubagentStart, inject trimmed guide |
| **No sprint persistence** | Can't persist sprint state across sessions | Add `sprint.md`, `product_spec.md`, and `sprint` boundary events |
| **Compaction doesn't know about sprint events** | Sprint boundary events might get compacted | Add retention rules for active `sprint` events |
| **Housekeeping doesn't curate Sprint pillar** | No sprint progress in curated SMM | Add Sprint section to housekeeping (reads `sprint.md`) |
| **Kickoff doesn't check sprint status** | Lead needs to know if mid-sprint or starting new | Add sprint status check to kickoff |
| **Path normalization uses absolute paths** | `.coordination.json` fails across worktrees | Normalize to repo-relative paths |
| **context:fork doesn't reliably delegate** | Plan reviewer and retro subagents sometimes run inline | v1 issue, still present — fallback instructions mitigate |

---

## Worktree Subagent Findings (M1/M2)

### Empirical Testing (2026-04-10)

We tested native Agent Teams with parallel sprint stories. The key finding: **the commit restriction makes the lead a serial bottleneck.** In Agent Teams, only the lead can commit. Teammates implement code but depend on the lead to stage, review, and commit their work. This serializes what should be parallel work and creates context-window pressure as the lead juggles multiple teammates' output.

The review cycle (`/simplify` -> `/xp-quality-review` -> `/xp-security-triage`) compounds this. Each teammate's commit requires three review steps, all gated through the lead. With 3-4 teammates producing commits, the lead spends most of its time in review cycles rather than coordinating.

### Why Worktree Subagents Are Better for Sprint Work

Worktree subagents solve the bottleneck by giving each teammate full autonomy:

| Capability | Agent Teams | Worktree Subagents |
|---|---|---|
| **Commits** | Lead only (serial bottleneck) | Each teammate commits independently |
| **Review cycle** | Lead runs reviews for each teammate's changes | Each teammate runs its own review cycle |
| **Git isolation** | Shared checkout or prompt-driven worktrees | Automatic worktree per teammate (`isolation: worktree`) |
| **TDD** | PreToolUse hooks fire, but commit gate is lead-only | Full TDD cycle including commit gate per teammate |
| **Merge** | N/A (shared branch) | Lead merges branches after completion |
| **Context pressure** | Lead context fills with teammate output | Each teammate has its own context window |

The `xp-teammate` agent definition (`plugins/xp-agents/agents/xp-teammate.md`) provides the behavioral contract: strict TDD, review cycle before every commit, stay within assigned file domain, record decisions and concerns to the SMM.

### Two-Mode Model

The `/xp-assign` skill selects the execution mode after analyzing sprint stories:

**Solo** (sequential) — the lead executes stories directly. Selected when:
- Stories have dependency chains between them
- File domains overlap between stories
- All stories are size S (coordination overhead not worth it)
- File domains are missing from story definitions

**Worktree Subagents** (parallel) — each story gets an `xp-teammate` agent. Selected when:
- 2+ stories have no dependencies between them
- Stories are size M or L
- Stories have non-overlapping file domains

The mode decision is presented to the user for confirmation before spawning. `/xp-assign` auto-runs after planning completes.

### Platform Constraints Discovered

Two platform issues were discovered during M1/M2 implementation:

1. **`isolation: worktree` silently ignored with `team_name`** ([anthropics/claude-code#33045](https://github.com/anthropics/claude-code/issues/33045)) — when an agent is spawned with both `isolation: worktree` and a `team_name`, the worktree isolation is silently dropped. Workaround: use `isolation: worktree` without `team_name`, treating teammates as independent subagents rather than Agent Team members.

2. **WorktreeCreate stdout must be clean** ([anthropics/claude-code#27467](https://github.com/anthropics/claude-code/issues/27467)) — any stdout from `WorktreeCreate` hooks is interpreted as the worktree path. Hook scripts must avoid writing to stdout during worktree creation, or the worktree setup fails silently.

### Recommendation

**Use worktree subagents for sprint-driven parallel execution.** They provide full teammate autonomy (TDD, review, commits) without the serial bottleneck of Agent Teams' lead-only commit model.

**Use native Agent Teams for ad-hoc collaborative work** outside the sprint flow — exploratory tasks, shared investigation, or work that benefits from the built-in task list and messaging primitives without needing independent commits.

The original Agent Teams design in this document remains valid for its coordination patterns (SMM sharing, conflict detection, behavioral guide injection). The worktree subagent model reuses all of these patterns — it changes the execution primitive (subagent with worktree isolation instead of Agent Team teammate), not the coordination architecture.

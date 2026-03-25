# Agent Teams Design — Sprint-Driven XP

## Overview

This document maps XP sprint practices to Claude Code Agent Teams. The core insight: Agent Teams provide the parallel execution engine, xp-agents provides the persistence, ceremony, and coordination layer. Neither alone delivers sprint-driven development — together they do.

Agent Teams are experimental (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), with known limitations that shape this design. The most significant: teams don't survive session resumption. The sprint state must live outside the team.

---

## Vocabulary

| Term | Definition |
|---|---|
| **Session** | A single Claude Code invocation. Has a start (SessionStart hook), work period, and end (SessionEnd hook). Ephemeral — context window, Agent Teams, and all runtime state die at session end. The atomic unit of compute. |
| **Iteration** | One complete plan/work/accept cycle. Maps to a single session — a session naturally has this shape: kickoff → plan → work → accept → stop. Not split across sessions. |
| **Sprint** | A unit of deliverable work toward a goal. One or more iterations. Persists across sessions via SMM. Has a goal, backlog items, and a definition of done. Ends when the goal is met or remaining work is deferred. |
| **Backlog item** | A unit of work within a sprint. Has acceptance criteria (including e2e test definitions), dependencies, size estimate, file domain, and status. Created during planning, executed during work, verified during accept. |
| **Acceptance criteria** | Concrete, testable conditions that prove a backlog item or sprint goal is done. Defined at plan time, verified at accept time. Includes e2e test definitions. |
| **File domain** | The set of files/directories a backlog item owns. Used to verify non-overlapping task assignments and enforce coordination boundaries. |

---

## Iteration Lifecycle (Single Session)

An iteration is one complete cycle within a session. Every session follows this structure:

### Solo Iteration

```
1. Kickoff
   → Retro (what happened last session)
   → Goals (what are we doing this session)
   → Housekeeping (curate SMM)

2. Plan
   → Decompose work into steps
   → Plan review:
     - Quality: right-sized? TDD-ordered? Dependencies correct?
     - Acceptance criteria: what e2e tests prove this works?
     - Execution mode: solo, subagents, or Agent Team?
     - Parallelization: which items can run concurrently? Non-overlapping domains?

3. Work (repeat per unit of work)
   → Red: write failing test
   → Green: make it pass
   → Simplify: refactor (three review subagents run)
   → Quality review: courage + drift + debt (triggered when simplify subagents complete)
   → Security triage → commit

4. Accept
   → Run e2e tests defined in plan
   → Verify acceptance criteria

5. Stop
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
     - Acceptance criteria per backlog item AND for the integrated result

3. Spawn
   → Lead runs /xp-spawn-team
   → Skill reads plan, structures tasks with domains and criteria
   → Lead creates Agent Team with tasks

4. Work (each teammate, in parallel)
   → Red → green → simplify → quality review → security triage → commit
   → Each teammate works within their assigned file domain
   → .coordination.json enforces domain boundaries

5. Accept
   → Lead waits for all teammates to complete
   → If worktrees: PR review → merge for each teammate's work
   → If shared checkout: review commits
   → Run e2e tests against the integrated result
   → Verify acceptance criteria from the plan

6. Stop
   → Session end
```

### Key Design Points

- **Simplify IS the refactor step** in red/green/refactor. It's not a separate ceremony — it's the third beat of TDD.
- **Quality review triggers when simplify subagents complete** (detected via SubagentStop), not at Stop time. It checks courage (did you fix what simplify found?), drift (are you following SMM constraints?), and debt (are you creating new debt?).
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
- "This decomposes into 3 independent modules with no file overlap — consider `/xp-spawn-team`" → teams

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
| **Sprint entity** | Groups backlog items with a goal, tracks progress across sessions |
| **Backlog items** | Event type with acceptance criteria, dependencies, status |
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
- **Mid-sprint**: spawn teammates via `/xp-spawn-team`, handle questions, unblock dependencies, review PRs, merge
- **Sprint end**: review, retrospective, prepare next sprint
- **Interrupt-driven**: responds to teammate messages, `TeammateIdle` events, `TaskCompleted` events, customer questions

The lead is the customer proxy. When a teammate raises a blocking question:
1. If answerable from sprint specs/SMM — lead answers directly
2. If genuinely new — lead escalates to the actual customer via `AskUserQuestion`

### Teammates = Developers

Teammates **write code**:

- Claim an unblocked backlog item from the task list
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

The most effective pattern is: plan first (plan mode), review the plan (`/xp-review-plan`), then hand the plan to a team for parallel execution (`/xp-spawn-team`). Don't jump straight into spawning teammates. Get the architecture and task breakdown right first.

### Feed Context Into Task Descriptions

Teammates don't inherit the lead's conversation history. Whatever context the lead built up before starting the team, teammates won't have it. Our SubagentStart hook injects the curated SMM + behavioral guide automatically, but task descriptions should also embed specific details — file paths, API contracts, acceptance criteria.

### Keep the Lead Coordinating, Not Implementing

The lead should delegate, not implement. Use delegate mode if needed. The lead's job is: spawn team, monitor progress, review work, handle questions, merge changes.

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

The `/xp-spawn-team` skill should choose based on the plan:

- **No worktrees** (default): clean domain separation, teammates work on completely different files. `.coordination.json` prevents overlap. Best for most cases, especially when the planning game produces non-overlapping task assignments.
- **Worktrees**: when tasks involve git-heavy workflows (branching, PRs), when the lead wants formal PR review, or when git operation isolation is important (larger teams where `git add .` risk is higher).

### Path Normalization for Worktree Safety

If worktrees are used, `.coordination.json` needs repo-relative paths instead of absolute paths for cross-worktree conflict detection. Current `normalize_path()` uses `os.path.realpath()` which produces absolute paths — the same logical file has different absolute paths in different worktrees:

- Main checkout: `/Users/paul/project/src/app.py`
- Worktree A: `/Users/paul/project/.claude/worktrees/teammate-1/src/app.py`

Fix: normalize to repo-relative paths using `git rev-parse --show-toplevel` to strip the worktree prefix. This makes coordination work across worktrees while remaining backward-compatible for solo mode.

---

## Team Launch Mechanism

### `/xp-spawn-team` Skill

A lead-invoked skill that reads the current plan and creates an Agent Team. The plan reviewer recommends it when the plan has genuinely parallelizable, cleanly separable work.

**Flow:**
1. Plan reviewer reviews the plan, identifies parallel groups with non-overlapping file domains
2. Plan reviewer tells the lead: "This plan has 3 independent modules — run `/xp-spawn-team`"
3. Lead runs `/xp-spawn-team`
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

## Sprint Lifecycle

### Sprint = N Sessions

A sprint is a unit of deliverable work. A session is a unit of compute time. Most sprints span multiple sessions. The sprint persists in the SMM; the Agent Team is recreated each session.

```
Sprint Start (Session K)
│
├─ 1. Retrospective (session retro from K-1, sprint retro if sprint boundary)
├─ 2. Sprint Goal — "what are we delivering?"
├─ 3. Spec Gathering — questions, constraints, acceptance criteria
├─ 4. Planning Game — decompose into backlog items with dependencies
├─ 5. Backlog items written to SMM
│
Sprint Execution (Sessions K through K+N)
│
├─ 6. Lead reads sprint backlog from SMM
├─ 7. Plan reviewer recommends execution mode (solo/subagent/team)
├─ 8. If team: lead runs /xp-spawn-team, creates team with tasks
├─ 9. Teammates self-claim unblocked items, execute
├─ 10. Lead reviews work, merges, unblocks dependent items
├─ 11. Session ends — sprint state persists in SMM
├─ 12. Next session: recreate team, continue from remaining backlog
│
Sprint End (Session K+N, all items done or deferred)
│
├─ 13. Sprint Review — what shipped vs what was planned
├─ 14. Sprint Retrospective — patterns across the sprint, broader than session retro
├─ 15. Prepare Next Sprint — carry forward, update backlog
```

### Session Lifecycle Within a Sprint

```
Session start
  → SessionStart hook: init SMM, write .needs-kickoff
  → retrospective.py: prepare retro data

/xp-kickoff (lead runs this)
  → Session retro (what happened since last session)
  → Sprint status check:
      If no active sprint → start new sprint (goal → specs → planning game)
      If mid-sprint → read remaining backlog, show progress
  → Housekeeping (curate SMM)

Plan review
  → Lead creates plan for next chunk of work
  → Plan reviewer reviews, recommends execution mode
  → If team recommended → lead runs /xp-spawn-team

Team execution (if applicable)
  → Lead creates team with structured tasks from /xp-spawn-team output
  → SubagentStart hook injects SMM + behavioral guide to each teammate
  → All existing hooks enforce quality on teammate work
  → Teammates work, commit, create PRs (worktree) or commit directly (shared checkout)
  → Lead reviews, merges, handles questions
  → TaskCompleted hook updates backlog_item status in SMM

Session end
  → session_end.py captures sprint progress
  → Sprint state persists in SMM for next session
```

---

## XP Practices Mapped to Agent Teams

### Planning Game

| XP Concept | Agent Teams Mechanism |
|---|---|
| Customer sets priorities | Lead collects sprint goal, gathers specs via `AskUserQuestion` |
| Stories decomposed into tasks | Planning game produces `backlog_item` events with acceptance criteria |
| Estimates | Backlog items sized during planning (small/medium/large) |
| Dependencies identified | `backlog_item.dependencies` field, maps to Agent Teams task dependencies |
| Developer picks next task | Teammate self-claims from shared task list |

The planning game is a lead-driven ceremony. The lead:
1. Takes the sprint goal
2. Gathers specs (questions to customer, reads existing code/docs)
3. Decomposes into backlog items with acceptance criteria and dependencies
4. Writes items to SMM as `backlog_item` events
5. Plan reviewer validates: right-sized? TDD-ordered? Dependencies correct? Parallelizable?

### Small Releases

| XP Concept | Agent Teams Mechanism |
|---|---|
| Release early and often | Teammates make small, frequent commits |
| Integration | Worktree mode: per-item PRs. Shared checkout: direct commits to branch |
| Working software | Each merged PR / committed item is a working increment |

Merge strategy: **per-item, not per-sprint**. Each completed backlog item produces a deliverable. Lead reviews and merges. This:
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

The SMM is the mechanism for collective ownership. Every teammate gets the curated SMM + behavioral guide at spawn via SubagentStart. **Limitation:** Prompt nuggets don't work for teammates (UserPromptSubmit doesn't fire). Mid-session discoveries propagate via direct messaging or the shared event log.

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

### Retrospective

| XP Concept | Agent Teams Mechanism |
|---|---|
| Session retro | Keep/Fix/Try from the previous session (existing) |
| Sprint retro | Broader analysis across all sessions in the sprint |
| Velocity tracking | Items completed vs planned, carry-over rate |
| Process improvement | Try items become behavioral experiments for next sprint |

Two levels of retrospective:
- **Session retro** (existing): tactical, what happened since last session
- **Sprint retro** (new): strategic, patterns across the sprint. Did we deliver the sprint goal? What slowed us down? Were estimates accurate? Did the planning game produce right-sized items?

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

Marks sprint boundaries. Written by lead at sprint start and end.

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
  "content": "Sprint complete: 8/10 items delivered",
  "metadata": {
    "sprint_id": "sprint-001",
    "action": "end",
    "items_planned": 10,
    "items_delivered": 8,
    "items_carried": 2
  }
}
```

### `backlog_item`

A unit of work in the sprint backlog. Written by lead during planning game.

```json
{
  "type": "backlog_item",
  "content": "Implement JWT authentication middleware",
  "metadata": {
    "sprint_id": "sprint-001",
    "item_id": "item-001",
    "acceptance_criteria": [
      "JWT tokens validated on protected routes",
      "Invalid tokens return 401",
      "Token refresh endpoint works",
      "Tests cover all three scenarios"
    ],
    "dependencies": [],
    "size": "medium",
    "status": "ready",
    "file_domain": ["src/middleware/auth/", "tests/middleware/auth/"]
  }
}
```

The `file_domain` field is new — it declares which files/directories a backlog item owns. Used by `/xp-spawn-team` to verify non-overlapping assignments and by `.coordination.json` to enforce domain boundaries.

### Agent-Driven Goal Completion

In 1.0, goal completion flows through the user — housekeeping asks "are any of these done?" For Agent Teams, agents need to close goals and backlog items autonomously:

- **Backlog items** have acceptance criteria from the planning game. When a teammate meets all criteria, it records a resolution event with `metadata.resolves` pointing to the backlog item. The `TaskCompleted` hook verifies criteria before allowing completion.
- **Sprint goals** are resolved by the lead when all backlog items are done (or remaining items are deferred). The lead writes the `sprint` end event.
- **Session goals** (from `/xp-goal-collection`) are resolved by agents mid-session when the work ships.

Status lifecycle: `ready` → `in-progress` → `done` | `deferred`

Status updates are new events with `metadata.resolves` pointing to the original:

```json
{
  "type": "backlog_item",
  "content": "Completed: JWT authentication middleware",
  "metadata": {
    "item_id": "item-001",
    "status": "done",
    "resolves": ["<original-event-id>"]
  }
}
```

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
- PreToolUse (Write/Edit/Bash) — conflict detection, TDD order, security triage gate
- PostToolUse (Write/Edit/Bash) — status tracking, lint, commit parsing, simplify nudge
- SubagentStart — SMM + behavioral guide injection (teammates appear here with their agent_type)
- SubagentStop — completion recording

**Hooks that DON'T fire for teammates (lead-only):**
- Stop — simplify gate, quality review gate, TDD stop gate don't apply to teammates
- SessionStart — no kickoff marker, no retro prep for teammates
- SessionEnd — no session_end event for teammates
- UserPromptSubmit — no customer_input logging, no kickoff gate, no prompt nuggets

**New hooks needed for teammates:**
- TeammateIdle — equivalent of Stop gates (TDD, simplify enforcement)
- TaskCompleted — verify acceptance criteria before marking done

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

### Stop Gate Equivalents for Teammates

Stop doesn't fire for teammates. We need equivalent enforcement via TeammateIdle and TaskCompleted:

| Gate | Teammate behavior | Rationale |
|---|---|---|
| TDD (tests pass) | **Enforce** via TeammateIdle + TaskCompleted | Non-negotiable — broken tests block everyone |
| Simplify | **Enforce** via TeammateIdle | Teammates should clean up their own code |
| Quality review | **Skip** — lead reviews instead | Lead has cross-cutting perspective. Teammate-level review doubles cost. |
| Security triage | **Enforce** via existing PreToolUse:Bash | Already works — teammate must triage before committing |

TeammateIdle and TaskCompleted use exit 2 + stderr to block (not `decision: "block"` JSON). They do NOT support matchers — handlers must do their own filtering.

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

1. **Planning** — `/xp-spawn-team` decomposes work into non-overlapping file domains. Each task gets a `file_domain` declaring which files/directories it owns. This is the primary mechanism — if domains are clean, conflicts don't happen.

2. **Coordination** — `.coordination.json` blocks overlapping writes at PreToolUse time. Deterministic, real-time, already works for teammates. This is the safety net that catches domain violations.

3. **Isolation** (optional) — Worktree isolation prevents git operation interference. Prompt-driven, not enforced by the plugin. A nice-to-have for git hygiene, not required for conflict prevention.

### Path Normalization

Current `normalize_path()` uses absolute paths (`os.path.realpath()`). This works when all teammates share the same checkout. If worktrees are used, the same logical file has different absolute paths per worktree — coordination.json wouldn't detect the conflict.

**Fix needed for worktree support:** normalize to repo-relative paths using `git rev-parse --show-toplevel` to strip the worktree prefix. This makes coordination work across worktrees while remaining backward-compatible for solo and shared-checkout modes.

---

## Integration Points

### Existing Hooks (Work for Teammates)

- **PreToolUse/PostToolUse** — conflict detection, TDD order, lint, security triage, commit parsing
- **SubagentStart** — injects curated SMM + behavioral guide at teammate spawn
- **SubagentStop** — records teammate completion

### Existing Hooks (Lead-Only, No Changes Needed)

- **SessionStart/SessionEnd/UserPromptSubmit/Stop** — don't fire for teammates, no guards needed

### New Hooks for Agent Teams

| Hook Event | Script | Purpose |
|---|---|---|
| `TaskCompleted` | `task_completed.py` | TDD gate + update `backlog_item` status in SMM |
| `TeammateIdle` | `teammate_idle.py` | TDD gate + simplify enforcement + check remaining work |

### Lead-Specific Skills

| Skill | Purpose |
|---|---|
| `/xp-sprint-start` | Sprint goal, spec gathering, planning game, backlog creation |
| `/xp-spawn-team` | Read plan, analyze file domains, structure tasks, instruct lead to create team |
| `/xp-sprint-review` | Compare delivered items against sprint goal, summarize |
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
- **SKIP:** EnterPlanMode (built-in plan approval handles this), /xp-quality-review (lead reviews instead)
- **KEEP:** /simplify after commits, /xp-security-triage before commits, TDD discipline, concern recording

---

## SMM Changes

### Sprint-Aware Curated View

The curated `SHARED_MENTAL_MODEL.md` gains a sprint section:

```markdown
# Shared Mental Model

## Sprint
- Goal: Build user management REST API with auth
- Progress: 5/10 items done, 2 in-progress, 3 ready
- Blockers: Token refresh depends on auth middleware (in-progress)

## Intent
...

## Constraints
...

## Risks
...

## Wisdom
...
```

### Sprint State Persistence

Sprint state lives in the SMM event log as `sprint` and `backlog_item` events. This means:
- Survives session boundaries (Agent Teams don't)
- Visible to all agents via SubagentStart context injection
- Curated by housekeeping like any other event type
- Compacted carefully — active sprint events are never compacted

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
| No PR/merge workflow | No integration mechanism | Lead manages merges; `/xp-spawn-team` structures the approach |
| Prompt nuggets don't work for teammates | No mid-session signal injection | SubagentStart provides initial context; direct messaging for urgent updates |
| Same model for all teammates | Can't optimize cost with smaller models | Accept until platform adds per-role model selection |

### Platform Gaps (We Fill)

- **No conflict prevention** — platform only warns about same-file edits. Our `.coordination.json` blocks them deterministically.
- **No sprint/backlog concept** — platform has tasks but no multi-session persistence. Our SMM handles this.
- **No PR/merge workflow** — entirely on us to design the review-and-merge cycle.

---

## Open Questions

### Resolved

| # | Question | Answer |
|---|---|---|
| 1 | Stop event scope | Stop does NOT fire for teammates. Need TeammateIdle equivalents. |
| 2 | SessionStart scope | Does NOT fire for teammates. No guards needed. |
| 3 | UserPromptSubmit scope | Does NOT fire for teammates, even when messaging them directly. |
| 4 | Plugin hooks on teammates | YES — PreToolUse and PostToolUse fire for teammates. |
| 5 | Teammate agent_type | Custom teammate name (e.g., "agent-updater"). Appears in SubagentStart/SubagentStop. |
| 6 | Teammate skill invocation | Skills load for teammates (docs confirmed). |
| 7 | Team size heuristics | 3-5 teammates, 5-6 tasks each. Token cost scales linearly (~3-4x for 3 teammates). |
| 10 | Integration order | Per-item merges. Lead reviews and merges. Worktrees produce PRs; shared checkout uses direct commits. |
| 11 | Teammate specialization | Domain-based, not role-based. Frontend agent, backend agent, etc. Clean file domain separation. |
| 16 | Worktree isolation | Available via prompt to lead, not via agent frontmatter. Prompt-driven, not enforced. |

### Still Open (Resolve During Implementation)

8. **Sprint length.** Explicit (customer sets it) or emergent (sprint ends when backlog is done)?

9. **Failed items.** Deferred to next sprint? Reassigned? Lead takes over?

12. **Sprint review format.** Run acceptance criteria? Show test results? Generate summary?

13. **Lead context management.** Delegate PR reviews to subagent? (Recommendation: yes — preserves lead's context window for coordination.)

14. **Worktree merge conflicts.** Lead resolves, or retry mechanism?

15. **Customer availability.** Queue questions with assumptions, or block?

17. **Simplify threshold on teammates.** Same as main agent (3+ code files) or lower for smaller work items?

18. **Cross-teammate communication.** Prompt nuggets don't work for teammates. Direct messaging for urgent discoveries? Broadcast for breaking changes? Accept async delay for most cases?

---

## Underspecified Areas (Needs Design)

### PR and Merge Workflow

The platform has no PR workflow. We need to design the full cycle for worktree mode:

1. **Teammate completes work** — commits in worktree, creates PR via `gh pr create`
2. **Lead discovers PR is ready** — how? Options:
   - Teammate sends message to lead: "PR #N ready for review"
   - `TaskCompleted` hook checks for new PRs
   - Lead polls periodically
3. **Lead reviews PR** — reads diff, checks against acceptance criteria and SMM constraints
   - Could delegate to a review subagent to preserve lead's context
   - Uses `gh pr review` to approve/request changes
4. **Merge** — lead merges via `gh pr merge`
5. **Other teammates rebase** — after merge, teammates in worktrees may need to pull. How?
   - Lead broadcasts "main updated, rebase your worktree"
   - Teammates auto-rebase after each task completion
   - Accept that short-lived worktrees rarely conflict

For shared-checkout mode (no worktrees), the flow is simpler: teammates commit directly, lead reviews commits post-hoc or via TaskCompleted hook.

**Key question:** Should the lead do PR reviews inline (context cost) or delegate to a review subagent (coordination cost)?

### Bootstrap Flow (First Session with Agent Teams)

What happens the very first time someone uses xp-agents with Agent Teams?

1. `/xp-kickoff` runs — seed SMM, first retro (nothing to analyze), goals
2. User describes what they want to build
3. Lead runs sprint start — goal setting, spec gathering, planning game
4. Lead decomposes into backlog items
5. Plan reviewer reviews plan, recommends team if parallelizable
6. Lead runs `/xp-spawn-team`, creates team with tasks
7. Teammates execute

This is the same as the sprint start flow, but without any prior sprint history. The seed SMM provides default constraints and wisdom. The planning game produces the first backlog.

**Key question:** Does the lead need a special "first sprint" skill, or does `/xp-sprint-start` handle this naturally?

### Cross-Teammate Communication

The SMM is the broadcast channel, but prompt nuggets don't fire for teammates (UserPromptSubmit is lead-only). For urgent cross-cutting discoveries:

- **Scenario:** Teammate A discovers a breaking API change — other teammates need to know NOW
- **Current mechanism:** A records a `concern` event → but no prompt nugget delivery to teammates
- **Gap:** teammates only see SMM state from SubagentStart (spawn time), not mid-session updates

Options:
- **Direct messaging:** teammate sends message to affected teammates (platform supports this)
- **Broadcast:** send to all teammates (platform supports, but expensive)
- **Accept the async delay:** most discoveries aren't urgent enough to warrant interruption
- **Hybrid:** concerns with `severity: high` trigger a broadcast via a PostToolUse hook that detects high-severity concern writes and instructs the lead to broadcast

### Velocity and Estimation

Sprint 1 has no velocity history. The planning game produces backlog items with size estimates (small/medium/large) but no data to calibrate against.

- **Sprint 1:** estimate-free. Plan what feels right, measure what actually gets done.
- **Sprint 2+:** sprint retro reports items_planned vs items_delivered. Lead uses this to size the next sprint.
- **Long-term:** velocity stabilizes. Lead can predict "we deliver ~8 medium items per sprint."

Mechanism: the `sprint` end event already captures `items_planned`, `items_delivered`, `items_carried`. The sprint retro skill reads these for trend analysis. No new infrastructure needed — just the skills to compute and present the data.

### Lead Context Management

The lead coordinates everything: spawning teammates, reviewing PRs, handling messages, unblocking dependencies. Its context window fills fast.

Options:
- **Delegate PR reviews to a subagent** — lead spawns a review subagent for each PR, gets back a summary. Keeps detailed diffs out of lead's context.
- **Periodic compaction** — lead's context compacts naturally. PostCompact reinjects SMM + sprint status.
- **Lean on the task list** — task states are on disk, not in context. Lead reads them when needed.
- **Limit broadcast messages** — teammates message lead only for blockers, not status updates. Status is in the SMM.

Recommendation: delegate PR reviews to a subagent. The lead should orchestrate, not deep-read code.

### Backlog Item ↔ Task Mapping

Two systems track work:
- **SMM event log** — `backlog_item` events with acceptance criteria, dependencies, status. Persists across sessions.
- **Platform task list** — `~/.claude/tasks/{team-name}/`. Ephemeral, per-team.

The lead must translate: read backlog items from SMM, create platform tasks for the current team. When tasks complete, update backlog item status in SMM.

**Key question:** Is this a skill (`/xp-spawn-team` reads backlog, creates tasks)? Or a hook (`TaskCompleted` updates backlog items)? Likely both — skill creates tasks at spawn, hook updates backlog at completion.

### Compaction Rules for Sprint/Backlog Events

Active sprint events must survive compaction. Rules needed:
- `sprint` with `action: "start"` — retain while sprint is active
- `sprint` with `action: "end"` — retain for 1 sprint (like session_end for aging)
- `backlog_item` with `status: "ready"` or `status: "in-progress"` — retain (active work)
- `backlog_item` with `status: "done"` or `status: "deferred"` — compact after sprint ends

### Housekeeping Sprint Curation

Housekeeping needs to curate the Sprint pillar:
- Read active `sprint` and `backlog_item` events
- Compute progress: N done, N in-progress, N ready, N blocked
- Identify blockers (items with unmet dependencies)
- Write Sprint section to curated SMM

### Sprint Retro vs Session Retro

Two retro levels:
- **Session retro** (existing) — tactical, what happened since last session
- **Sprint retro** (new) — strategic, patterns across all sessions in the sprint

Sprint retro data:
- All session retros from the sprint (trend analysis)
- Sprint velocity: items_planned vs items_delivered vs items_carried
- Backlog item completion times
- Which items were reassigned or failed

**Key question:** Is this a separate skill (`/xp-sprint-retro`) or an extension of the existing retro that detects sprint boundaries?

### Lead Kickoff Flow Changes

Current kickoff: retro → questions → goals → housekeeping

For teams, kickoff needs to add sprint awareness:
1. Session retro (existing)
2. Question triage (existing)
3. **Sprint status check** (new):
   - If no active sprint → start new sprint (goal → specs → planning game → backlog)
   - If mid-sprint → show remaining backlog, progress summary
4. Goal collection (existing, but may be replaced by sprint goals)
5. Housekeeping with Sprint pillar (modified)
6. **Plan review → execution mode recommendation** (new) — plan reviewer recommends solo/subagent/team

**Key question:** Modify existing `/xp-kickoff` to be sprint-aware, or create a separate `/xp-sprint-kickoff`?

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
| `backlog_item` event type | Defined with full schema, lifecycle, acceptance criteria, and `file_domain` |
| Planning game at SessionStart | Sprint-scoped planning game with spec gathering phase |
| Plan reviewer validates against backlog | Unchanged — plan reviewer checks items are right-sized, TDD-ordered. Also recommends execution mode (solo/subagent/team). |
| Burn down rendering | Sprint section in curated SMM with progress summary |
| Requirements decomposition subagent | Lead-driven spec gathering, can delegate to subagent |
| Customer confirms priorities once | Sprint goal set once, lead handles tactical decisions |

The key addition: **the sprint as a first-class lifecycle** that wraps the existing session lifecycle, with the team lead as the persistent orchestrator across ephemeral Agent Team instances.

---

## v1 Limitations That Affect v2

| Limitation | Impact on Teams | Required Change |
|---|---|---|
| **Prompt nuggets don't work for teammates** | Teammates can't see mid-session signals from other agents | Direct messaging or broadcast for urgent items; accept async for rest |
| **Stop gates don't fire for teammates** | No simplify, quality review, or TDD enforcement at stop time | TeammateIdle and TaskCompleted handlers |
| **Behavioral guide is solo-focused** | Process section tells teammates to run kickoff, plan mode, etc. | Detect teammate in SubagentStart, inject trimmed guide |
| **No sprint/backlog event types** | Can't persist sprint state across sessions | Add `sprint` and `backlog_item` to event schema |
| **Compaction doesn't know about sprint events** | Active sprint events might get compacted | Add retention rules for active sprint/backlog_item events |
| **Housekeeping doesn't curate Sprint pillar** | No sprint progress in curated SMM | Add Sprint section to housekeeping |
| **Kickoff doesn't check sprint status** | Lead needs to know if mid-sprint or starting new | Add sprint status check to kickoff |
| **Path normalization uses absolute paths** | `.coordination.json` fails across worktrees | Normalize to repo-relative paths |
| **context:fork doesn't reliably delegate** | Plan reviewer and retro subagents sometimes run inline | v1 issue, still present — fallback instructions mitigate |

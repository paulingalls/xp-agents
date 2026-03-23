# Agent Teams Design — Sprint-Driven XP

## Overview

This document maps XP sprint practices to Claude Code Agent Teams. The core insight: Agent Teams provide the parallel execution engine, xp-agents provides the persistence, ceremony, and coordination layer. Neither alone delivers sprint-driven development — together they do.

Agent Teams are experimental (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), with known limitations that shape this design. The most significant: teams don't survive session resumption. The sprint state must live outside the team.

---

## Architecture: Two Layers

### Agent Teams Layer (Claude Code platform)

Provides the execution primitives:

| Component | What it does |
|---|---|
| **Team lead** | Main session. Creates team, spawns teammates, coordinates |
| **Teammates** | Subagent-like instances within the lead's session, own context windows (worktree isolation unconfirmed) |
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

## Role Separation

### Team Lead = XP Coach + Customer Proxy

The lead **does not write code**. It orchestrates:

- **Sprint start**: goal setting, spec gathering, planning game
- **Mid-sprint**: spawn teammates, create tasks from backlog, handle questions, unblock dependencies, review PRs, merge
- **Sprint end**: review, retrospective, prepare next sprint
- **Interrupt-driven**: responds to teammate messages, `TeammateIdle` events, `TaskCompleted` events, customer questions

The lead is the customer proxy. When a teammate raises a blocking question:
1. If answerable from sprint specs/SMM — lead answers directly
2. If genuinely new — lead escalates to the actual customer via `AskUserQuestion`

### Teammates = Developers

Teammates **write code**:

- Claim an unblocked backlog item from the task list
- Execute with full xp-agents hook enforcement (TDD, lint, conflicts, security)
- Work in isolated worktrees (unconfirmed — may need to request via spawn prompt)
- Small, frequent commits
- Create PR when item is complete
- Signal done — lead reviews PR and merges
- Pick up next unblocked item

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
├─ 7. Lead spawns Agent Team, creates tasks from unfinished backlog items
├─ 8. Teammates self-claim unblocked items, execute
├─ 9. Lead reviews PRs, merges, unblocks dependent items
├─ 10. Session ends — sprint state persists in SMM
├─ 11. Next session: recreate team, continue from remaining backlog
│
Sprint End (Session K+N, all items done or deferred)
│
├─ 12. Sprint Review — what shipped vs what was planned
├─ 13. Sprint Retrospective — patterns across the sprint, broader than session retro
├─ 14. Prepare Next Sprint — carry forward, update backlog
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

Lead spawns Agent Team
  → Creates tasks from unblocked backlog items
  → Teammates claim and execute
  → SubagentStart hook injects SMM + behavioral guide to each teammate
  → All existing hooks enforce quality on teammate work

Mid-session
  → Teammates work, commit, create PRs
  → Lead reviews PRs, merges
  → TaskCompleted hook updates backlog_item status in SMM
  → Dependencies auto-unblock, teammates self-claim next items
  → Lead handles questions, re-prioritizes if customer redirects

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
5. Plan reviewer validates: right-sized? TDD-ordered? Dependencies correct?

### Small Releases

| XP Concept | Agent Teams Mechanism |
|---|---|
| Release early and often | Teammates make small, frequent commits |
| Integration | Teammates create PRs, lead reviews and merges frequently |
| Working software | Each merged PR is a working increment |

Merge strategy: **per-item, not per-sprint**. Each completed backlog item produces a PR. Lead reviews and merges. This:
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

TDD order check (PreToolUse) works for teammates. TDD stop gate (Stop) confirmed NOT firing for teammates — `teammate_idle.py` and `task_completed.py` handlers provide equivalent enforcement.

### Pair Programming → PR Review

| XP Concept | Agent Teams Mechanism |
|---|---|
| Two sets of eyes | Teammate implements, lead reviews PR |
| Knowledge sharing | Decisions and discoveries broadcast via SMM |
| Quality gate | Lead can reject PR with feedback |

Traditional pair programming doesn't map to Agent Teams (teammates work independently). PR review by the lead is the closest analog. Current design: skip `/xp-quality-review` on teammates — lead reviews PRs instead, avoiding double cost.

### Collective Code Ownership

| XP Concept | Agent Teams Mechanism |
|---|---|
| Anyone can change any code | All teammates share the same codebase (via worktrees) |
| Shared understanding | SMM injected into every teammate via SubagentStart |
| Conflict prevention | `.coordination.json` tracks working_on across teammates |

The SMM is the mechanism for collective ownership. Every teammate gets the curated SMM + behavioral guide at spawn via SubagentStart. **Limitation:** Prompt nuggets don't work for teammates (UserPromptSubmit doesn't fire). Mid-session discoveries must propagate via direct messaging or the shared event log — teammates won't see nuggets.

### Continuous Integration

| XP Concept | Agent Teams Mechanism |
|---|---|
| Integrate frequently | Per-item PR merges |
| Tests run on integration | Lead verifies tests pass before merging |
| Broken build = stop everything | Lead can broadcast to teammates if integration breaks |

### On-Site Customer

| XP Concept | Agent Teams Mechanism |
|---|---|
| Customer available | Human available via `AskUserQuestion` |
| Customer sets priorities | Sprint goal and spec gathering at sprint start |
| Quick answers | Lead as customer proxy for questions answerable from specs |
| Escalation | Lead escalates genuinely new questions to human |

The lead as customer proxy reduces interruptions to the human. The human sets direction at sprint start and handles escalations. The lead handles tactical questions.

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

Velocity tracking feeds back into the planning game. If the team consistently carries over items, the sprint retro should flag: "reduce scope or increase sprint length."

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
    "status": "ready"
  }
}
```

### Agent-Driven Goal Completion

In 1.0, goal completion flows through the user — housekeeping asks "are any of these done?" For Agent Teams, agents need to close goals and backlog items autonomously:

- **Backlog items** have acceptance criteria from the planning game. When a teammate meets all criteria, it records a resolution event with `metadata.resolves` pointing to the backlog item. The `TaskCompleted` hook verifies criteria before allowing completion.
- **Sprint goals** are resolved by the lead when all backlog items are done (or remaining items are deferred). The lead writes the `sprint` end event.
- **Session goals** (from `/xp-goal-collection`) are resolved by agents mid-session when the work ships. The agent writes a `status` event with `metadata.resolves` pointing to the goal event ID.

The behavioral guide should instruct agents to resolve goals when they believe the work is complete. Housekeeping serves as the verification layer — if an agent resolves a goal but the user disagrees, housekeeping surfaces it during the next curation.

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

### Model B Confirmed: Teammates Are Subagents

Empirical testing with probe hooks on every event type confirmed **Model B**. Teammates are treated as subagents within the lead's session, not as independent sessions. Key findings:

| Question | Result |
|---|---|
| Does **Stop** fire for teammates? | **NO.** Stop only fires for the lead (empty agent_id). |
| Does **SessionStart** fire for teammates? | **NO.** Only fires for the lead. |
| Does **SessionEnd** fire for teammates? | **NO.** Only fires for the lead. |
| Does **UserPromptSubmit** fire for teammates? | **NO.** Only fires for lead prompts. Messaging a teammate directly does NOT trigger it. |
| Do **plugin hooks** fire for teammates? | **YES.** PreToolUse and PostToolUse fire for teammates with their agent_id and agent_type. |
| Do teammates get unique **session_ids**? | **NO.** All teammates share the lead's session_id. |
| Does **SubagentStart** fire when teammates spawn? | **YES.** agent_type is the teammate's custom type (e.g., "agent-updater"). |
| Does **SubagentStop** fire when teammates finish? | **YES.** Same agent_type. |
| What does **TeammateIdle** provide? | `teammate_name`, `team_name`, `session_id`, `permission_mode`. No agent_id or agent_type. |
| What does **TaskCompleted** provide? | `task_id`, `task_subject`, `task_description`, `teammate_name`, `team_name`. No agent_id. |

### What This Means

**Hooks that work for teammates unchanged:**
- PreToolUse (Write/Edit/Bash) — conflict detection, TDD order, security triage gate
- PostToolUse (Write/Edit/Bash) — status tracking, lint, commit parsing, simplify nudge
- SubagentStart — SMM + behavioral guide injection (teammates appear here with their agent_type)
- SubagentStop — completion recording

**Hooks that DON'T fire for teammates (lead-only):**
- Stop — our simplify gate, quality review gate, and TDD stop gate don't apply to teammates
- SessionStart — no kickoff marker, no retro prep for teammates
- SessionEnd — no session_end event for teammates
- UserPromptSubmit — no customer_input logging, no kickoff gate, no prompt nuggets for teammates

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
| `pre_tool_write.py` | PreToolUse:Write | ✓ Conflict detection, TDD order, plan review gate |
| `pre_tool_bash.py` | PreToolUse:Bash | ✓ Security triage gate, file-modification heuristic |
| `post_tool_use.py` | PostToolUse:Write | ✓ Status/working_on tracking, conflict detection |
| `lint_check.py` | PostToolUse:Write | ✓ Runs linter on written file |
| `bash_post_tool.py` | PostToolUse:Bash | ✓ Commit parsing, test results, simplify nudge |
| `subagent_start.py` | SubagentStart | ✓ SMM + behavioral guide injection |
| `subagent_stop.py` | SubagentStop | ✓ Completion recording |

### Hooks That DON'T Fire for Teammates (No Changes Needed)

| Hook | Event | Why It's Fine |
|---|---|---|
| `session_start.py` | SessionStart | Teammates don't trigger SessionStart — no kickoff marker conflict |
| `retrospective.py` | SessionStart | Teammates don't trigger SessionStart — no retro prep corruption |
| `session_end.py` | SessionEnd | Teammates don't trigger SessionEnd — no event log pollution |
| `kickoff_gate.py` | UserPromptSubmit | Teammates don't trigger UserPromptSubmit — no blocking |
| `user_prompt_log.py` | UserPromptSubmit | Teammates don't trigger UserPromptSubmit — no false customer_input |
| `prompt_nugget.py` | UserPromptSubmit | Teammates don't get nuggets (lead-only), but they DO get SMM via SubagentStart |

### Gaps: Stop Gates Don't Fire for Teammates

| Hook | Event | Gap | Solution |
|---|---|---|---|
| `simplify_gate.py` | Stop | No simplify enforcement for teammates | TeammateIdle handler |
| `quality_review_gate.py` | Stop | No quality review for teammates | Skip — lead reviews PRs instead |
| `tdd_stop_gate.py` | Stop | Teammates can stop with failing tests | TeammateIdle handler |

#### 2. No Ceremony Guards Needed

Empirical testing confirmed: SessionStart, SessionEnd, UserPromptSubmit, and Stop don't fire for teammates. No `is_teammate()` guards needed on ceremony hooks.

#### 3. Stop Gate Equivalents for TeammateIdle / TaskCompleted

Stop doesn't fire for teammates (Model B confirmed). We need equivalent enforcement via TeammateIdle and TaskCompleted. These use exit 2 + stderr (not `decision: "block"` JSON):

**TeammateIdle handler** — TDD gate equivalent:

```python
# teammate_idle.py (TeammateIdle hook)
# Reuses tdd_stop_gate logic, different output mechanism
result = tdd_stop_gate.run(input_data)
if result:
    print(result, file=sys.stderr)
    sys.exit(2)  # Keeps teammate working with feedback
```

**TaskCompleted handler** — acceptance criteria verification:

```python
# task_completed.py (TaskCompleted hook)
# Verify acceptance criteria, update backlog_item in SMM
task_id = input_data.get("task_id", "")
task_subject = input_data.get("task_subject", "")

# Check TDD
tdd_result = tdd_stop_gate.run(input_data)
if tdd_result:
    print(f"Cannot complete '{task_subject}': {tdd_result}", file=sys.stderr)
    sys.exit(2)  # Task not marked complete

# Update backlog_item status in SMM
# ... write backlog_item event with status: "done"
```

**Design choice for simplify/quality review on teammates:**

| Gate | Teammate behavior | Rationale |
|---|---|---|
| TDD (tests pass) | **Enforce** via TeammateIdle + TaskCompleted | Non-negotiable — broken tests block everyone |
| Simplify | **Enforce** via TeammateIdle | Teammates should clean up their own code before creating a PR. Catches reuse opportunities and dead code within the teammate's own work. |
| Quality review | **Skip** — lead does PR review instead | Lead reviews the PR with full sprint context. Teammate-level quality review would double the cost without adding the cross-cutting perspective the lead has. |
| Security triage | **Enforce** via existing PreToolUse:Bash | Already works — teammate must triage before committing |

### Output Mechanism Differences

| Event | Block mechanism | Feedback mechanism |
|---|---|---|
| Stop | `{"decision": "block", "reason": "..."}` via stdout | Reason shown to agent |
| TeammateIdle | `exit 2` + stderr | Stderr fed back to teammate, continues working |
| TaskCompleted | `exit 2` + stderr | Stderr fed back to agent, task NOT marked complete |
| PreToolUse | `exit 2` + stderr OR `permissionDecision: "deny"` | Stderr/reason shown to agent |

Important: TeammateIdle and TaskCompleted do **not** support matchers — they fire on every occurrence. Our handlers must do their own filtering.

---

## Integration Points

See "Hook Compatibility — Empirical Results" section above for the full confirmed list. Summary:
- **PreToolUse/PostToolUse** — work for teammates (conflict detection, TDD order, lint, security triage, commit parsing)
- **SubagentStart** — injects SMM + behavioral guide at teammate spawn
- **SessionStart/SessionEnd/UserPromptSubmit/Stop** — don't fire for teammates (no changes needed)
- **Prompt nuggets** — don't work for teammates (UserPromptSubmit doesn't fire). **Limitation to address in v2.**

### New Hooks for Agent Teams

| Hook Event | Script | Purpose |
|---|---|---|
| `TaskCompleted` | `task_completed.py` | TDD gate + update `backlog_item` status in SMM |
| `TeammateIdle` | `teammate_idle.py` | TDD gate + check if unfinished backlog items remain |

### Lead-Specific Skills

| Skill | Purpose |
|---|---|
| `/xp-sprint-start` | Sprint goal, spec gathering, planning game, backlog creation |
| `/xp-sprint-review` | Compare delivered items against sprint goal, summarize |
| `/xp-sprint-retro` | Cross-session retrospective for the sprint |
| `/xp-spawn-team` | Read backlog, create Agent Team tasks with dependencies |

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

## Platform Findings (from docs as of 2026-03-23)

### Confirmed Behaviors

- **Teammates load project context automatically** — CLAUDE.md, MCP servers, and skills. This means our plugin hooks and skills load for teammates.
- **Team config on disk** — `~/.claude/teams/{team-name}/config.json` with `members` array (name, agent ID, agent type). Teammates can read this to discover each other.
- **Task list on disk** — `~/.claude/tasks/{team-name}/`. Our hooks could read this.
- **Plan approval is built-in** — lead can require teammates to plan before implementing. Lead reviews and approves/rejects autonomously. May complement or replace our plan review for teammates.
- **File conflict is NOT enforced by platform** — "Two teammates editing the same file leads to overwrites" is a best practice, not enforcement. Our `.coordination.json` conflict detection is a genuine value-add.
- **Permissions set at spawn** — all teammates inherit lead's permission mode. Can be changed individually after spawn.
- **Teammate messaging** — direct (one-to-one) and broadcast. Automatic delivery. Lead doesn't need to poll.

### Resolved by Empirical Testing (2026-03-23)

- **Hook events for teammates** — PreToolUse/PostToolUse/SubagentStart/SubagentStop fire. SessionStart/SessionEnd/UserPromptSubmit/Stop do NOT fire. TeammateIdle/TaskCompleted fire as documented.
- **Plugin hooks on teammates** — **YES**, `hooks/hooks.json` hooks fire for teammates.
- **Teammates share the lead's session_id** — they are subagent-like, not independent sessions.

### Still Unconfirmed

- **Worktree isolation for teammates** — Agent Teams docs don't explicitly say teammates get worktrees. Need to verify or request via spawn prompt.

### Platform Gaps (We Need to Fill)

- **No PR/merge workflow** — docs say nothing about PRs, merging, or integration. Entirely on us.
- **No conflict prevention** — file-level, platform only warns. Our `.coordination.json` handles this.
- **No sprint/backlog concept** — platform has tasks but no multi-session persistence. Our SMM handles this.

## Platform Limitations and Mitigations

| Limitation | Impact | Mitigation |
|---|---|---|
| Teams don't survive session resumption | Can't keep same team across sessions | Sprint state in SMM; recreate team each session |
| One team per session | Can't have sub-teams | Keep team flat; lead coordinates all teammates |
| No nested teams | Teammates can't spawn sub-teammates | Each teammate is a leaf worker |
| Lead is fixed | Can't rotate coach role | Lead is always the main session |
| Teammates don't inherit lead's history | Teammates lack planning context | Good spawn prompts + SMM injection via SubagentStart |
| Task status can lag | Blocked items may not auto-unblock | `TaskCompleted` hook as backup to update status |
| Shutdown can be slow | Session end delayed | Design for graceful degradation |
| Split panes require tmux/iTerm2 | Not all terminals supported | In-process mode works everywhere |
| No PR/merge workflow | No integration mechanism | Lead reviews PRs, manages merges (see PR Workflow section) |
| No worktree confirmation | Teammates may not get isolated worktrees | Verify empirically; request via spawn prompt if needed |

---

## Open Questions

### Resolved by Empirical Testing (2026-03-23)

| # | Question | Answer |
|---|---|---|
| 1 | Stop event scope | **Model B** — Stop does NOT fire for teammates. Need TeammateIdle equivalents. |
| 2 | SessionStart scope | Does NOT fire for teammates. No guards needed. |
| 3 | UserPromptSubmit scope | Does NOT fire for teammates, even when messaging them directly. No guards needed. |
| 4 | Plugin hooks on teammates | **YES** — PreToolUse and PostToolUse fire for teammates. Plugin hooks work. |
| 5 | Teammate agent_type | Custom teammate name (e.g., "agent-updater"). Appears in SubagentStart/SubagentStop. |
| 6 | Teammate skill invocation | Skills load for teammates (docs confirmed). Invocation needs further testing. |

### Still Open (Resolve During Implementation)

7. **Team size heuristics.** Agent Teams docs suggest 3-5 teammates, 5-6 tasks each. Should the planning game factor this in?

8. **Sprint length.** Explicit (customer sets it) or emergent (sprint ends when backlog is done)?

9. **Failed items.** Deferred to next sprint? Reassigned? Lead takes over?

10. **Integration order.** Lead enforces merge order, or worktree merges handle it naturally?

11. **Teammate specialization.** Roles (e.g., "frontend specialist") or general-purpose?

12. **Sprint review format.** Run acceptance criteria? Show test results? Generate summary?

13. **Lead context management.** Delegate PR reviews to subagent? (Recommendation: yes)

14. **Worktree merge conflicts.** Lead resolves, or retry mechanism?

15. **Customer availability.** Queue questions with assumptions, or block?

16. **Worktree isolation.** Do teammates automatically get worktrees? Needs empirical verification.

17. **Simplify threshold on teammates.** Teammates run `/simplify` (same threshold as main agent: 3+ code files). Is that threshold right for teammate-sized work items, or should it be lower?

---

## v1 Limitations That Affect v2

These are confirmed limitations from v1 testing and empirical results that must be addressed:

| Limitation | Impact on Teams | Required Change |
|---|---|---|
| **Prompt nuggets don't work for teammates** | Teammates can't see mid-session signal events (new concerns, decisions, assumptions from other agents) | Need alternative: direct messaging, broadcast hook, or read-on-demand from event log |
| **Stop gates don't fire for teammates** | No simplify, quality review, or TDD enforcement at stop time | Build TeammateIdle and TaskCompleted handlers |
| **Behavioral guide is solo-focused** | Process section tells teammates to run kickoff, plan mode, etc. | Inject teammate-specific guide via SubagentStart detection |
| **No sprint/backlog event types** | Can't persist sprint state across sessions | Add `sprint` and `backlog_item` to event schema + validation |
| **Compaction doesn't know about sprint events** | Active sprint events might get compacted | Add retention rules for active sprint/backlog_item events |
| **Housekeeping doesn't curate Sprint pillar** | No sprint progress in curated SMM | Add Sprint section to housekeeping curation |
| **Kickoff doesn't check sprint status** | Lead needs to know if mid-sprint or starting new sprint | Add sprint status check to kickoff flow |
| **No PR/merge workflow** | Platform has no integration mechanism | Build lead-driven PR review + merge flow |
| **context:fork doesn't reliably delegate** | Plan reviewer and retro subagents sometimes run inline | v1 issue, still present — fallback instructions mitigate |

---

## Underspecified Areas (Needs Design)

### PR and Merge Workflow

The platform has no PR workflow. We need to design the full cycle:

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

**Key question:** Should the lead do PR reviews inline (context cost) or delegate to a review subagent (coordination cost)?

### Teammate Behavioral Guide

The current behavioral guide Process section is written for the main agent. Teammates need different instructions:

- **DO:** Claim tasks, write tests first, commit frequently, create PRs, record decisions/assumptions/concerns
- **DON'T:** Run kickoff, do housekeeping, set goals, run retrospectives
- **SKIP:** EnterPlanMode guidance (built-in plan approval handles this), /xp-quality-review (lead reviews PRs instead)
- **KEEP:** /simplify after commits, /xp-security-triage before commits, TDD discipline, concern recording

Options:
- Split behavioral guide into two files (main agent vs teammate)
- Single guide with a "For teammates" section
- Detect teammate in SubagentStart and inject a different guide

### Cross-Teammate Communication

The SMM is the broadcast channel, but it's async (prompt nuggets fire on next prompt). For urgent cross-cutting discoveries:

- **Teammate A discovers a breaking API change** — other teammates need to know NOW
- **Current mechanism:** A records a `concern` event → prompt nugget surfaces it to others on their next prompt
- **Gap:** "next prompt" could be minutes away if the teammate is mid-implementation

Options:
- Direct messaging: teammate sends message to affected teammates (platform supports this)
- Broadcast: send to all teammates (platform supports, but expensive)
- Accept the async delay — prompt nuggets are "good enough" for most cases
- Hybrid: concerns with `severity: high` trigger a broadcast via a hook

### Bootstrap Flow (First Session with Agent Teams)

What happens the very first time someone uses xp-agents with Agent Teams?

1. `/xp-kickoff` runs — seed SMM, first retro (nothing to analyze), goals
2. User describes what they want to build
3. Lead runs sprint start — goal setting, spec gathering, planning game
4. Lead decomposes into backlog items
5. Lead spawns team, creates tasks from backlog
6. Teammates execute

This is the same as the sprint start flow, but without any prior sprint history. The seed SMM provides default constraints and wisdom. The planning game produces the first backlog.

**Key question:** Does the lead need a special "first sprint" skill, or does `/xp-sprint-start` handle this naturally?

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

How does a `backlog_item` event in the SMM map to a task in `~/.claude/tasks/{team-name}/`? Two systems track work:
- **SMM event log** — `backlog_item` events with acceptance criteria, dependencies, status. Persists across sessions.
- **Platform task list** — `~/.claude/tasks/{team-name}/`. Ephemeral, per-team.

The lead must translate: read backlog items from SMM, create platform tasks for the current team. When tasks complete, update backlog item status in SMM.

**Key question:** Is this a skill (`/xp-spawn-team` reads backlog, creates tasks)? Or a hook (`TaskCompleted` updates backlog items)?

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
6. **Spawn team** (new) — create tasks from unblocked backlog items

**Key question:** Modify existing `/xp-kickoff` to be sprint-aware, or create a separate `/xp-sprint-kickoff`?

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
| `backlog_item` event type | Defined with full schema, lifecycle, and acceptance criteria |
| Planning game at SessionStart | Sprint-scoped planning game with spec gathering phase |
| Plan reviewer validates against backlog | Unchanged — plan reviewer checks items are right-sized, TDD-ordered |
| Burn down rendering | Sprint section in curated SMM with progress summary |
| Requirements decomposition subagent | Lead-driven spec gathering, can delegate to subagent |
| Customer confirms priorities once | Sprint goal set once, lead handles tactical decisions |

The key addition: **the sprint as a first-class lifecycle** that wraps the existing session lifecycle, with the team lead as the persistent orchestrator across ephemeral Agent Team instances.

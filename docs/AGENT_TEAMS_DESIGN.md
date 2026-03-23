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
| **Teammates** | Separate Claude Code instances, own context windows, own worktrees |
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
- Work in isolated worktrees (`isolation: worktree`)
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
| Tests must pass | `tdd_stop_gate.py` on Stop (may not fire for teammates — see Hook Compatibility Analysis). Backup: `TeammateIdle` + `TaskCompleted` handlers. |
| Red-green-refactor | Each teammate follows the cycle independently |

TDD order check (PreToolUse) works for teammates. TDD stop gate (Stop) needs empirical testing — if Stop doesn't fire for teammates, the `teammate_idle.py` and `task_completed.py` handlers provide equivalent enforcement.

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

The SMM is the mechanism for collective ownership. Every teammate gets the same curated view of Intent, Constraints, Risks, and Wisdom. Prompt nuggets surface new decisions and concerns as they happen.

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

## Hook Compatibility Analysis

### The Central Question: Do Teammates Get Stop Events?

The docs are ambiguous on a critical point. The hooks reference says Stop fires for "the main Claude Code agent." But the agent teams docs say teammates are "separate Claude Code instances" and "full, independent Claude Code session[s]" — explicitly NOT subagents. If a teammate is its own full session, then it IS the main agent within that session.

Three possible architectures (empirical testing required):

**Model A — Teammates get Stop.** Stop fires within the teammate's own session (it's a full session, so it's "the main agent" in that context). TeammateIdle fires separately — possibly on the lead — as an additional coordination event. Our Stop gates would work unchanged.

**Model B — Teammates don't get Stop.** Stop only fires for the lead's session. TeammateIdle is the teammate replacement for Stop. SubagentStop fires on the lead when a teammate finishes. Our Stop gates would need TeammateIdle equivalents.

**Model C — Hybrid.** Stop fires for teammates but only for hooks defined in the teammate's own frontmatter (converted to SubagentStop per the subagent docs). Global/plugin hooks on Stop only fire for the lead. TeammateIdle is the plugin-accessible gate for teammates.

**Evidence for each:**

| Evidence | Supports |
|---|---|
| Agent teams doc: "separate Claude Code instances," "full, independent session" | Model A |
| Agent teams doc: "Unlike subagents, which run within a single session" | Model A |
| Hooks ref: Stop fires for "the main Claude Code agent" | Model B |
| Hooks guide: "Stop hooks fire whenever Claude finishes responding" (no "main" qualifier) | Model A |
| Subagent docs: "Stop hooks in frontmatter are automatically converted to SubagentStop" | Model C |
| TeammateIdle exists at all — why, if Stop already fires for teammates? | Model B |
| TeammateIdle exit 2: "teammate receives stderr as feedback and continues working" | Could be any |

**Recommendation:** Run empirical tests before building. Create a simple hook on Stop that writes a marker file, spawn a teammate, and check if the marker appears. This resolves the ambiguity definitively.

### Empirical Test Plan

Tests to run with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` enabled:

1. **Stop event scope.** Register a Stop hook that writes a timestamp to a file. Spawn a team with one teammate. Does the file get written when the teammate finishes?

2. **SessionStart scope.** Register a SessionStart hook that logs the `source` and `agent_id` fields. Spawn a teammate. Does SessionStart fire for the teammate? What source value?

3. **TeammateIdle scope.** Register a TeammateIdle hook that logs all input fields. Where does it fire — on the lead's session or the teammate's?

4. **UserPromptSubmit scope.** Does UserPromptSubmit fire for teammate prompts (messages from lead/other teammates)?

5. **Plugin hooks on teammates.** Does a plugin's hooks.json fire for teammates? Or only settings.json hooks?

6. **Skill availability.** Can a teammate invoke a plugin skill (e.g., `/xp-quality-review`)?

7. **SubagentStart for teammates.** Does SubagentStart fire when a teammate is spawned? What `agent_type` value?

### Known Compatibility Issues

Regardless of which model is correct, several hooks have confirmed issues:

#### Session Lifecycle Hooks

| Hook | Event | Issue | Severity |
|---|---|---|---|
| `session_start.py` | SessionStart | Writes `.needs-kickoff` marker on `source: "startup"`. If teammates trigger SessionStart, this re-writes the marker the lead already cleared, blocking all teammates. | **Critical** |
| `retrospective.py` | SessionStart | Prepares `.retro-input.json` for each teammate. Wasteful and may corrupt lead's retro data. | Medium |
| `session_end.py` | SessionEnd | Would append `session_end` event for each teammate. Pollutes event log and breaks aging calculations. | Medium |
| `kickoff_gate.py` | UserPromptSubmit | Blocks prompts until `/xp-kickoff` runs. If SessionStart re-writes the marker, teammates are blocked. Even without that, teammates don't need kickoff. | **Critical** |
| `kickoff_done.py` | PostToolUse:Skill | Clears `.needs-kickoff` and injects behavioral guide. If a teammate runs housekeeping, it would interfere with lead's kickoff state. | Medium |

#### Stop Gates (if Model B or C is correct)

| Hook | Event | Issue | Severity |
|---|---|---|---|
| `simplify_gate.py` | Stop | Doesn't fire for teammates. No `/simplify` enforcement. | High |
| `quality_review_gate.py` | Stop | Doesn't fire for teammates. No quality review enforcement. | High |
| `tdd_stop_gate.py` | Stop | Doesn't fire for teammates. Can stop with failing tests. | **Critical** |

#### UserPromptSubmit Hooks

| Hook | Event | Issue | Severity |
|---|---|---|---|
| `user_prompt_log.py` | UserPromptSubmit | Logs every prompt as `customer_input`. Teammate prompts (messages from lead) aren't customer input — would pollute the event log. | Medium |
| `prompt_nugget.py` | UserPromptSubmit | Injects new signal events. Probably works correctly and is beneficial. | None (works) |

#### Hooks That Work Correctly

| Hook | Event | Why It Works |
|---|---|---|
| `pre_tool_write.py` | PreToolUse:Write | File-based checks (`.coordination.json`, TDD order). Works for any agent. |
| `pre_tool_bash.py` | PreToolUse:Bash | Security triage gate is file-based. Teammate needs skill access for `/xp-security-triage` (confirmed available). |
| `post_tool_use.py` | PostToolUse:Write | Status/working_on tracking. Agent ID from input data. Works correctly. |
| `lint_check.py` | PostToolUse:Write | Runs linter on written file. Agent-agnostic. |
| `bash_post_tool.py` | PostToolUse:Bash | Commit size check, test result parsing. Agent-agnostic. |
| `subagent_start.py` | SubagentStart | SMM + behavioral guide injection. Works for teammates (confirmed). |
| `prompt_nugget.py` | UserPromptSubmit | Surfaces new events. Beneficial for teammates. |
| `pre_compact.py` | PreCompact | SMM backup. Agent-agnostic. |

### Required Changes

#### 1. Teammate Detection

Need a function to distinguish teammates from the main agent and from xp- subagents. The challenge: different hook events provide different fields.

```python
def is_teammate(input_data: dict) -> bool:
    """True when running inside an Agent Team teammate.

    Heuristic: has agent_id (not main), doesn't start with xp-.
    Needs validation via empirical testing.
    """
    agent_id = input_data.get("agent_id", "")
    agent_type = input_data.get("agent_type", "")
    if not agent_id or agent_id == "main":
        return False
    if isinstance(agent_type, str) and agent_type.startswith("xp-"):
        return False
    return True
```

Known fields by event:
- `TeammateIdle` / `TaskCompleted`: have `teammate_name`, `team_name` (definitive)
- `SubagentStart` / `SubagentStop`: have `agent_id`, `agent_type`
- `PreToolUse` / `PostToolUse` / `Stop`: have `agent_id`, `agent_type` (when in subagent/teammate)
- `SessionStart` / `UserPromptSubmit`: need empirical testing for what fields are present

#### 2. Skip Ceremonies for Teammates

Teammates execute, they don't orchestrate. These hooks should skip for teammates:

```python
# In session_start.py — don't write kickoff marker for teammates
if is_teammate(input_data):
    return GUPP_TEXT + SKILLS_TEXT  # Context only, no marker

# In kickoff_gate.py — don't block teammates
if is_teammate(input_data):
    return None

# In user_prompt_log.py — don't log teammate prompts as customer_input
if is_teammate(input_data):
    return None

# In retrospective.py — don't prepare retro for teammates
if is_teammate(input_data):
    return None

# In session_end.py — don't write session_end for teammates
if is_teammate(input_data):
    return None
```

#### 3. Stop Gate Equivalents for TeammateIdle / TaskCompleted

If Stop doesn't fire for teammates (Model B/C), we need equivalent enforcement on the teammate-specific events. These use exit 2 + stderr (not `decision: "block"` JSON):

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

### Hooks That Apply to Teammates (Confirmed Working)

These hooks fire for teammates and work correctly without changes:

| Hook | Effect on Teammates |
|---|---|
| `pre_tool_write.py` | Conflict detection via `.coordination.json`, TDD order check |
| `pre_tool_bash.py` | Commit security triage gate (teammate can run `/xp-security-triage`) |
| `post_tool_use.py` | Auto status/working_on, conflict detection |
| `lint_check.py` | Linter after every write |
| `bash_post_tool.py` | Commit size check, test result parsing |
| `subagent_start.py` | SMM + behavioral guide injected at teammate spawn |
| `prompt_nugget.py` | New decisions/concerns surfaced to teammates |

### Hooks That Need Teammate Awareness

| Hook | Change Needed |
|---|---|
| `session_start.py` | Skip `.needs-kickoff` marker for teammates |
| `kickoff_gate.py` | Skip entirely for teammates |
| `user_prompt_log.py` | Skip `customer_input` logging for teammates |
| `retrospective.py` | Skip retro prep for teammates |
| `session_end.py` | Skip `session_end` event for teammates |
| `kickoff_done.py` | Skip marker clearing for teammates |

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

### Unconfirmed (Empirical Testing Required)

- **Which hook events fire for teammates** — docs don't clarify. Only `TeammateIdle` and `TaskCompleted` are explicitly documented as teammate hooks.
- **Worktree isolation for teammates** — design doc assumes `isolation: worktree` but Agent Teams docs don't explicitly say teammates get worktrees. Need to verify.
- **Plugin hooks on teammates** — do `hooks/hooks.json` hooks fire for teammates, or only settings.json hooks?

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

### Must Resolve Before Building (Empirical Testing)

1. **Stop event scope.** Does Stop fire for teammates? This determines whether our three Stop gates work or need TeammateIdle equivalents. See "Empirical Test Plan" above.

2. **SessionStart scope.** Does SessionStart fire for teammates? What `source` value? This determines how many hooks need `is_teammate()` guards.

3. **UserPromptSubmit scope.** Do teammate prompts (messages from lead/other teammates) trigger UserPromptSubmit? This affects `kickoff_gate.py`, `user_prompt_log.py`, and `prompt_nugget.py`.

4. **Plugin hooks on teammates.** Do hooks from `hooks/hooks.json` (plugin scope) fire for teammates, or only settings.json hooks?

5. **Teammate `agent_type` value.** What value appears in `agent_type` for a teammate? This determines how `is_teammate()` detection works.

6. **Teammate skill invocation.** Can a teammate invoke a plugin skill by name (e.g., `/xp-security-triage`)? Confirmed by docs that skills load, but need to verify invocation works.

### Design Decisions (Resolve During Implementation)

7. **Team size heuristics.** How many teammates for a given backlog size? Agent Teams docs suggest 3-5, with 5-6 tasks per teammate. Should the planning game factor this in?

8. **Sprint length.** How many sessions constitute a sprint? Should this be explicit (customer sets it) or emergent (sprint ends when backlog is done)?

9. **Failed items.** When a teammate can't complete an item — deferred to next sprint? Reassigned to another teammate? Lead takes over?

10. **Integration order.** When items have dependencies, merge order matters. Does the lead enforce merge order, or do worktree merges handle this naturally?

11. **Teammate specialization.** Should teammates have roles (e.g., "frontend specialist") or be general-purpose? Agent Teams supports custom agent types for teammates.

12. **Sprint review format.** What does "demo" look like for agent teams? Run acceptance criteria? Show test results? Generate a summary document?

13. **Lead context management.** The lead's context window fills with PR reviews and coordination. How do we keep it clean? Delegate reviews to a subagent?

14. **Worktree merge conflicts.** When two teammates both merge into the main branch, what happens if they conflict? Does the lead resolve, or is there a retry mechanism?

15. **Customer availability.** What if the customer isn't available when the lead needs to escalate? Queue questions and continue with assumptions? Block?

16. **Simplify threshold on teammates.** Teammates run `/simplify` (same threshold as main agent: 3+ code files). Is that threshold right for teammate-sized work items, or should it be lower?

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

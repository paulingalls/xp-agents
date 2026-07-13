# Shared Mental Model — Design

## Purpose

The Shared Mental Model (SMM) answers four questions that, if unanswered, cause agents to make mistakes:

1. **Am I building the right thing?** (Intent)
2. **What boundaries must I respect?** (Constraints)
3. **What could go wrong?** (Risks)
4. **What mistakes should I avoid?** (Wisdom)

Everything else is noise. The SMM is a briefing, not a database.

**Coordination** ("Am I stepping on someone's toes?") is handled separately via `.coordination.json` — a real-time, ephemeral file updated on every file write. It is not part of the curated SMM because it operates at a fundamentally different cadence (per-tool-call vs once-per-session).

---

## The Four Pillars

### Intent

What the customer wants, in their words, distilled to deliverable outcomes.

```markdown
## Intent
- "Build a REST API for user management with auth and role-based access"
- 📋 Add role-based access control to endpoints (undelivered)
- 📋 Set up token refresh flow (undelivered)
```

**Enter:** Customer speaks → agent distills to a deliverable outcome. Not every input becomes an intent — "fix the typo" is a task, "add role-based access" is an intent.

**Leave:** Agent marks it delivered when the work ships. Or customer supersedes it.

**Cap:** see [PROCESS_GUIDE.md §Pillars](../plugins/xp-agents/PROCESS_GUIDE.md#pillars) — that file is the single source of truth for cap numbers (don't restate inline). Oldest undelivered intents get flagged: "still wanted?"

**Empty = no direction.** If no intents exist, the agent should ask what to build next.

---

### Constraints

Decisions and conventions that bound the solution space.

```markdown
## Constraints
- Use PostgreSQL for persistence
- JWT for authentication
- REST, not GraphQL
- camelCase for API fields
- Python 3.10+, stdlib only
```

**Enter:** Agent makes an architectural choice or establishes a convention, with rationale. Must be stated explicitly — not inferred from code.

**Leave:** Only when explicitly superseded by a new constraint that references the old one. Constraints don't age out — "use Postgres" doesn't become less true over time. Decisions age after 3 sessions in the event log (compacted if confirmed and curated into the SMM).

**Cap:** see [PROCESS_GUIDE.md §Pillars](../plugins/xp-agents/PROCESS_GUIDE.md#pillars). Beyond the cap, some are too granular (move to code/linting).

---

### Risks

Things that could cause problems if ignored. Unifies what were previously separate categories (assumptions, concerns, questions, debt).

```markdown
## Risks
- 🔴 No integration tests for role checks (6 sessions)
- ⚠️ Auth middleware uses placeholder secret (3 sessions)
- Token refresh flow unverified — assumed 15-min expiry
```

Three severities, one category:
- **Uncertainty** — "we think X but haven't verified"
- **Problem** — "X is wrong and needs fixing"
- **Debt** — "we chose to defer X"

**Enter:** Agent identifies something uncertain, problematic, or owed.

**Leave:** Resolved. Uncertainty verified or invalidated. Problem fixed. Debt repaid.

**Escalate:** Risks not addressed get louder. After 3 sessions: ⚠️. After 6 sessions: 🔴. A 🔴 risk appears first in the section.

**Cap:** see [PROCESS_GUIDE.md §Pillars](../plugins/xp-agents/PROCESS_GUIDE.md#pillars). Exceeding the cap is itself a 🔴 risk.

**Same-session rule:** Assumptions from plan reviews must be verified or dropped in the session they're created. They don't linger as "unverified" indefinitely.

---

### Coordination (separate from SMM)

Coordination is **not a pillar of the curated SMM**. It operates at a fundamentally different cadence — real-time per-tool-call updates vs once-per-session curation. It lives in `.coordination.json`.

```json
{
  "main": {"working_on": ["src/auth/roles.ts"], "updated": "2026-03-18T02:30:00+00:00"},
  "agent-2": {"working_on": ["src/auth/test_roles.ts"], "updated": "2026-03-18T02:31:00+00:00"}
}
```

**Enter:** Automatically — agent starts working on files (PostToolUse updates on every Write/Edit).
**Leave:** Automatically — agent finishes or session ends. Ephemeral.
**Cap:** Bounded by active agents. Solo: 1 entry. Team: N entries.
**Conflict detection:** `pre_tool_write.py` reads this file for Write/Edit/MultiEdit (O(1), blocks on overlap). `pre_tool_bash.py` checks heuristically for Bash (advisory, never blocks).

---

### Project Files (separate from curated SMM)

Sprint and planning state live in separate files, not in the curated SMM pillars. They operate at a different cadence — sprint lifecycle (days/weeks) vs session curation.

| File | Created By | Lifecycle | Purpose |
|---|---|---|---|
| `system_context.json` | `/xp-system-context` | Persistent, updated as system evolves | Product overview, architecture, technical constraints |
| `execution_plan.json` | `/xp-plan` | Persistent across sprints, archived when all milestones delivered | Milestones, change zones, impact zones, design details |
| `sprint.json` | `/xp-sprint-start` | One active at a time | Stories, sizes, statuses, acceptance criteria |

**Sprint events** (`type: sprint`) record lifecycle transitions (start, end) with metadata including velocity (stories_planned, stories_delivered, stories_carried).

**Sprint-aware injection:** xp-plan-reviewer and xp-retrospective get sprint data via SubagentStart. Teammates get filtered stories (only their assigned work). `/xp-assign` preload dumps both sprint and the current plan.

---

### Mutable State Files (ring-buffer pattern)

New mutable SMM state files (anything besides the four pillars and the append-only event log) follow a single canonical shape:

```json
{
  "version": <int>,
  "entries": [ {...}, {...} ]
}
```

`session_history.json` is the concrete reference implementation — see `plugins/xp-agents/smm/session_history.py`. Every new mutable state file inherits this shape because it gets you four properties for free:

- **Schema versioning** — the top-level `version` field lets future migrations introspect the on-disk shape without sniffing entry contents.
- **Atomic write + symlink rejection** — both go through `smm_store`-style helpers (`write_text_atomic` + `path.is_symlink()` check). Never partial-write, never follow a malicious symlink out of `SMM_DIR`.
- **Fail-loud on corrupt JSON or schema-invalid entries** — `load_*` functions raise `ValueError` rather than silently returning empty, so a corrupted file surfaces immediately at the next read instead of erasing user data on the next write.
- **Bounded growth** — `entries` is sliced to the most-recent N at append time (`session_history` defaults to 5). The "ring buffer" framing is logical: oldest-out, newest-in, no unbounded accumulation.

When adding a new mutable state file, copy the `session_history.py` template (`validate_*`, `empty_*`, `load_*`, `save_*`, `append_entry`) before authoring a bespoke shape. The constraint is the feature — every state file looking the same makes the next migration trivial.

**Constraint reference:** SMM constraint `83297d6921d4` codifies this pattern.

Current instances: `session_history.json` and `adoption.json`.

`adoption.json` (`smm/adoption_store.py`) carries one caveat worth copying if you write another derived state file. It records which retro Try items and triage items were adopted or deferred — a memory that otherwise lives only in events the log eventually archives, while the items themselves are re-offered from files that are never compacted. Its only writer is `compact.py`, at the instant the events would be lost. That makes it a **derived cache**, and a cache may not be allowed to wedge the thing that derives it: compaction is the only bound on `events.jsonl`, so an unreadable ledger is quarantined (moved to `adoption.json.corrupt`, never deleted) and rebuilt, rather than raising. The store still fails loud per the pattern above — the recovery lives in its caller, so a direct reader never silently gets an empty ledger.

### SMM_DIR resolution (separate from SMM)

All scripts resolve the SMM directory via `${CLAUDE_PLUGIN_ROOT}/smm/init.sh` (single canonical source). The shell helper honors a `$SMM_DIR` environment override; otherwise it derives `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/`.

- **SMM is at user level, not project level** — `${CLAUDE_PLUGIN_DATA}` lives outside the working tree, so worktrees share the same SMM (intentional — it's the broadcast bus).
- **Never hardcode SMM paths** — every script and hook calls `init.sh` (or accepts `--smm-dir DIR` from CLIs). Tests stand up a temp `SMM_DIR` env var and run scripts unmodified.

---

### Wisdom

Behavioral rules learned from experience. The institutional memory.

```markdown
## Wisdom
- Write tests before implementation — the TDD gate blocks otherwise
- Split large changes into separate commits
- Always record decisions when making architectural choices
- Complete the review cycle (code-review → quality review) before committing code changes; Tier 2/3 cover security at /xp-accept and close
- Don't amend pushed commits — creates divergent history
```

**Enter:** Deliberate promotion only:
- A retro "Try" is adopted and works → promoted to Wisdom
- A retro "Fix" recurs 3+ times → distilled into a rule
- Customer gives explicit guidance → captured

Each item is a **behavioral rule** phrased as "do X" or "don't do Y" with a brief "because Z."

**Leave:** Relevance decay. Not referenced for 10+ sessions → demoted. Or explicitly dropped by the team.

**Cap:** see [PROCESS_GUIDE.md §Pillars](../plugins/xp-agents/PROCESS_GUIDE.md#pillars). Adding one at cap requires removing one. The constraint is the feature — only the most important lessons survive.

**Not a diary.** "Session 5 was hard" is not Wisdom. "Always run tests before claiming done" is Wisdom.

---

## Health Signals

Each pillar has a natural size that signals project health. **Healthy ranges and caps are owned by [PROCESS_GUIDE.md §Pillars](../plugins/xp-agents/PROCESS_GUIDE.md#pillars)** — refer there rather than restating numbers here. The asymmetric warning shape per pillar:

| Pillar | Below-range signal | Over-cap signal |
|---|---|---|
| Intent | no direction | scope creep |
| Constraints | no decisions made | over-specified (move some to code/linting) |
| Risks | false confidence | unmanaged risk |
| Wisdom | not learning | cap reached, prune |

Coordination health is tracked separately via `.coordination.json` (bounded by active agent count, not curated).

A healthy curated SMM totals roughly 12-30 items and ~300-600 tokens — small enough that an agent reads the entire mental model in about 2 seconds. The unhealthy states themselves become signals — if Risks hits its cap, the SMM itself should flag: "Risk register at capacity — resolve items before adding more."

---

## Architecture

### Three layers (four-file architecture)

The SMM directory contains four key files:
- `events.jsonl` — append-only event log (staging buffer)
- `shared_mental_model.json` — curated four-pillar briefing
- `execution_plan.json` — milestones with change zones and design details
- `sprint.json` — current sprint stories and statuses

**1. Data trails (hooks, automatic)**

During a session, command hooks leave raw event trails in the event log. These are mechanical — no judgment, no LLM, just data capture:

- `customer_input` — the user's exact words
- `status` — what files are being touched
- `decision` — architectural choices as they happen
- `concern` — problems noticed by hooks or subagents
- `session_end` — session summary

Hooks don't curate the SMM. They just leave breadcrumbs.

**2. Curation (housekeeping skill, once per session)**

At session start, after the retrospective, housekeeping reads the raw event trail and curates the four pillars with LLM judgment:

- Distills `customer_input` events into Intent items (or not — "fix the typo" is a task, not an intent)
- Adds new decisions to Constraints
- Unifies assumptions, concerns, and debt into Risks with severity
- Promotes retro Try items to Wisdom (or drops them)
- Prunes graduated Constraints, resolved Risks, delivered Intents
- Enforces caps — flags when a pillar is unhealthy

A preload script prepares data for housekeeping — aggregates events, computes aging, identifies what's new since last curation. The judgment happens in the skill, not in Python.

Housekeeping writes the curated `shared_mental_model.json` via `smm_cli.py save`.

**3. Mid-session context (additionalContext, sparse)**

During the session, lightweight context is injected at specific moments:

- **UserPromptSubmit:** Prompt nugget — new signal events since last prompt (watermark-based, ~50-100 tokens)
- **SubagentStart:** Tiered context injection — Explore subagents get Intent+Constraints only (~200 tokens); xp-code-reviewer gets full SMM (for drift management); all others get full curated SMM + process guide (~1000 tokens)
- **After housekeeping:** Process guide via PostToolUse:Skill hook

Conflicts are handled by PreToolUse hooks (blocking for Write, advisory for Bash) — not as context injection. No per-tool-call event log reads. The agent has the full SMM from housekeeping. Nuggets surface only what's new and actionable.

### The materializer's role

`materialize.py` prepares structured curation data for housekeeping:

- Aggregates events since last curation (watermark-based)
- Computes aging for risks and constraints
- Identifies new customer_input, decisions, concerns, resolutions
- Outputs structured JSON that housekeeping can reason about

The `shared_mental_model.json` is written by housekeeping (with judgment) via `smm_cli.py save`, not by the materializer.

### Per-item content limits

Two layers enforce per-item content size so callers don't author oversized payloads:

- **At write time (`event_schema.CONTENT_BUDGETS`)** — `validate_event` rejects events whose `content` exceeds the per-type budget. Authoritative table lives in `plugins/xp-agents/smm/event_schema.py:CONTENT_BUDGETS`; read it for current numbers rather than restating here. A few types are uncapped (`customer_input`, `commit`) because the source bounds their size — a user prompt, a commit body.
- **At materialization (`materialize._CUSTOMER_INPUT_TRUNCATE_LIMIT`)** — uncapped `customer_input` events are truncated when bucketed into the housekeeping preload, with a `content_truncated` flag on the summary so housekeeping can chase the original if needed. Summary-side only — the raw event in `events.jsonl` is unchanged.

Hard ceilings (`MAX_CONTENT_LENGTH`, `MAX_EVENT_BYTES`, same module) cap unbounded growth from any single write — the safety net beneath the per-type budget.

---

## Injection Model

| When | What | Cost |
|---|---|---|
| Session start | GUPP + skills list only (no SMM) | ~100 tokens, once |
| SessionStart (teammate) | CLI teammates get XP Values + TEAMMATE_GUIDE.md + rendered SMM via SessionStart hook | ~1000 tokens, once |
| After housekeeping | Agent Reads curated SMM file directly | ~500 tokens, once |
| After housekeeping | Process guide + XP values via PostToolUse:Skill hook | ~500 tokens, once |
| UserPromptSubmit | Nugget: new signal events since last prompt (watermark-based) | ~50-100 tokens |
| SubagentStart | Tiered: Explore gets Intent+Constraints, Plan/default gets full SMM | ~200-500 tokens |

**No PreToolUse delta.** PreToolUse hooks (`pre_tool_write.py` for Write/Edit/MultiEdit, `pre_tool_bash.py` for Bash) use only file-based checks: `.coordination.json` for conflicts, marker files for plan review, `.review-cycle-{agent_id}.json` for commit-gated review cycle, TDD tracker for test enforcement. Zero event log reads. Coordination conflicts are detected and blocked on Write/Edit; Bash file-mods are not gated here — cross-agent damage is caught at story-close merge.

---

## Progressive Curation (CLI Teammates)

The SMM is a shared document at user level, visible to all agents across worktrees. Each agent's housekeeping run incorporates everyone's contributions:

```
Agent A starts → curates SMM from events → works, leaves event trails
Agent B starts → curates SMM (now includes A's decisions, concerns)
Agent C starts → curates SMM (includes A's + B's contributions)
Agent A restarts → curates SMM (includes B's + C's contributions)
```

The event log is the shared coordination bus (append-only, flock-protected). The shared_mental_model.json is the latest curated snapshot. Every housekeeping run makes it richer because it has more events to work with.

### Merge, don't replace

Housekeeping should **update the existing SMM**, not rewrite from scratch. This means:
- Read the current shared_mental_model.json first
- Incorporate new events since the last curation
- Add new Intents, Constraints, Risks from other agents' trails
- Mark items delivered/resolved based on new evidence
- Write the updated SMM back

This handles concurrent curation gracefully — if Agent A and Agent B both curate near-simultaneously, each reads the current state and merges their events. Even if one write is lost to a race, the next curation picks up the missed events from the log.

Flock protection on shared_mental_model.json writes (like events.jsonl) provides additional safety.

### What each agent contributes

| Agent Activity | Event Trail | Pillar Affected |
|---|---|---|
| Customer speaks | `customer_input` | Intent (housekeeping distills) |
| Architectural choice | `decision` | Constraints (housekeeping adds) |
| Problem noticed | `concern` | Risks (housekeeping unifies) |
| Uncertainty stated | `assumption` | Risks (housekeeping unifies) |
| Debt acknowledged | `debt` | Risks (housekeeping unifies) |
| File work | `status` + working_on | Coordination (automatic) |
| Retro produces Try | `retrospective` | Wisdom (housekeeping promotes) |
| Session ends | `session_end` | Aging calculations |

Every agent leaves the same kinds of trails. Housekeeping doesn't care which agent created the event — it curates all of them into one shared model.

---

## Mid-Session Context

Two injection moments during active work. Conflicts are handled by PreToolUse hooks (blocking or warning), not as separate nuggets.

### Prompt nugget (UserPromptSubmit)

Fires on each user prompt. Uses a watermark (`prompt-nugget`) to surface only new signal events (concerns, decisions, goals, debt, questions) since the last prompt:

```
New since last prompt:
- [concern] Test failures detected: 1 failed (unittest)
- [decision] Fix retrospective preload overflow, move prompt nugget...
```

~100 tokens. Top 3 by priority (concern > question > assumption > discovery > debt > decision). Most recent wins within same priority. If nothing is new, no nugget.

### SubagentStart

Tiered context injection based on subagent type. Explore subagents get only Intent+Constraints from the curated SMM (~200 tokens) — they need direction and boundaries but not full project history. `xp-code-reviewer` gets the full SMM (overriding the xp-* default of values-only) because it needs Constraints for drift management. Plan/general-purpose subagents get the full curated SMM (~500 tokens). All rendered from `shared_mental_model.json` via `smm_cli.py`.

**Note:** CLI teammates do NOT use SubagentStart — they are independent `claude -p` processes, not Agent tool subagents. Teammate context (XP Values + TEAMMATE_GUIDE.md + rendered SMM) is injected via the SessionStart hook when `is_worktree_teammate()` detects a worktree path.

### Conflict detection (not a nugget)

Conflict detection is handled by PreToolUse hooks, not mid-session nuggets:
- **Write/Edit/MultiEdit:** `pre_tool_write.py` reads `.coordination.json` and **blocks** if another agent claims the same file.
- **Bash:** no coordination gate — bash isn't statically parseable. CLI teammates run in isolated git worktrees; cross-agent damage from `mv`/`sed -i`/redirects materializes at story-close merge where git is the deterministic safety net (sprint-105 decision).

---

## Preload Data for Housekeeping

The materializer prepares structured data that enables housekeeping's judgment. Housekeeping reads this, makes curation decisions, and writes the SMM.

### Structure

```json
{
  "current_smm": {
    "intent": ["Add RBAC (undelivered)", "Token refresh (undelivered)"],
    "constraints": ["Use Postgres", "JWT for auth"],
    "risks": ["No integration tests (4 sessions)"],
    "wisdom": ["Write tests first"]
  },
  "new_since_last_curation": {
    "customer_inputs": [{"content": "also add password reset", "ts": "..."}],
    "decisions": [{"content": "Use bcrypt for hashing", "topic": "auth-hashing"}],
    "concerns": [{"content": "Empty catch block in auth", "severity": "medium"}],
    "assumptions": [],
    "debt": [],
    "questions": [],
    "resolutions": {"concern-id-1": "fixed in commit abc123"}
  },
  "retro_history": {
    "latest_tries": ["Split large commits", "Add materializer tests"],
    "recurring_fixes": ["Low decision recording rate (4 retros)"],
    "adopted_tries": ["Concern auto-resolution"]
  },
  "aging": {
    "risk-id-1": 4,
    "risk-id-2": 1
  },
  "health": {
    "intent_count": 2,
    "constraints_count": 8,
    "risks_count": 3,
    "wisdom_count": 5
  }
}
```

### What each field enables

| Field | Pillar | Judgment Enabled |
|---|---|---|
| `current_smm.*` | All | Merge, don't replace — update existing items |
| `customer_inputs` | Intent | "Is this a deliverable outcome or just a task?" |
| `decisions` | Constraints | "Add to constraints, or remove stale ones?" |
| `concerns` + `assumptions` + `debt` + `questions` | Risks | "Unify into risks, assign severity, resolve if evidence exists" |
| `resolutions` | Risks | "This risk was resolved — remove it" |
| `retro_history` | Wisdom | "This Try worked for 3 sessions — promote to Wisdom?" |
| `aging` | Risks | "This risk is 6 sessions old — escalate to 🔴" |
| `health` | All | "Risks at cap — flag it. Intent empty — ask customer." |

### Event schema implications

The current event types map well to pillars. No new types needed. Three things matter:

1. **Resolution tracking** — `metadata.resolves` already exists, just needs consistent use
2. **Session counting** — computed from `session_end` events after each item's timestamp
3. **Curation watermark** — a new marker: "housekeeping curated up to event N," so the preload knows what's new since last curation

The biggest gap: `customer_input` events exist but nobody distills them into intents. That's pure judgment — exactly what housekeeping now does.

---

## Resolved Design Questions

### Watermarks — scoped to two purposes

Watermarks serve two specific purposes:

1. **Curation watermark** — written by housekeeping: "I curated up to event N." The preload uses this to identify new events since last curation. For teams, each agent writes its own curation watermark. Compaction uses the oldest watermark as the safe truncation point.

2. **Prompt nugget watermark** — written by `prompt_nugget.py` to track which events have been surfaced to the agent. Advances on each UserPromptSubmit so only new signal events appear.

Subagent hex-ID watermarks (`.watermark-abf63d10...`) are eliminated. No per-tool-call watermarks exist.

### Event log compaction — housekeeping compacts after curation

The event log is a staging buffer, not an archive. Compaction runs at three points: after SMM curation (`smm_cli.py save`), at session end (`SessionEnd` hook), and during context compaction (`PostCompact` hook). All use the same watermark-based policy.

**Sequence per curation cycle:**

1. Housekeeping reads the materializer's preload, curates the four pillars, and writes the updated `shared_mental_model.json` via `smm_cli.py save`.
2. The save signals the materializer via the agent's curation watermark (event count + agent_id).
3. Compaction reads the **oldest** still-valid watermark across all active agents and prunes events strictly before it, applying per-type retention:
   - **Status events**: compacted freely (counts preserved in session summaries)
   - **Customer inputs**: compacted freely (captured in Intent pillar)
   - **Decisions**: retained for 3 sessions, then compacted (live in Constraints pillar)
   - **Assumptions, questions**: retained for 5 sessions, then compacted (gives housekeeping time to curate into Risks)
   - **Concerns, debt**: retained while unresolved
   - **Retrospectives**: capped at 2 in the event log (archived in `retrospectives/` directory)
   - **Resolved items**: pruned (goals, concerns, debt with resolution events)
   - **Session_end events**: last 3 retained (needed for aging calculations)

**Multi-teammate graceful degradation.** If a teammate crashes before writing its curation watermark, the oldest still-valid watermark wins; compaction conservatively retains the extra events that the missing teammate had not yet curated. The next successful curation by any agent advances the oldest watermark and lets compaction catch up.

The SMM is the durable record. The event log is the working buffer that feeds it. Once curated, raw events have served their purpose.

**Size target:** The event log should stabilize at ~1-2 sessions of events (~50-200 entries).

### Conflict detection — dedicated coordination file

Real-time team conflict detection uses a lightweight `.coordination.json` file instead of scanning the event log:

```json
{
  "main": {
    "working_on": ["src/auth/roles.ts"],
    "updated": "2026-03-18T02:30:00+00:00"
  },
  "agent-2": {
    "working_on": ["src/auth/test_roles.ts"],
    "updated": "2026-03-18T02:31:00+00:00"
  }
}
```

- Each agent atomically updates its entry on file writes (command hook, cheap)
- Conflict check reads this one small file, not the event log
- Stale entries (updated > 30 minutes ago) are ignored — the agent likely exited
- Session end clears the agent's entry
- Flock-protected like events.jsonl

This is O(1) per check — read one small JSON file, check for `working_on` overlap. No event log scanning, no watermarks, no line counting.

---

## Design Principles

**Hooks leave trails, housekeeping curates.** Raw events are cheap and mechanical. Curation requires judgment and happens once per session. The SMM is a curated document, not a mechanical rendering.

**Events enter freely, the SMM is curated.** Hooks and agents create events automatically. But the curated SMM is deliberate — housekeeping decides what makes it into the four pillars. Compaction and aging handle cleanup so the event log doesn't grow unbounded.

**Less is more.** A 50-line SMM that every agent reads is worth more than a 500-line SMM that agents skim or ignore. The caps enforce curation.

**No taxonomy tax.** Agents don't care whether something is an "assumption" vs a "concern" vs a "question." They care about risk. One category, three severities.

**Ephemeral vs durable.** Coordination is ephemeral (clears each session). Intent, Constraints, and Wisdom are durable (persist across sessions). Risks are in between (persist but escalate and eventually force resolution).

**The SMM is not a history.** It's a snapshot of current state. The event log is the history. The SMM is the briefing derived from that history.

**Events.jsonl is transient — never the source of truth for stack config.** The event log is a working buffer that compaction may prune at any time. Anything that must survive (product/architecture/tooling decisions, conventions, language/runtime choices) belongs in `system_context.json`, which owns stack config and is the durable source of truth that survives sprints, plans, and event-log compaction. A `decision` event is fine for the in-flight signal, but if it codifies stack config, promote it into `system_context.json` so a future agent reading only the durable files doesn't lose it.

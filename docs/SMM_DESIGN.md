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

**Cap:** ~10 items. Oldest undelivered intents get flagged: "still wanted?"

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

**Leave:** Only when explicitly superseded by a new constraint that references the old one. Constraints don't age out — "use Postgres" doesn't become less true over time.

**Graduate:** A constraint stable for 10+ sessions and enforced by code/tests is part of the project's DNA. It can leave the SMM because the codebase embodies it.

**Cap:** ~20 items. Beyond this, some are too granular (move to code/linting) or have graduated.

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

**Cap:** ~10 items. More than 10 active risks is itself a 🔴 risk.

**Same-session rule:** Assumptions from plan reviews must be verified or dropped in the session they're created. They don't linger as "unverified" indefinitely.

---

### Coordination (separate from SMM)

Coordination is **not a pillar of the curated SMM**. It operates at a fundamentally different cadence — real-time per-tool-call updates vs once-per-session curation. It lives in `.coordination.json` (see M4 milestone).

```json
{
  "main": {"working_on": ["src/auth/roles.ts"], "updated": "2026-03-18T02:30:00+00:00"},
  "agent-2": {"working_on": ["src/auth/test_roles.ts"], "updated": "2026-03-18T02:31:00+00:00"}
}
```

**Enter:** Automatically — agent starts working on files.
**Leave:** Automatically — agent finishes or session ends. Ephemeral.
**Cap:** Bounded by active agents. Solo: 1 entry. Team: N entries.
**Conflict detection:** PreToolUse reads this file (O(1), no event log scan).

---

### Wisdom

Behavioral rules learned from experience. The institutional memory.

```markdown
## Wisdom
- Write tests before implementation — the TDD gate blocks otherwise
- Split large changes into separate commits
- Always record decisions when making architectural choices
- Run /simplify before stopping — don't skip it
- Don't amend pushed commits — creates divergent history
```

**Enter:** Deliberate promotion only:
- A retro "Try" is adopted and works → promoted to Wisdom
- A retro "Fix" recurs 3+ times → distilled into a rule
- Customer gives explicit guidance → captured

Each item is a **behavioral rule** phrased as "do X" or "don't do Y" with a brief "because Z."

**Leave:** Relevance decay. Not referenced for 10+ sessions → demoted. Or explicitly dropped by the team.

**Cap:** Hard cap of 10. Adding one at cap requires removing one. The constraint is the feature — only the most important lessons survive.

**Not a diary.** "Session 5 was hard" is not Wisdom. "Always run tests before claiming done" is Wisdom.

---

## Health Signals

Each pillar has a natural size that signals project health:

| Pillar | Healthy | Warning Signs |
|---|---|---|
| Intent | 2-5 items | 0 = no direction, 10+ = scope creep |
| Constraints | 5-15 items | 0 = no decisions made, 20+ = over-specified |
| Risks | 2-5 items | 0 = false confidence, 10+ = unmanaged risk |
| Wisdom | 3-7 items | 0 = not learning, 10 = cap reached, prune |

**Total SMM at healthy state: 12-30 items, ~300-600 tokens.**

Coordination health is tracked separately via `.coordination.json` (bounded by active agent count, not curated).

An agent reads the entire mental model in 2 seconds. The unhealthy states themselves become signals — if Risks hits 10, the SMM itself should flag: "Risk register at capacity — resolve items before adding more."

---

## Architecture

### Three layers

**1. Data trails (hooks, automatic)**

During a session, command hooks leave raw event trails in the event log. These are mechanical — no judgment, no LLM, just data capture:

- `customer_input` — the user's exact words
- `status` — what files are being touched
- `decision` (draft) — architectural choices as they happen
- `concern` — problems noticed by hooks or subagents
- `session_end` — session summary

Hooks don't curate the SMM. They just leave breadcrumbs.

**2. Curation (housekeeping skill, once per session)**

At session start, after the retrospective, housekeeping reads the raw event trail and curates the four pillars with LLM judgment:

- Distills `customer_input` events into Intent items (or not — "fix the typo" is a task, not an intent)
- Promotes draft decisions to Constraints (or drops them)
- Unifies assumptions, concerns, and debt into Risks with severity
- Promotes retro Try items to Wisdom (or drops them)
- Prunes graduated Constraints, resolved Risks, delivered Intents
- Enforces caps — flags when a pillar is unhealthy

A preload script prepares data for housekeeping — aggregates events, computes aging, identifies what's new since last curation. The judgment happens in the skill, not in Python.

Housekeeping writes the curated `SHARED_MENTAL_MODEL.md`. This replaces the current mechanical materializer for SMM generation.

**3. Nuggets (additionalContext, sparse)**

During the session, a few specific moments inject lightweight hints via `additionalContext`. Not deltas, not the full SMM — just useful context at useful moments:

- **UserPromptSubmit:** Summary of new concerns, decisions, and discoveries since last prompt
- **Conflict detected:** "Agent-2 is touching the same files"
- **Subagent completes:** "Quality review found issues" (the subagent's full response is already in context)

No PreToolUse delta injection. No watermarks. No per-tool-call event log reads. The agent has the full SMM from session start. Nuggets surface only what's new and actionable.

### What the materializer becomes

The current `materialize.py` shifts from rendering the SMM to preparing data for housekeeping:

- Aggregates events since last curation
- Computes aging for risks and constraints
- Identifies new customer_input, draft decisions, concerns
- Outputs structured data that housekeeping can reason about

The SMM.md file is written by housekeeping (with judgment), not by the materializer (mechanically).

---

## Injection Model

| When | What | Cost |
|---|---|---|
| Session start | Full SMM (written by housekeeping) | ~500 tokens, once |
| UserPromptSubmit | Nugget: new concerns, decisions, discoveries since last prompt | ~50-100 tokens |
| Conflict | Nugget: who's touching what | ~20 tokens |
| SubagentStart | Full SMM for new subagents/teammates | ~500 tokens |

**No PreToolUse delta.** The agent already has context. Signal events from subagents arrive via their response output. Coordination conflicts are detected by a lightweight command hook check (no SMM read needed).

---

## Progressive Curation (Agent Teams)

The SMM is a shared document at user level, visible to all agents across worktrees. Each agent's housekeeping run incorporates everyone's contributions:

```
Agent A starts → curates SMM from events → works, leaves event trails
Agent B starts → curates SMM (now includes A's decisions, concerns)
Agent C starts → curates SMM (includes A's + B's contributions)
Agent A restarts → curates SMM (includes B's + C's contributions)
```

The event log is the shared coordination bus (append-only, flock-protected). The SMM.md is the latest curated snapshot. Every housekeeping run makes it richer because it has more events to work with.

### Merge, don't replace

Housekeeping should **update the existing SMM**, not rewrite from scratch. This means:
- Read the current SMM.md first
- Incorporate new events since the last curation
- Add new Intents, Constraints, Risks from other agents' trails
- Mark items delivered/resolved based on new evidence
- Write the updated SMM back

This handles concurrent curation gracefully — if Agent A and Agent B both curate near-simultaneously, each reads the current state and merges their events. Even if one write is lost to a race, the next curation picks up the missed events from the log.

Flock protection on SMM.md writes (like events.jsonl) provides additional safety.

### What each agent contributes

| Agent Activity | Event Trail | Pillar Affected |
|---|---|---|
| Customer speaks | `customer_input` | Intent (housekeeping distills) |
| Architectural choice | `decision` (draft) | Constraints (housekeeping promotes) |
| Problem noticed | `concern` | Risks (housekeeping unifies) |
| Uncertainty stated | `assumption` | Risks (housekeeping unifies) |
| Debt acknowledged | `debt` | Risks (housekeeping unifies) |
| File work | `status` + working_on | Coordination (automatic) |
| Retro produces Try | `retrospective` | Wisdom (housekeeping promotes) |
| Session ends | `session_end` | Aging calculations |

Every agent leaves the same kinds of trails. Housekeeping doesn't care which agent created the event — it curates all of them into one shared model.

---

## Mid-Session Nuggets

Three moments, minimal content. No other hooks need nuggets.

### Prompt nugget (UserPromptSubmit)

Fires on each user prompt. Surfaces new signal events (concerns, decisions, discoveries) since the last prompt:

```
New since last prompt:
- [concern] Test failures detected: 1 failed (unittest)
- [decision] Fix retrospective preload overflow, move prompt nugget...
```

~50-100 tokens. Only new items since last injection. If nothing is new, no nugget.

### Conflict nugget (teams only)

Another agent touched your files:

```
⚡ Conflict: Agent-2 started working on src/auth/roles.ts
```

~20 tokens. Fires from coordination check, not from an SMM read.

### SubagentStart

New subagent/teammate gets the full curated SMM (~500 tokens).

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
    "recurring_fixes": ["Navigator silent (4 retros)"],
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
| `decisions` | Constraints | "Promote this draft to a constraint?" |
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

### Watermarks — eliminated for delta, repurposed for compaction

No PreToolUse delta means no per-agent watermarks for injection. The watermark concept survives only as a **curation watermark** — a single marker written by housekeeping: "I curated up to event N." The preload uses this to identify new events since last curation.

For teams, each agent's housekeeping writes its own curation watermark. Compaction uses the oldest watermark as the safe truncation point (everyone's curated past it).

Subagent hex-ID watermarks (`.watermark-abf63d10...`) are eliminated entirely.

### Event log compaction — housekeeping compacts after curation

The event log is a staging buffer, not an archive. Housekeeping compacts as part of curation:

1. Housekeeping curates events into the SMM
2. Writes its curation watermark (event count or timestamp)
3. For solo: compacts events before the watermark, retaining only:
   - Last 3 `session_end` events (for aging calculations)
   - Any events referenced by current SMM items (traceability)
4. For teams: compacts only events before the **oldest** agent's curation watermark

The SMM is the durable record. The event log is the working buffer that feeds it. Once curated, raw events have served their purpose.

**Size target:** The event log should stabilize at ~1-2 sessions of events (~50-200 entries), not grow indefinitely. The current 1000+ events would compact to ~100.

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

**Items enter deliberately, leave automatically.** The current SMM's failure mode is automatic entry (hooks create events) with no exit (nothing resolves them). This design inverts it — housekeeping is the deliberate gate.

**Less is more.** A 50-line SMM that every agent reads is worth more than a 500-line SMM that agents skim or ignore. The caps enforce curation.

**No taxonomy tax.** Agents don't care whether something is an "assumption" vs a "concern" vs a "question." They care about risk. One category, three severities.

**Ephemeral vs durable.** Coordination is ephemeral (clears each session). Intent, Constraints, and Wisdom are durable (persist across sessions). Risks are in between (persist but escalate and eventually force resolution).

**The SMM is not a history.** It's a snapshot of current state. The event log is the history. The SMM is the briefing derived from that history.

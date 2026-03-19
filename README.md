# xp-agents: Extreme Programming for Claude Code Agent Teams

A Claude Code plugin that makes your agents — solo or in teams — write better software through XP practices. Command hooks enforce deterministic rules. Plugin subagents provide judgment-based guidance. A broadcast event log keeps every agent aligned. Zero config. Install and go.

## TL;DR

**What it does:** Command hooks fire automatically on tool calls — blocking conflicts, enforcing TDD, running linters, and tracking status. Plugin subagents provide strategic guidance: a plan reviewer validates plans and a retrospective analyst surfaces cross-session learning. Inline skills handle goal collection, question triage, quality review, and SMM curation. Everything is broadcast through a shared event log visible to every agent.

**How it works:** Deterministic enforcement (tests, lint, conflicts, security) lives in command hooks — they fire every time. Judgment work (plan analysis, retrospectives, quality review) lives in plugin subagents and inline skills, triggered by command hook nudges or stop gates.

**Who it's for:** Anyone using Claude Code — solo agents benefit from the quality review, retrospectives, and TDD enforcement. Agent Teams benefit from the broadcast coordination layer that replaces point-to-point mailboxes.

---

## Install

From within a Claude Code session:

```bash
# Add the marketplace
/plugin marketplace add paulingalls/xp-agents

# Install (select "User" scope for Agent Teams / worktree support)
/plugin install xp-agents@xp-agents
```

Or from your terminal (skips the interactive scope picker):

```bash
# Add the marketplace
claude plugin marketplace add paulingalls/xp-agents

# Install at user scope
claude plugin install xp-agents@xp-agents --scope user
```

For local development, use `--plugin-dir` (session-only, not persisted):

```bash
claude --plugin-dir /path/to/xp-agents/plugins/xp-agents
```

**Requirements:** Python 3.10+ on PATH. macOS or Linux. Zero external packages.

**For teams:** Add this to your project's `.claude/settings.json` so teammates can discover the plugin:

```json
{
  "extraKnownMarketplaces": {
    "xp-agents": {
      "source": { "source": "github", "repo": "paulingalls/xp-agents" }
    }
  }
}
```

Each person installs at user scope. The marketplace entry is just discovery.

---

## What Happens When You Use It

**First session:**

```
$ claude
> Starting session...

[xp-agents] Initializing SMM for project... ✓
[xp-agents] Kickoff required — run /xp-kickoff

> /xp-kickoff

[xp-agents] First session — no retrospective data.
[xp-agents] What are your goals for this session?

> "Build a REST API for user management with auth and role-based access."

[xp-agents] Goal recorded.
[xp-agents] Running housekeeping — curating Shared Mental Model...
[xp-agents] SMM curated. Behavioral guide loaded. Ready to work.
```

From here, the system takes over:
- **Every user prompt** — prompt nuggets inject new signal events (concerns, decisions, discoveries) since last prompt (~50-100 tokens)
- **Before every write** — conflict detection via `.coordination.json`, TDD order check, plan review gate via marker file
- **Before every push** — security review gate blocks until review is done
- **After every write** — status auto-updated, linter runs
- **At stop** — `/simplify` required for significant changes (≥3 code files), then `/xp-quality-review` checks courage + drift + debt, TDD gate blocks if tests failing
- **Technical debt** — tracked, aged across sessions, surfaced during quality review when touching affected files

**Second session:**

```
$ claude
> Starting session...

[xp-agents] Kickoff required — run /xp-kickoff

> /xp-kickoff

[xp-agents] Found 47 events from previous session. Running retrospective...

## What We Learned Last Session

### Keep
- Early concern-raising: pagination concern changed the API design
  before any consumer code was written.

### Fix
- Avatar question still unresolved after 1 session.
  Resolve it this session or drop it from scope.

### Try
- Before reporting done, list what's tested and what isn't.

[xp-agents] Any goals for this session?

> "Add role-based access control"

[xp-agents] Goal recorded. Running housekeeping...
[xp-agents] SMM curated:
  Intent: 2 items | Constraints: 5 items | Risks: 3 items | Wisdom: 2 items
[xp-agents] Ready to work.
```

Every session starts smarter than the last one ended. The kickoff sequences retrospective → goals → housekeeping, curating the four-pillar SMM with aging debt, undelivered intents, and lessons learned.

---

## How It Works

### Hooks Enforce, Subagents Advise

xp-agents uses two mechanisms: **command hooks** for deterministic enforcement (they fire every time, guaranteed) and **plugin subagents + inline skills** for judgment-based guidance (full tool access, triggered by hook nudges or stop gates).

| Hook Event | What Fires | XP Practice |
|---|---|---|
| **UserPromptSubmit** | Prompt nuggets (new signal events since last prompt), customer input logging, kickoff gate | Communication, On-Site Customer |
| **PreToolUse** (Write/Edit) | `working_on` conflict blocking (via `.coordination.json`), TDD order check, plan review gate (`.plan-awaiting-review` marker) | TDD, Planning Game |
| **PreToolUse** (Bash) | Push security gate, file-modification conflict heuristic (advisory) | Coding Standards |
| **PostToolUse** (Write/Edit) | Auto status/working_on, conflict detection, lint check | Standup, Coding Standards |
| **PostToolUse** (Bash) | Git commit size check, test result parsing | Small Releases, CI |
| **SubagentStop** (Plan) | Write `.plan-awaiting-review` marker (PreToolUse nudges review before writes) | Planning Game, Simple Design |
| **SessionStart** | GUPP + skills injection, retrospective data prep, `.needs-kickoff` marker | Retrospective, On-Site Customer |
| **SessionEnd** | Session summary: unresolved items, working state, missing status flag | Honesty |
| **SubagentStart** | Tiered context injection (Explore: Intent+Constraints, others: full SMM + behavioral guide) | Collective Code Ownership |
| **PostToolUse** (Skill) | Security review tracker when `/security-review` completes; behavioral guide injection when `/xp-housekeeping` completes | Coding Standards, Communication |
| **Stop** | Block if tests failing (`tdd_stop_gate.py`), block if quality review pending (`quality_review_gate.py`), block if ≥3 code files changed and `/simplify` not run | TDD, Refactoring |
| **Notification** | Desktop notification for 🔴 blocking questions | On-Site Customer |
| **PreCompact** | Back up SMM state | Sustainable Pace |

The retrospective analyst and plan reviewer are plugin subagents with full tool access. Quality review, goal collection, question triage, and housekeeping run as inline skills in the main agent. Command hooks inject `additionalContext` nudging the main agent to invoke them at the right moment. The plan reviewer is triggered via a marker file: SubagentStop writes `.plan-awaiting-review`, then PreToolUse detects it and nudges the agent to invoke the reviewer before writes. The plan reviewer's preload script clears the marker. SubagentStart uses tiered context injection — Explore subagents get only Intent+Constraints (lightweight), while all others get the full curated SMM + behavioral guide.

### The Shared Mental Model

Instead of point-to-point mailboxes, xp-agents introduces a broadcast event log visible to every agent — the main agent, all subagents, and all Agent Team teammates.

```
~/.claude/xp-agents/{project-id}/smm/
├── events.jsonl              ← append-only log
├── SHARED_MENTAL_MODEL.md    ← curated four-pillar view, written by housekeeping
├── .curation-watermark       ← last-curated event position
├── .coordination.json        ← per-agent working_on for O(1) conflict detection
├── .plan-awaiting-review     ← plan review gate marker
├── events.lock               ← flock for atomic appends
└── retrospectives/           ← Keep/Fix/Try session artifacts
```

The SMM lives at user level (`~/.claude/`), not in the project's `.claude/`. This means Agent Team teammates in different git worktrees all share the same event log.

The curated view uses a four-pillar model, written by housekeeping (LLM judgment):
- **Intent** — project goals and active customer intents
- **Constraints** — confirmed decisions, conventions, and architectural boundaries
- **Risks** — concerns, blocking questions, unverified assumptions, technical debt (with severity)
- **Wisdom** — lessons learned, retrospective insights, behavioral experiments

Context reaches agents through lightweight **prompt nuggets** at each user prompt (~50-100 tokens of new signal events) and tiered context injection at subagent spawn (Explore gets Intent+Constraints only, others get full SMM + behavioral guide). The main agent gets the SMM during housekeeping (reads the file directly) and the behavioral guide via PostToolUse:Skill hook.

Events are semantically typed — each carries different synchronization semantics:

| Event Type | Purpose | Generated By |
|---|---|---|
| `goal` | Project north star — what we're building and why | Skill (xp-goal-collection) + customer |
| `customer_input` | The user's exact words | Command hook (automatic) |
| `customer_intent` | Distilled customer request — tracked until delivered | Skill (xp-question-triage) |
| `status` | What each agent is doing + `working_on` files | Command hook (automatic) + agent |
| `decision` | Architectural choices | Agent + subagent (plan reviewer) |
| `convention` | Team standards | Agent |
| `concern` | Problems needing attention | Skill (quality review) + agent |
| `discovery` | Unexpected findings | Agent |
| `question` | Customer input needed (🔴 blocking / 🟡 assumed) | Agent |
| `assumption` | Stated beliefs — escalates if contradicted | Agent + subagent (plan reviewer) |
| `debt` | Acknowledged tradeoff — ages and escalates across sessions | Skill (quality review) + subagent (retrospective) |
| `session_end` | Session summary with unresolved items | Command hook (automatic) |
| `retrospective` | Keep/Fix/Try analysis + session stats | Subagent (retrospective) |

### The Automated Retrospective

At session start, if there's unanalyzed data from a previous session, the command hook prepares retrospective data and the kickoff orchestrator invokes the retrospective subagent. It uses all five XP values as analytical lenses:

- **Keep**: What worked — grounded in specific events from the log
- **Fix**: What needs improvement — Honesty: were status events truthful? Courage: were concerns raised? Simplicity: was anything over-engineered? Communication: were decisions broadcast? Respect: were conventions followed?
- **Try**: Behavioral experiments for this session — informed by Fix items

The retrospective also analyzes **session stats** for plugin health: concern resolution rate, decision recording rate, security review coverage.

The retrospective runs at session *start*, not session end — resilient to force-quit, crash, Ctrl+C. The event log is append-only and durable.

| Session | What the Team Knows |
|---|---|
| 1st | Nothing. Cold start. |
| 2nd | Keep/Fix/Try from session 1. |
| 3rd | Cross-session trends emerge. |
| 5th | Tried experiments validated or dropped. |
| 10th | Genuine institutional memory. |

### Agent Teams

xp-agents is designed for Agent Teams. Because hooks are global and the SMM is stored at user level, every teammate in every worktree automatically gets:

- Prompt nuggets at each user prompt and tiered context at subagent spawn
- `working_on` conflict detection across teammates
- Decisions visible to every other teammate
- A team-wide retrospective at next session start

Native Agent Teams provide task distribution. xp-agents adds the coordination layer: shared context, conflict prevention, quality enforcement, and institutional memory.

---

## Configuration

xp-agents works out of the box with zero configuration. It is opinionated — all enforcement is always on. If a gate is annoying, the solution is to fix the gate, not make it optional.

---

## Why This Exists

Multi-agent systems fail for reasons that have nothing to do with individual capability. The research is consistent:

**Coordination costs scale exponentially.** Galileo Labs (Feb 2026) found that 4 agents create 6 potential failure points, 10 agents create 45. Seven common failure modes — all rooted in insufficient coordination architecture.

**Group dynamics apply to AI teams too.** Bentes (Feb 2026) maps distributed systems failures onto multi-agent AI: the Anti-Volunteer's Dilemma (agents act simultaneously because no one can see another is handling it), Split-Brain Inconsistency (agents on different versions of reality after compaction), the "Yes, And" Hallucination Cascade (agents building on each other's errors).

**Shared mental models are the solution.** Lou et al. (USC/ASU, Mar 2026) established shared mental models as the primary alignment mechanism for human-AI teaming. A Nature study (Feb 2026) found structured coordination protocols essential precisely where LLMs are weakest.

**XP was designed for this.** At "The Future of Software Development" summit (Feb 2026), a major theme was the resurgence of XP practices in the AI era. XP was built for high uncertainty, rapid change, and continuous feedback — exactly what AI agents create.

Claude Code Agent Teams communicate via point-to-point mailboxes and a shared task list. This handles task distribution but not coordination: no shared decision context, no conflict detection, no code review enforcement, no retrospective learning.

---

## Honesty: The Foundational Value

XP has five values: Communication, Feedback, Simplicity, Courage, and Respect. Honesty is the foundation that makes all five work.

A standup where agents report "everything is fine" when tests are failing is worse than no standup — it creates false confidence. A retrospective where no one raises problems produces comfortable fiction. The difference between honest and dishonest teams isn't incremental. It's multiplicative.

| XP Value | Without Honesty | With Honesty |
|---|---|---|
| **Communication** | Agent reports "auth complete." Integration fails — 3 tests red. **Cost: 1 wasted session.** | Agent reports "auth 70% — token refresh not done, 3 tests failing." Other agent pivots. **Cost: zero.** |
| **Feedback** | Reviewer writes "LGTM" on `catch(e) {}`. Pattern spreads. DB goes down — no logs. **Cost: 3 hours + failed demo.** | Reviewer writes a `concern`. Fixed in 5 minutes. |
| **Simplicity** | Agent builds `AbstractEndpointFactory` for one endpoint. **Cost: 200 lines of dead abstraction.** | Agent writes a plain function. Notes "will extract if we add a second." |
| **Courage** | Agent notices single-tenant schema, stays quiet. Three sessions later: 14 files, 23 broken tests. | Agent raises a `concern`. Fixed in 30 minutes. |

xp-agents enforces honesty through hooks, not aspiration:

- **Quality review skill** — post-simplify courage check: were recommendations skipped? Drift management: do code changes contradict recorded decisions?
- **Retrospective subagent** — analyzes honesty patterns: were status events truthful? Were concerns raised or did everyone agree too easily?
- **Session end hook** — flags when the agent didn't write a final status summary
- **Conflict detector** — catches convention violations and unacknowledged contradictions
- **Behavioral guide** — XP behavioral rules injected after housekeeping for judgment calls hooks can't enforce

---

## Extending

Any Claude Code subagent or skill works alongside xp-agents without configuration. Because hooks are global, every subagent automatically gets SMM context and output evaluation via the existing command hooks.

Build additional reviewers — security, accessibility, domain-specific quality gates — as plugin subagents or command hooks and publish them to the marketplace.

---

## Technical Details

### XP Practices → Enforcement Mechanism

| Practice | Enforcement | Mechanism |
|---|---|---|
| **TDD** | Deterministic: Stop blocks if tests fail (`tdd_stop_gate.py`). TDD order check in PreToolUse. unittest/pytest/jest/go test detection. | `tdd_stop_gate.py`, `pre_tool_write.py`, `bash_post_tool.py` |
| **Pair Programming** | Skill: quality review after simplify (courage + drift + debt awareness). | `/xp-quality-review` |
| **Planning Game** | Subagent: plan reviewer checks size, TDD ordering, decision conflicts. Nudge via `.plan-awaiting-review` marker. Skills: goal collection + question triage. | `xp-plan-reviewer`, `/xp-goal-collection`, `/xp-question-triage` |
| **Small Releases** | Deterministic: commit size check. | `bash_post_tool.py` |
| **Coding Standards** | Deterministic: lint after every write, convention tracking, conflict detection, security review before push. | `lint_check.py`, `post_tool_use.py`, `pre_tool_write.py`, `pre_tool_bash.py` |
| **Continuous Integration** | Deterministic: test results parsed (success + failure). Stop blocks on failure. | `bash_post_tool.py`, `bash_failure.py`, `tdd_stop_gate.py` |
| **Refactoring** | Skill + gate: `/simplify` runs at loop end (≥3 code files), quality review checks skipped recommendations. | `/xp-quality-review`, `simplify_gate.py` |
| **Simple Design** | Subagent: plan reviewer flags oversized plans. `/simplify` checks efficiency. | `xp-plan-reviewer`, `simplify_gate.py` |
| **Collective Code Ownership** | Deterministic: prompt nuggets at each prompt, tiered context at subagent spawn (Explore: Intent+Constraints, others: full SMM + behavioral guide). Global hooks. | `prompt_nugget.py`, `subagent_start.py` |
| **On-Site Customer** | Deterministic: prompts logged, notifications sent. Skills: goal collection + question triage. | `user_prompt_log.py`, `/xp-goal-collection`, `/xp-question-triage` |
| **Retrospective** | Subagent: Keep/Fix/Try at session start with XP values as analytical lenses. | `xp-retrospective` |

### Token Cost Model

| Source | Per-occurrence | Frequency | Mitigation |
|---|---|---|---|
| Prompt nugget (UserPromptSubmit) | 50-100 tokens | Every user prompt | Watermark-based, only new signal events |
| SessionStart + kickoff | 2,000-5,000 tokens | Once per session | One-time cost (retro + goals + housekeeping) |
| Retrospective subagent | 10,000-20,000 tokens | Once per session | Only when unanalyzed events exist |
| `/simplify` at Stop | 30,000-60,000 tokens | Once per loop with ≥3 code files | Threshold skips small changes |
| `/xp-quality-review` at Stop | 5,000-10,000 tokens | Once per loop after simplify | Focused: courage + drift + debt only |

### Debt Aging

Technical debt events age across sessions. The materializer counts `session_end` events after the debt timestamp:

- **0-3 sessions**: rendered normally
- **4-6 sessions**: rendered with ⚠️, retrospective flags in Fix items
- **7+ sessions**: rendered with 🔴, retrospective escalates urgency

Repayment pressure comes from two sources: quality review surfaces debt when touching affected files, retrospective escalates aging debt in Fix items.

### Architecture: Why Subagents Instead of Agent Hooks

Agent hooks (`type: "agent"` in hooks.json) are broken platform-wide — they crash with "Messages are required for agent hooks. This is a bug." on all events tested (PostToolUse, UserPromptSubmit). This is a Claude Code platform issue, not fixable from the plugin side.

Plugin subagents (`agents/` directory) have full tool access (Bash, Read, Write, Edit, AskUserQuestion), return their full conversational response to the main agent, support background mode, and can preload skills. Each subagent is wrapped by a forked skill with `!` preloads for deterministic SMM state injection — the `allowed-tools` field (e.g., `Bash(*/skills/*/scripts/*)`) pre-approves preload script permissions. Command hooks trigger subagents via `additionalContext` nudge (strong encouragement) or exit 2 block (deterministic, like the `/simplify` gate).

---

## Research Sources

| Source | Title | Date |
|---|---|---|
| Galileo Labs (Pratik Bhavsar) | "Why Do Multi-Agent Systems Fail Even When Agents Work Perfectly in Isolation?" | Feb 2026 |
| Daniel Bentes | "Five AI Agents Walk Into a Group Chat" | Feb 2026 |
| Lou, Lu, Raghu, Zhang (USC/ASU) | "Visioning Human–Agentic AI Teaming" | Mar 2026 |
| Zhang et al. (Nature) | "LLM tools as catalysts for collective cognition" | Feb 2026 |
| Gergely Orosz (Pragmatic Engineer) | "The Future of Software Engineering with AI: Six Predictions" | Feb 2026 |
| Anthropic | Claude Code Agent Teams documentation | 2026 |
| Carraro, Furlan, Netland | "How shared mental models drive proactive problem-solving" (Human Relations) | 2025 |

---

## Project Status

See [MILESTONES.md](docs/MILESTONES.md) for the development roadmap.
See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for technical specifications.
See [RESEARCH.md](docs/RESEARCH.md) for competitive landscape and lessons learned.

## License

MIT

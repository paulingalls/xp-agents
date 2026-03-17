# xp-agents: Extreme Programming for Claude Code Agent Teams

A Claude Code plugin that makes your agents — solo or in teams — write better software through XP practices. Command hooks enforce deterministic rules. Plugin subagents provide judgment-based guidance. A broadcast event log keeps every agent aligned. Zero config. Install and go.

## TL;DR

**What it does:** Command hooks fire automatically on every tool call — injecting project context, blocking conflicts, enforcing TDD, running linters, and tracking status. Plugin subagents provide strategic guidance: a navigator reviews code changes, a quality reviewer flags issues, and a retrospective analyst surfaces cross-session learning. Inline skills handle goal collection and question triage. Everything is broadcast through a shared event log visible to every agent.

**How it works:** Deterministic enforcement (tests, lint, conflicts, security) lives in command hooks — they fire every time. Judgment work (code review, plan analysis, retrospectives) lives in plugin subagents with full tool access, triggered by command hook nudges or blocks.

**Who it's for:** Anyone using Claude Code — solo agents benefit from the code review, navigation, and retrospectives. Agent Teams benefit from the broadcast coordination layer that replaces point-to-point mailboxes.

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
[xp-agents] First session — what's the goal of this project?
[xp-agents] What are you trying to build and why?

> "Build a REST API for user management with auth and role-based access."

[xp-agents] Goal recorded. GUPP: Act on pending work immediately.
```

From here, the system takes over:
- **Before every write** — SMM delta injected (two-tier: Active Context for quick checks, full SMM for writes), navigator subagent nudged for strategic guidance
- **After every write** — status auto-updated, quality reviewer subagent nudged (runs in background), linter runs
- **Every user prompt** — logged and distilled into trackable customer intent
- **Every conflict** — detected and surfaced automatically
- **Technical debt** — tracked, aged across sessions, escalated when ignored
- **Tests must pass** before the agent can stop

**Second session:**

```
$ claude
> Starting session...

[xp-agents] Found 47 events from previous session. Running retrospective...

## What We Learned Last Session

### Keep
- Early concern-raising: pagination concern changed the API design
  before any consumer code was written.

### Fix
- Avatar question still unresolved after 1 session.
  Resolve it this session or drop it from scope.
- Navigator produced 0 guidance despite 12 file writes — check
  if self-filtering is too aggressive.

### Try
- Before reporting done, list what's tested and what isn't.

## Customer Intent (undelivered)
- 📋 Add role-based access control to endpoints
- 📋 Set up token refresh flow

## Technical Debt
- Auth middleware uses placeholder secret — 2 sessions old
```

Every session starts smarter than the last one ended. The retrospective includes plugin health stats, undelivered customer requests, and aging technical debt — not just Keep/Fix/Try.

---

## How It Works

### Hooks Enforce, Subagents Advise

xp-agents uses two mechanisms: **command hooks** for deterministic enforcement (they fire every time, guaranteed) and **plugin subagents** for judgment-based guidance (full tool access, triggered by hook nudges). Command hooks handle the "must happen" — SMM injection, conflict detection, TDD gating, linting, status tracking. Subagents handle the "should happen" — code review, plan analysis, retrospectives, goal collection.

| Hook Event | What Fires | XP Practice |
|---|---|---|
| **PreToolUse** (Write/Edit) | SMM delta injection, `working_on` conflict blocking, TDD order check, navigator subagent nudge | Communication, Pair Programming, TDD |
| **PostToolUse** (Write/Edit) | Auto status/working_on, conflict detection, lint check, quality reviewer subagent nudge | Standup, Coding Standards, Courage, Simplicity |
| **PostToolUse** (Bash) | Git commit size check, test result parsing | Small Releases, CI |
| **SubagentStop** (Plan) | Block until plan reviewer subagent invoked | Planning Game, Simple Design |
| **SessionStart** | GUPP + skills injection, retrospective data prep, `.needs-session-review` marker | Retrospective, On-Site Customer |
| **SessionEnd** | Session summary: unresolved items, working state, missing status flag | Honesty |
| **UserPromptSubmit** | Log user prompt as `customer_input` event | On-Site Customer |
| **SubagentStart** | Full SMM injection into new subagents | Collective Code Ownership |
| **SubagentStop** | Subagent reviewer nudge for output quality and alignment | Code Review |
| **PostToolUse** (Skill) | Security review tracker when `/security-review` completes; SMM + behavioral guide injection when `/xp-session-review` completes | Coding Standards, Communication |
| **Stop** | Block if tests failing (`tdd_stop_gate.py`), block if files changed and `/simplify` not run | TDD, Refactoring |
| **TaskCompleted** | Navigator gate (block until `pair_guidance` event exists) + quality reviewer nudge | Pair Programming |
| **Notification** | Desktop notification for 🔴 blocking questions | On-Site Customer |
| **PreCompact** | Back up SMM state | Sustainable Pace |

The navigator, quality reviewer, retrospective analyst, plan reviewer, and subagent reviewer are plugin subagents with full tool access. Goal collection and question triage run as inline skills. Command hooks inject `additionalContext` nudging the main agent to invoke them at the right moment. The plan reviewer uses exit-2 blocking (like the simplify gate) for deterministic triggering.

### The Shared Mental Model

Instead of point-to-point mailboxes, xp-agents introduces a broadcast event log visible to every agent — the main agent, all subagents, and all Agent Team teammates.

```
~/.claude/xp-agents/{project-id}/smm/
├── events.jsonl              ← append-only log
├── SHARED_MENTAL_MODEL.md    ← materialized view
├── .watermark-{agent-id}     ← per-agent read position
├── events.lock               ← flock for atomic appends
└── retrospectives/           ← Keep/Fix/Try session artifacts
```

The SMM lives at user level (`~/.claude/`), not in the project's `.claude/`. This means Agent Team teammates in different git worktrees all share the same event log.

The materialized view has two tiers: **Active Context** (goals, conflicts, blocking questions, undelivered customer intent, concerns, drift signals, agent status, navigator guidance) and **Reference** (decisions, conventions, resolved questions, assumptions, technical debt, discoveries). Non-write tools get Active Context only — cheap and focused. Write tools get the full SMM.

Events are semantically typed — each carries different synchronization semantics:

| Event Type | Purpose | Generated By |
|---|---|---|
| `goal` | Project north star — what we're building and why | Skill (xp-goal-collection) + customer |
| `customer_input` | The user's exact words | Command hook (automatic) |
| `customer_intent` | Distilled customer request — tracked until delivered | Skill (xp-question-triage) |
| `status` | What each agent is doing + `working_on` files | Command hook (automatic) + agent |
| `decision` | Architectural choices | Agent + subagent (plan reviewer) |
| `convention` | Team standards | Agent |
| `concern` | Problems needing attention | Subagent (quality reviewer) + agent |
| `discovery` | Unexpected findings | Agent |
| `question` | Customer input needed (🔴 blocking / 🟡 assumed) | Agent |
| `assumption` | Stated beliefs — escalates if contradicted | Agent + subagent (plan reviewer) |
| `debt` | Acknowledged tradeoff — ages and escalates across sessions | Subagent (quality reviewer + retrospective) |
| `pair_guidance` | Navigator strategic direction | Skill (xp-navigator) via PreToolUse nudge + TaskCompleted gate |
| `session_end` | Session summary with unresolved items | Command hook (automatic) |
| `retrospective` | Keep/Fix/Try analysis + session stats | Subagent (retrospective) |

### The Automated Retrospective

At session start, if there's unanalyzed data from a previous session, the command hook prepares retrospective data and nudges the main agent to invoke the retrospective subagent. It uses all five XP values as analytical lenses:

- **Keep**: What worked — grounded in specific events from the log
- **Fix**: What needs improvement — Honesty: were status events truthful? Courage: were concerns raised? Simplicity: was anything over-engineered? Communication: were decisions broadcast? Respect: were conventions followed?
- **Try**: Behavioral experiments for this session — informed by Fix items

The retrospective also analyzes **session stats** for plugin health: navigator effectiveness (guidance count vs. file writes), concern resolution rate, decision recording rate. If the quality reviewer hasn't flagged anything in a session with 20 file writes, the retrospective asks why.

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

- SMM delta injection before every tool call
- Quality review and navigation on every code change
- `working_on` conflict detection across teammates
- Decisions visible to every other teammate
- A team-wide retrospective at next session start

Native Agent Teams provide task distribution. xp-agents adds the coordination layer: shared context, conflict prevention, quality enforcement, and institutional memory.

---

## Configuration

xp-agents works out of the box with zero configuration. One setting is available in `settings.json`:

```json
{
  "enforcement": "strict"
}
```

- **`strict`** (default) — TDD blocks on test failure, working_on conflicts block, plan review blocks until invoked, security review required before push.
- **`advisory`** — same hooks fire, same events recorded, same subagents nudged — but nothing blocks. All blocks become warnings. The system still tracks everything; it just doesn't stop you.

The goal is to reach a point where `strict` and `advisory` produce the same behavior — because tests always pass, agents never overlap, and decisions are consistent. When that happens, you're ready for autonomous teams.

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

- **Quality reviewer subagent** — detects empty catch blocks, premature "done" signals, missing error handling
- **Retrospective subagent** — analyzes honesty patterns: were status events truthful? Were concerns raised or did everyone agree too easily?
- **Session end hook** — flags when the agent didn't write a final status summary
- **Conflict detector** — catches convention violations and unacknowledged contradictions
- **Behavioral guide** — XP behavioral rules injected at session start for judgment calls hooks can't enforce

---

## Extending

Any Claude Code subagent or skill works alongside xp-agents without configuration. Because hooks are global, every subagent automatically gets SMM context and output evaluation via the existing command hooks.

Build additional reviewers — security, accessibility, domain-specific quality gates — as plugin subagents or command hooks and publish them to the marketplace.

---

## Technical Details

### XP Practices → Enforcement Mechanism

| Practice | Enforcement | Mechanism |
|---|---|---|
| **TDD** | Deterministic: Stop blocks if tests fail (`tdd_stop_gate.py`). Navigator flags implementation-before-tests. unittest/pytest/jest/go test detection. | `tdd_stop_gate.py`, `pre_tool_use.py`, `bash_post_tool.py` |
| **Pair Programming** | Subagent: navigator before every significant write, quality reviewer after. | `xp-navigator`, `xp-quality-reviewer` |
| **Planning Game** | Subagent: plan reviewer checks size, TDD ordering, decision conflicts. Block via exit 2. Skills: goal collection + question triage replace customer proxy. | `xp-plan-reviewer`, `/xp-goal-collection`, `/xp-question-triage` |
| **Small Releases** | Deterministic: commit size check. | `bash_post_tool.py` |
| **Coding Standards** | Deterministic: lint after every write, convention tracking, conflict detection, security review before push. | `lint_check.py`, `post_tool_use.py`, `pre_tool_use.py` |
| **Continuous Integration** | Deterministic: test results parsed (success + failure). Stop blocks on failure. | `bash_post_tool.py`, `bash_failure.py`, `tdd_stop_gate.py` |
| **Refactoring** | Subagent + gate: quality reviewer flags complexity, `/simplify` runs at loop end. | `xp-quality-reviewer`, `simplify_gate.py` |
| **Simple Design** | Subagent: quality reviewer flags over-engineering, plan reviewer flags oversized plans. | `xp-quality-reviewer`, `xp-plan-reviewer` |
| **Collective Code Ownership** | Deterministic: SMM injected into all agents automatically. Global hooks. | `pre_tool_use.py`, `subagent_start.py` |
| **On-Site Customer** | Deterministic: prompts logged, notifications sent. Skills: goal collection + question triage. | `user_prompt_log.py`, `/xp-goal-collection`, `/xp-question-triage` |
| **Retrospective** | Subagent: Keep/Fix/Try at session start with XP values as analytical lenses. | `xp-retrospective` |

### Token Cost Model

| Source | Per-occurrence | Frequency | Mitigation |
|---|---|---|---|
| PreToolUse delta (full) | 50-500 tokens | Every Write/Edit/Commit | Watermarks prevent duplicates |
| PreToolUse delta (minimal) | 10-50 tokens | Every Bash/Read/Grep | 🔴 questions only |
| Navigator subagent | 5,000-10,000 tokens | Every Write/Edit (if invoked) | Self-filters trivial changes |
| Quality reviewer subagent | 5,000-10,000 tokens | Every Write/Edit (background) | Async, no latency cost |
| SessionStart full SMM | 2,000-5,000 tokens | Once per session | One-time cost |
| Retrospective subagent | 10,000-20,000 tokens | Once per session | Only when unanalyzed events exist |
| `/simplify` at Stop | 30,000-60,000 tokens | Once per loop with file changes | Gate skips no-op loops |

### Debt Aging

Technical debt events age across sessions. The materializer counts `session_end` events after the debt timestamp:

- **0-3 sessions**: rendered normally
- **4-6 sessions**: rendered with ⚠️, retrospective flags in Fix items
- **7+ sessions**: rendered with 🔴, retrospective escalates urgency

Repayment pressure comes from three sources: navigator nudges when modifying files with debt, quality reviewer writes concern if debt not addressed, retrospective escalates aging debt in Fix items.

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

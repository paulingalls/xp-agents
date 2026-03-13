# xp-agents: Extreme Programming for Claude Code Agent Teams

A Claude Code plugin that makes your agents — solo or in teams — write better software through XP practices enforced by hooks. Broadcast event log. Automated code review, navigation, retrospectives, and conflict detection. Zero config. Install and go.

## TL;DR

**What it does:** Hooks fire automatically on every tool call. Before every write, a navigator checks your direction. After every write, a quality reviewer evaluates the code. Decisions, status, and concerns are broadcast to every agent through a shared event log. At session start, a retrospective shows what the team learned last time. Tests must pass before the agent can stop.

**How it works:** Every XP practice is implemented as a hook handler — not something the agent "remembers" to do. Hooks are deterministic. They fire every time.

**Who it's for:** Anyone using Claude Code — solo agents benefit from the code review, navigation, and retrospectives. Agent Teams benefit from the broadcast coordination layer that replaces point-to-point mailboxes.

---

## Install

```bash
# Add the marketplace
/plugin marketplace add paulingalls/xp-agents

# Install at user level (required for Agent Teams / worktree support)
/plugin install xp-agents@xp-agents --scope user
```

Or install directly:

```bash
git clone https://github.com/paulingalls/xp-agents.git
claude plugin install ./xp-agents/plugins/xp-agents --scope user
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
[xp-agents] First session — no retrospective data yet.
[xp-agents] GUPP: If there is pending work, act on it immediately.
```

From here, the hooks take over:
- **Before every write** — SMM delta injected, navigator provides strategic guidance
- **After every write** — status auto-updated, quality reviewer evaluates the change, linter runs
- **Every user prompt** — logged as a `customer_input` event
- **Every conflict** — detected and surfaced automatically
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

### Try
- Before reporting done, list what's tested and what isn't.
```

Every session starts smarter than the last one ended.

---

## How It Works

### Hooks Enforce, Agents Suggest

xp-agents uses Claude Code's hook system to enforce XP practices deterministically. Hooks fire at every lifecycle point and are guaranteed to run regardless of what the agent "decides" to do.

| Hook Event | What Fires | XP Practice |
|---|---|---|
| **PreToolUse** (Write/Edit) | SMM delta injection, navigator guidance, `working_on` conflict blocking, TDD order check | Communication, Pair Programming, TDD |
| **PostToolUse** (Write/Edit) | Auto status/working_on, conflict detection, lint check, quality reviewer | Standup, Coding Standards, Courage, Simplicity |
| **PostToolUse** (Bash) | Git commit size check, test result parsing | Small Releases, CI |
| **SubagentStop** (Plan) | Plan size review, decision/assumption extraction to SMM | Planning Game, Simple Design |
| **SessionStart** | Retrospective (Keep/Fix/Try), customer question triage, SMM injection | Retrospective, On-Site Customer |
| **SessionEnd** | Session summary: unresolved items, working state, missing status flag | Honesty |
| **UserPromptSubmit** | Log user prompt as `customer_input` event | On-Site Customer |
| **SubagentStart** | Full SMM injection into new subagents | Collective Code Ownership |
| **SubagentStop** | Review subagent output for quality and alignment | Code Review |
| **Stop** | Block if tests failing | TDD |
| **Notification** | Desktop notification for 🔴 blocking questions | On-Site Customer |
| **PreCompact** | Back up SMM state | Sustainable Pace |

The navigator, quality reviewer, retrospective analyst, customer proxy, and plan reviewer are all hook handlers that fire automatically at the right lifecycle point.

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

Events are semantically typed — each carries different synchronization semantics:

| Event Type | Purpose | Generated By |
|---|---|---|
| `customer_input` | The user's exact words | Hook (automatic) |
| `status` | What each agent is doing + `working_on` files | Hook (automatic) + agent |
| `decision` | Architectural choices | Agent (prompted by hooks) |
| `convention` | Team standards | Agent |
| `concern` | Problems needing attention | Hook (quality reviewer) + agent |
| `discovery` | Unexpected findings | Agent |
| `question` | Customer input needed (🔴 blocking / 🟡 assumed) | Agent |
| `assumption` | Stated beliefs — escalates if contradicted | Agent |
| `pair_guidance` | Navigator strategic direction | Hook (navigator) |
| `session_end` | Session summary with unresolved items | Hook (automatic) |
| `retrospective` | Keep/Fix/Try analysis | Hook (retrospective analyst) |

### The Automated Retrospective

At session start, if there's unanalyzed data from a previous session, the retrospective analyst runs automatically. It uses all five XP values as analytical lenses:

- **Keep**: What worked — grounded in specific events from the log
- **Fix**: What needs improvement — Honesty: were status events truthful? Courage: were concerns raised? Simplicity: was anything over-engineered? Communication: were decisions broadcast? Respect: were conventions followed?
- **Try**: Behavioral experiments for this session — informed by Fix items

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

- **Quality reviewer** — detects empty catch blocks, premature "done" signals, missing error handling
- **Retrospective analyst** — analyzes honesty patterns: were status events truthful? Were concerns raised or did everyone agree too easily?
- **Session end hook** — flags when the agent didn't write a final status summary
- **Conflict detector** — catches convention violations and unacknowledged contradictions
- **CLAUDE.md** — behavioral nudges for judgment calls hooks can't enforce

---

## Extending

Any Claude Code subagent or skill works alongside xp-agents without configuration. Because hooks are global, every subagent automatically gets SMM context, code review, and output evaluation.

No template. No protocol. Just create a subagent. The hooks do the rest.

Build additional hook-based reviewers — security, accessibility, domain-specific quality gates — and publish them to the marketplace.

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

See [MILESTONES.md](MILESTONES.md) for the development roadmap.
See [ARCHITECTURE.md](ARCHITECTURE.md) for technical specifications.
See [RESEARCH.md](RESEARCH.md) for competitive landscape and lessons learned.

## License

MIT

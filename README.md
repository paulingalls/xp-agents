# xp-agents: Extreme Programming for Claude Code

A Claude Code plugin that makes your agents — solo or in teams — write better software through XP practices. Command hooks enforce deterministic rules. Plugin subagents provide judgment-based guidance. A broadcast event log keeps every agent aligned. Zero config. Install and go.

## Forward (from the Human)
Agents are non-deterministic, dishonest, lazy and they constantly cheat, all in their unshakable desire to achieve their goal.  They ignore what you tell them, they think instructions are for the weak. They do things their own way.

Kind of like humans.

Over 25 years I've been running, hiring and working with engineers.  Messy, spectrumy, brilliant, strange. They run the gamut. But one thing has constantly brought them together into a powerful team, and those are the values and discipline of Extreme Programming.

So, as Agents become more and more human like, using some of the same practices with them just made sense.  This plugin is my attempt to coral them into a working team, first as a teammate of me (solo agent) and then as teammates of each other (CLI teammates running in parallel worktrees).

So, give it a shot and drop me an issue.  I'd love to hear what you think...

Paul, the human theoretically in charge..;)

## TL;DR

**What it does:** Command hooks fire automatically on tool calls — blocking conflicts, enforcing TDD, running linters, and tracking status. Plugin subagents provide strategic guidance: a plan reviewer validates plans and a retrospective analyst surfaces cross-session learning. Inline skills handle work selection, quality review, sprint planning, and SMM curation. Everything is broadcast through a shared event log visible to every agent.

**How it works:** Deterministic enforcement (tests, lint, conflicts, security) lives in command hooks — they fire every time. Judgment work (plan analysis, retrospectives, quality review) lives in plugin subagents and inline skills, triggered by hook nudges or stop gates.

**Who it's for:** Anyone using Claude Code — solo agents benefit from the quality review, retrospectives, and TDD enforcement. Teams benefit from the broadcast coordination layer that keeps every agent aligned.

---

## Install

From within a Claude Code session:

```bash
# Add the marketplace
/plugin marketplace add paulingalls/xp-agents

# Install
/plugin install xp-agents@xp-agents
```

Or from your terminal (skips the interactive scope picker):

```bash
# Add the marketplace
claude plugin marketplace add paulingalls/xp-agents

# Install at user scope (available across all projects)
claude plugin install xp-agents@xp-agents --scope user

# Or install at project scope (shared with team via .claude/settings.json)
claude plugin install xp-agents@xp-agents --scope project
```

For local development, use `--plugin-dir` (session-only, not persisted):

```bash
claude --plugin-dir /path/to/xp-agents/plugins/xp-agents
```

**Requirements:** Python 3.11+ on PATH. macOS or Linux. Zero external packages.

**Scopes:** User scope makes xp-agents available on all your projects. Project scope shares it with your team via version control. Both work with CLI teammates — the SMM is stored in `CLAUDE_PLUGIN_DATA` (shared across worktrees).

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

Each person installs individually. The marketplace entry is just discovery.

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
[xp-agents] SMM curated. Process guide loaded. Ready to work.
```

From here, the system takes over:
- **Every user prompt** — prompt nuggets inject new signal events (concerns, decisions, discoveries) since last prompt (~50-100 tokens)
- **Before every write** — conflict detection via `.coordination.json`, TDD order check, plan review gate blocks writes until `/xp-review-plan` runs
- **Before every commit** — review cycle gate blocks until `/simplify` and `/xp-quality-review` complete (for commits with code changes); security review runs at story (`/xp-accept`, Tier 2) and close (Tier 3) boundaries
- **After every write** — status auto-updated, linter runs
- **After plan mode exits** — `PostToolUse:ExitPlanMode` nudges `/xp-review-plan` to extract assumptions, decisions, and risks
- **At stop** — TDD gate blocks if tests failing
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

[xp-agents] Triaging open questions and previous Try items...
[xp-agents] Any goals for this session?

> "Add role-based access control"

[xp-agents] Goal recorded. Running housekeeping...
[xp-agents] SMM curated:
  Intent: 2 items | Constraints: 5 items | Risks: 3 items | Wisdom: 2 items
[xp-agents] Ready to work.
```

Every session starts smarter than the last one ended. The kickoff sequences retrospective → work selection (questions, Try items, goals) → housekeeping, curating the four-pillar SMM with aging debt, undelivered intents, and lessons learned.

---

## How It Works

### Hooks Enforce, Subagents Advise

xp-agents uses two mechanisms: **command hooks** for deterministic enforcement (they fire every time, guaranteed) and **plugin subagents + inline skills** for judgment-based guidance (full tool access, triggered by hook nudges or stop gates).

| Hook Event | What Fires | XP Practice |
|---|---|---|
| **UserPromptSubmit** | Prompt nuggets (new signal events since last prompt), customer input logging, kickoff gate | Communication, On-Site Customer |
| **PreToolUse** (Write/Edit) | `working_on` conflict blocking (via `.coordination.json`), TDD order check, plan review gate blocks writes until `/xp-review-plan` clears marker | TDD, Planning Game |
| **PreToolUse** (Bash) | Commit-gated review cycle (simplify → quality review; Tier 1 patterns scan staged diffs), file-modification conflict heuristic (advisory) | Coding Standards, Refactoring |
| **PostToolUse** (Write/Edit) | Auto status/working_on, conflict detection, lint check | Standup, Coding Standards |
| **PostToolUse** (Bash) | Git commit size check, test result parsing (unittest/pytest/jest/go/swift/bun) | Small Releases, CI |
| **PostToolUse** (ExitPlanMode) | Write `.plan-awaiting-review` marker, nudge agent to run `/xp-review-plan` via additionalContext | Planning Game |
| **PostToolUse** (Skill) | Review cycle flag updates (simplify, quality review), kickoff completion (process guide injection + compaction) | Coding Standards, Refactoring, Communication |
| **PostToolUseFailure** (Bash) | Test failure detection and recording | TDD, CI |
| **SubagentStart** | Tiered context injection (Explore: Intent+Constraints, others: full SMM + process guide) | Collective Code Ownership |
| **SubagentStop** (Plan) | Write `.plan-awaiting-review` marker (fallback for Plan subagent flow) | Planning Game |
| **SessionStart** | GUPP + skills injection, retrospective data prep, `.needs-kickoff` marker | Retrospective, On-Site Customer |
| **SessionEnd** | Session summary: unresolved items, working state, missing status flag + event log compaction | Honesty, Sustainable Pace |
| **PreCompact** | Back up SMM state | Sustainable Pace |
| **PostCompact** | Compact event log (age decisions, cap retros, prune resolved items) | Sustainable Pace |
| **Stop** | Block if tests failing (`tdd_stop_gate.py`), block if housekeeping hasn't run (`housekeeping_stop_gate.py`) | TDD, Feedback |

### Plan Review — Two Entry Points

Plans can be created two ways: via `EnterPlanMode`/`ExitPlanMode` tools (the agent enters a read-only planning mode) or via a Plan subagent (the `Agent` tool with type `Plan`). Both flows trigger plan review:

1. **ExitPlanMode tool** → `PostToolUse:ExitPlanMode` writes the `.plan-awaiting-review` marker and nudges the agent via `additionalContext`
2. **Plan subagent** → `SubagentStop` writes the marker when `agent_type == "Plan"`

In both cases, `PreToolUse:Write|Edit` **blocks** all writes (except plan files in `.claude/plans/`) until `/xp-review-plan` runs. The review skill's preload clears the marker. This ensures assumptions, decisions, and risks from every plan feed the Shared Mental Model.

### Skills

| Skill | Purpose | When It Runs |
|---|---|---|
| `/xp-kickoff` | Session start orchestrator — sequences retro, work selection, housekeeping | Every session start |
| `/xp-run-retrospective` | Keep/Fix/Try analysis with XP values as lenses | Kickoff step 1 (when retro data exists) |
| `/xp-work-selection` | Triage open questions, retro Try items, and select session goals | Kickoff step 2 |
| `/xp-housekeeping` | Curate the four-pillar SMM (Intent, Constraints, Risks, Wisdom) | Kickoff step 3 |
| `/xp-plan` | Execution planning — transforms design sources into ordered milestones with change zones | Before implementation |
| `/xp-system-context` | Autonomous codebase analysis — produces system description, architecture, constraints | Before planning or on demand |
| `/xp-sprint-start` | Decompose milestones into context-rich stories with file domains and interface contracts | After planning |
| `/xp-review-plan` | Plan review — checks size, TDD ordering, decision conflicts, records assumptions | After planning completes |
| `/xp-assign` | Analyze plan steps, select execution mode (solo vs CLI teammates), spawn if parallel | After sprint stories are ready |
| `/xp-quality-review` | Post-simplify courage check — skipped recommendations, drift, debt | After `/simplify` |
| `/xp-accept` | Verify acceptance criteria, guide e2e testing, mark stories done or deferred | After implementation |
| `/xp-sprint-review` | Review what shipped vs planned, update milestones, record velocity | When all stories are done or deferred |
| `/xp-sprint-close` | Push sprint branch, fork close-reviewer, merge into target, cleanup | After sprint review |
| `/xp-plan-close` | Push plan branch, fork close-reviewer, merge into primary, archive | After last milestone's sprint-close |
| `/xp-free-close` | Push free branch, fork close-reviewer, merge into primary, cleanup | End of free session |

### The Shared Mental Model

xp-agents uses a broadcast event log visible to every agent — the main agent, all subagents, and all CLI teammates in parallel worktrees.

```
${CLAUDE_PLUGIN_DATA}/{project-id}/smm/
├── events.jsonl              ← append-only log
├── shared_mental_model.json  ← curated four-pillar view, written by housekeeping
├── execution_plan.json       ← ordered milestones with change zones and design context
├── sprint.json               ← current sprint stories with file domains and acceptance criteria
├── system_context.json       ← autonomous codebase analysis (architecture, constraints)
├── .curation-watermark       ← last-curated event position
├── .coordination.json        ← per-agent working_on for O(1) conflict detection
├── .plan-awaiting-review     ← plan review gate marker
├── events.lock               ← flock for atomic appends
└── retrospectives/           ← Keep/Fix/Try session artifacts
```

The SMM lives in `CLAUDE_PLUGIN_DATA` (`~/.claude/plugins/data/xp-agents-xp-agents/`), keyed by a hash of the git repo's common directory. This means CLI teammates in different git worktrees all share the same event log.

The curated view uses a four-pillar model, written by housekeeping (LLM judgment):
- **Intent** — project goals and active customer intents
- **Constraints** — confirmed decisions, conventions, and architectural boundaries
- **Risks** — concerns, blocking questions, unverified assumptions, technical debt (with severity aging)
- **Wisdom** — lessons learned, retrospective insights, behavioral conventions

Context reaches agents through lightweight **prompt nuggets** at each user prompt (~50-100 tokens of new signal events) and tiered context injection at subagent spawn (Explore gets Intent+Constraints only, others get full SMM + process guide). The main agent gets the SMM during housekeeping and the process guide via PostToolUse:Skill hook.

Events are semantically typed — each carries different synchronization semantics:

| Event Type | Purpose | Generated By |
|---|---|---|
| `goal` | Project north star — what we're building and why | Skill (xp-work-selection) + customer |
| `customer_input` | The user's exact words | Command hook (automatic) |
| `customer_intent` | Distilled customer request — tracked until delivered | Skill (xp-work-selection) |
| `status` | What each agent is doing + `working_on` files | Command hook (automatic) + agent |
| `decision` | Architectural choices | Agent + subagent (plan reviewer) |
| `convention` | Team standards | Agent |
| `concern` | Problems needing attention | Skill (quality review) + agent |
| `discovery` | Unexpected findings | Agent |
| `question` | Customer input needed (🔴 blocking / 🟡 assumed) | Agent + subagent (plan reviewer) |
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

### Sprint Execution: Solo and Worktree Subagents

After planning, the `/xp-assign` skill analyzes the plan's steps and selects an execution mode:

**Solo** (sequential) — the lead executes stories one at a time. Best when stories have dependencies between them, overlapping file domains, or are all small (S-sized). This is the default and most common mode.

**CLI Teammates** (parallel) — each independent step group gets its own `claude -p` process running in an isolated git worktree. Teammates have full autonomy: they write tests, implement, run the review cycle (`/simplify`, `/xp-quality-review`), and commit independently. Tier 2/3 security review fires at story acceptance and close. The lead merges branches after all teammates complete.

`/xp-assign` chooses CLI teammates when two or more step groups are substantial, have no dependencies between them, and have non-overlapping file domains. The mode decision is presented to the user for confirmation before spawning.

Because hooks are global and the SMM is stored in `CLAUDE_PLUGIN_DATA` (shared across worktrees), every teammate automatically gets:

- Tiered context injection at spawn (full SMM + process guide)
- `working_on` conflict detection across teammates
- Commit-gated review cycle enforcement (same gates as solo)
- Decisions and concerns visible to every other agent
- A team-wide retrospective at next session start

---

## Configuration

xp-agents works out of the box with zero configuration. It is opinionated — all enforcement is always on. If a gate is annoying, the solution is to fix the gate, not make it optional.

---

## Development setup

The shipping plugin code is **stdlib-only** — every script under `plugins/xp-agents/` runs on Python 3.11+ with no `pip install`. The test suite is allowed external runners (it doesn't ship), and the recommended setup is `pipx`:

```bash
# One-time tooling install (isolated venv, on PATH, no Homebrew conflict):
brew install pipx                    # if not already installed
pipx install pytest
pipx inject pytest pytest-xdist      # parallel test execution

# Run all 3326 tests in parallel (~13s on 16 cores):
pytest -n auto

# Or sequentially via unittest (no pytest required, ~89s):
python3 -m unittest discover -s plugins/xp-agents/tests -p "test_*.py"
```

`lefthook` runs `pytest -n auto` on every commit. If `pytest` isn't on PATH, lefthook will fail loud — install it via the steps above, or set `LEFTHOOK=0 git commit ...` to bypass for an emergency.

Run a single file: `pytest plugins/xp-agents/tests/hooks/test_session_start.py`.
Run a single test: `pytest plugins/xp-agents/tests/hooks/test_session_start.py::TestSessionStart::test_clear_source_returns_context`.

---

## Why This Exists

Multi-agent systems fail for reasons that have nothing to do with individual capability. The research is consistent:

**Coordination costs scale exponentially.** Galileo Labs (Feb 2026) found that 4 agents create 6 potential failure points, 10 agents create 45. Seven common failure modes — all rooted in insufficient coordination architecture.

**Group dynamics apply to AI teams too.** Bentes (Feb 2026) maps distributed systems failures onto multi-agent AI: the Anti-Volunteer's Dilemma (agents act simultaneously because no one can see another is handling it), Split-Brain Inconsistency (agents on different versions of reality after compaction), the "Yes, And" Hallucination Cascade (agents building on each other's errors).

**Shared mental models are the solution.** Lou et al. (USC/ASU, Mar 2026) established shared mental models as the primary alignment mechanism for human-AI teaming. A Nature study (Feb 2026) found structured coordination protocols essential precisely where LLMs are weakest.

**XP was designed for this.** At "The Future of Software Development" summit (Feb 2026), a major theme was the resurgence of XP practices in the AI era. XP was built for high uncertainty, rapid change, and continuous feedback — exactly what AI agents create.

xp-agents provides the coordination layer that Claude Code doesn't ship with: a shared mental model visible to every agent (solo or CLI teammates in parallel worktrees), conflict detection across concurrent workers, commit-gated code review enforcement, and cross-session retrospective learning.

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

xp-agents enforces honesty through data, not aspiration:

- **Honesty signals in the retro** — the retrospective receives concrete sequence-based metrics: longest streak of code writes without a test run, code commits without a recorded security check at story/close boundaries, code-write-to-concern ratio, whether assumptions were stated, and whether a final status was recorded. The retro uses these to flag specific honesty gaps, not vague patterns.
- **Quality review skill** — post-simplify courage check: were recommendations skipped? Drift management: do code changes contradict recorded decisions?
- **Conflict detector** — catches convention violations, superseded decisions, and unacknowledged contradictions
- **Process guide** — XP behavioral rules injected after housekeeping for judgment calls hooks can't enforce

---

## Extending

Any Claude Code subagent or skill works alongside xp-agents without configuration. Because hooks are global, every subagent automatically gets SMM context and output evaluation via the existing command hooks.

Build additional reviewers — security, accessibility, domain-specific quality gates — as plugin subagents or command hooks and publish them to the marketplace.

---

## Technical Details

### XP Practices → Enforcement Mechanism

| Practice | Enforcement | Mechanism |
|---|---|---|
| **TDD** | Deterministic: Stop blocks if tests fail (`tdd_stop_gate.py`). TDD order check in PreToolUse. unittest/pytest/jest/go/swift/bun/xcodebuild test detection. | `tdd_stop_gate.py`, `pre_tool_write.py`, `bash_post_tool.py` |
| **Pair Programming** | Skill: quality review after simplify (courage + drift + debt awareness). | `/xp-quality-review` |
| **Planning Game** | Subagent: plan reviewer checks size, TDD ordering, decision conflicts. Three-layer enforcement via PostToolUse:ExitPlanMode, SubagentStop:Plan, and PreToolUse write block. Skill: work selection (goals, questions, Try items). | `xp-plan-reviewer`, `/xp-work-selection` |
| **Small Releases** | Deterministic: commit size check. | `bash_post_tool.py` |
| **Coding Standards** | Deterministic: lint after every write, convention tracking, conflict detection, Tier 1 secret-pattern scan on staged diffs. | `lint_check.py`, `post_tool_use.py`, `pre_tool_write.py`, `pre_tool_bash.py` |
| **Continuous Integration** | Deterministic: test results parsed (success + failure). Stop blocks on failure. | `bash_post_tool.py`, `bash_failure.py`, `tdd_stop_gate.py` |
| **Refactoring** | Commit gate: `/simplify` required before commit if code files changed, quality review checks skipped recommendations. Enforced by `pre_tool_bash.py` + `markers.py`. | `/xp-quality-review`, `pre_tool_bash.py` |
| **Simple Design** | Subagent: plan reviewer flags oversized plans. `/simplify` required at commit for code changes. | `xp-plan-reviewer`, `pre_tool_bash.py` |
| **Collective Code Ownership** | Deterministic: prompt nuggets at each prompt, tiered context at subagent spawn (Explore: Intent+Constraints, others: full SMM + process guide). Global hooks. | `prompt_nugget.py`, `subagent_start.py` |
| **On-Site Customer** | Deterministic: prompts logged. Skill: work selection (goals, questions, Try items). | `user_prompt_log.py`, `/xp-work-selection` |
| **Retrospective** | Subagent: Keep/Fix/Try at session start with XP values as analytical lenses. | `xp-retrospective` |

### Token Cost Model

| Source | Per-occurrence | Frequency | Mitigation |
|---|---|---|---|
| Prompt nugget (UserPromptSubmit) | 50-100 tokens | Every user prompt | Watermark-based, only new signal events |
| SessionStart + kickoff | 2,000-5,000 tokens | Once per session | One-time cost (retro + goals + housekeeping) |
| Retrospective subagent | 10,000-20,000 tokens | Once per session | Only when unanalyzed events exist |
| `/simplify` at commit | 30,000-60,000 tokens | Once per commit with ≥3 code files | Threshold skips small changes |
| `/xp-quality-review` at commit | 5,000-10,000 tokens | Once per commit after simplify | Focused: courage + drift + debt only |

### Debt Aging

Technical debt events age across sessions. The materializer counts `session_end` events after the debt timestamp:

- **0-3 sessions**: rendered normally
- **4-6 sessions**: rendered with ⚠️, retrospective flags in Fix items
- **7+ sessions**: rendered with 🔴, retrospective escalates urgency

Repayment pressure comes from two sources: quality review surfaces debt when touching affected files, retrospective escalates aging debt in Fix items.

### Event Log Compaction

The event log grows over sessions. Compaction runs at three points: after kickoff (PostToolUse:Skill when housekeeping completes), at session end (SessionEnd), and during context compaction (PostCompact). All use the same `compact.py` with watermark-based policy:

- **Status events**: compacted freely (counts preserved in session summaries)
- **Customer inputs**: compacted freely (captured in Intent pillar)
- **Decisions**: aged after 3 sessions (confirmed decisions live in Constraints pillar)
- **Assumptions/Questions**: aged after 5 sessions (gives housekeeping time to curate into Risks)
- **Retrospectives**: capped at 2 in the log (archived in `retrospectives/` directory)
- **Resolved items**: pruned (goals, concerns, debt with resolution events)

Only events before the curation watermark are eligible for compaction.

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

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for technical specifications.
See [SMM_DESIGN.md](docs/SMM_DESIGN.md) for the four-pillar Shared Mental Model design.
See [BRANCHING_DOCTRINE.md](docs/BRANCHING_DOCTRINE.md) for the branching stage model and team scenarios.
See [RESEARCH.md](docs/RESEARCH.md) for competitive landscape and lessons learned.

## License

MIT

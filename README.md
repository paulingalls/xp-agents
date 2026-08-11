```
██╗  ██╗██████╗        █████╗  ██████╗ ███████╗███╗   ██╗████████╗███████╗
╚██╗██╔╝██╔══██╗      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝██╔════╝
 ╚███╔╝ ██████╔╝══════███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ███████╗
 ██╔██╗ ██╔═══╝       ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ╚════██║
██╔╝ ██╗██║           ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ███████║
╚═╝  ╚═╝╚═╝           ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝
```

# _Extreme Programming in a Box_

XP-Agents is a Claude Code plugin that makes your agents — solo or in teams — write better software through XP practices. Command hooks enforce deterministic rules. Plugin subagents provide judgment-based guidance. A broadcast event log keeps every agent aligned. Zero config. Install and go.

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

**Scopes:** User scope makes xp-agents available on all your projects. Project scope shares it with your team via version control. Both work with CLI teammates — the SMM is stored under `XP_AGENTS_DATA` (default `~/.xp-agents/data`, shared across worktrees).

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

### Installing on Codex

Everything above this heading describes Claude Code. Codex reads its own
marketplace catalog and its own plugin manifest, both shipped in this repo beside
the Claude ones. Register the marketplace, then install:

From a local checkout — this is the sequence the test suite executes:

```bash
codex plugin marketplace add /path/to/xp-agents
codex plugin add xp-agents@xp-agents
```

From the published repo — the same commands, with the source given as
`owner/repo`:

```bash
codex plugin marketplace add paulingalls/xp-agents
codex plugin add xp-agents@xp-agents
```

The local form is listed first because it is the one the suite actually runs. The
published form's syntax is documented by `codex plugin marketplace add`, but
whether a fresh clone resolves the catalog's relative plugin path has not been
measured here — treat it as untested, not as broken.

**You must review the hooks, or nothing is enforced.** Codex will not run
plugin-bundled hooks until you trust them, and this is the part worth reading
twice:

- **Interactive:** run `/hooks` and approve. Approval is per *content hash*, so
  it must be repeated after every plugin update.
- **Headless:** pass `--dangerously-bypass-hook-trust`.
- **If you skip it, nothing tells you.** Untrusted hooks are skipped **silently** —
  the hooks file is demonstrably read, yet no handler runs and no error appears.
  The session looks completely normal while every XP gate is absent: no commit
  gate, no TDD gate, no stop gates, no secret scan.

**`--disable unified_exec` is required on every Codex spawn**, not a
recommendation. Without it, `exec_command` opens a persistent shell and
`write_stdin` sends work into it that the command hook never sees — bypassing the
commit gate, the tier-1 secret scan, staged-lint and branch protection. The flag
removes that channel and substitutes `shell_command`, which is gated.

**The per-commit review gate has no automatic release on Codex yet**, and it
will block your commits until you move the review. The gate itself fires
normally: at two or more changed code files, `git commit` stops with "Run
/xp-quality-review before committing". What clears it does not run there — the
flag is written by a hook matched on Claude Code's own tool names, and the
reviewer it spawns is a Claude Code subagent. So the block has no reachable exit
on Codex. Until harness parity lands, move the review to story close, which
turns that block into a visible advisory:

```bash
cd /path/to/your/project
PLUGIN=~/.codex/plugins/cache/xp-agents/xp-agents/<version>
python3 "$PLUGIN/scripts/cadence_cli.py" --smm-dir "$("$PLUGIN/smm/init.sh")" write story
```

This defers the review; it does not disable the gate. The tier-1 secret scan,
the staged-lint check and branch protection stay unconditional either way.

**Re-run it every session.** The cadence marker is session-scoped: a fresh
start (a new session, or `/clear`) resets it to the careful per-commit default,
deliberately, so one session's choice never leaks into the next. That reset runs
on Codex too — `SessionStart` is registered in the generated hooks variant. So
the command above buys you the session you run it in and no more; the next one
begins blocked again. Treat it as something you type at the start of a session,
not once at install time.

**No minimum Codex version is claimed.** The plugin was exercised on `0.146.0`
and nothing older was ever installed, so there is no measured floor to state — a
version that works tells you nothing about where support began. This is an
unknown, not an assurance that every version works: an older Codex that runs the
skills while ignoring the hooks would be unenforced in exactly the silent way
described above.

The scope and team-discovery notes above are Claude Code's. `codex plugin add`
takes no scope flag, and no `.claude/settings.json` equivalent for sharing the
marketplace with a team was measured here — each person registers it themselves.

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
- **Before every write** — conflict detection (via `.coordination.json`), TDD order check, plan-review gate (`/xp-review-plan`), and assign gate (`/xp-assign`, worktree teammates exempt)
- **Before every commit** — review cycle gate (`/xp-quality-review`) once 2+ code files changed since the last review; on *story* cadence the gate defers instead, and the review runs at `/xp-story-close`. `[release]`/`[chore]`/`[sprint-direct]`-prefixed messages bypass for legitimate maintenance. Security is two-tier: a deterministic secret/pattern scan on the staged diff at every commit (Tier 1), and `/security-review` over the cumulative branch diff at close (Tier 2)
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
| **PreToolUse** (Write/Edit) | `working_on` conflict blocking (via `.coordination.json`), TDD order check, `.plan-awaiting-review` gate blocks writes until `/xp-review-plan` clears it, `.assign-pending` gate blocks writes until `/xp-assign` clears it (worktree teammates exempt) | TDD, Planning Game |
| **PreToolUse** (Bash) | Commit-gated review cycle (`/xp-quality-review`; Tier 1 secret/pattern scan on the staged diff), branch-protection advisories, cd-into-worktree-git advisory. No Bash file-modification coordination gate — `pre_tool_write` covers Edit/Write; cross-agent Bash damage is caught at story-close merge. | Coding Standards, Refactoring |
| **PreToolUse** (Skill) | Prepare per-skill review guidance before a skill runs | Coding Standards |
| **PreToolUse** (EnterPlanMode) | Schedule gate — blocks plan entry until `/xp-schedule` promotes a frontier | Planning Game |
| **PostToolUse** (Write/Edit) | Auto status/working_on, conflict detection, lint check | Standup, Coding Standards |
| **PostToolUse** (Bash) | Git commit bookkeeping and size check, test result parsing (24 runners across Python, JS/TS, Go, Rust, Swift, JVM, Ruby, PHP, .NET, Dart, Elixir, C/C++) | Small Releases, CI |
| **PostToolUse** (ExitPlanMode) | Write `.plan-awaiting-review` marker, nudge agent to run `/xp-review-plan` via additionalContext | Planning Game |
| **PostToolUse** (Skill\|Agent) | Review cycle flag updates (`/code-review`, `/xp-quality-review`), forked-xp completion routing in `review_cycle_done.py` — process guide injection on housekeeper completion, `/xp-assign` task-creation nudge after assign, security-review continuation nudge; accept-marker drain | Coding Standards, Refactoring, Communication |
| **PostToolUse** (AskUserQuestion) | Record the user's answer as an `answer` event | On-Site Customer |
| **PostToolUseFailure** (Bash) | Test failure detection and recording | TDD, CI |
| **PostToolUseFailure** (AskUserQuestion) | Record the clarification when a question is dismissed | On-Site Customer |
| **SubagentStart** | Tiered context injection + XP values (Explore: Intent+Constraints; `xp-code-reviewer`/Plan/unknown: full SMM; generic catch-alls: an SMM reference pointer; other `xp-*` agents: values only, plus preload paths for retrospective/housekeeper) | Collective Code Ownership |
| **SubagentStop** (Plan) | Write `.plan-awaiting-review` marker (fallback for Plan subagent flow when PostToolUse:Agent doesn't fire) | Planning Game |
| **SessionStart** | GUPP + XP values injection, retrospective data prep, `.needs-kickoff` marker | Retrospective, On-Site Customer |
| **SessionEnd** | Session summary: unresolved items, working state, missing status flag + event log compaction | Honesty, Sustainable Pace |
| **PreCompact** | Back up SMM state | Sustainable Pace |
| **PostCompact** | Compact event log (age decisions, cap retros, prune resolved items) | Sustainable Pace |
| **Stop** | Six gates: tests failing, sprint lifecycle (accept → review), close-cycle mid-flight (CLOSE_CYCLE_ACTIVE marker), housekeeping not run, session-end checklist warning, teammate uncommitted/incomplete review cycle | TDD, Feedback |
| **TeammateIdle** | TDD enforcement for an idle CLI teammate | TDD |
| **TaskCompleted** | TDD enforcement when a teammate reports its task complete | TDD, Honesty |
| **WorktreeCreate** | Set up the branch base for a teammate worktree | Collective Code Ownership |

### Token Budgets and Honesty Guards

Three regression suites keep the plugin's hot paths honest as it grows:

- **Byte-budget framework (emitters + preloads)** — every shipping hook-injection emitter and forked-skill preload has a per-script byte budget. Suites measure each script against a seeded SMM and fail if output grows past `ceil(measured * 1.125 / 100) * 100` bytes. New emitters or preloads must register a budget; the surface scan refuses to ship anything unbudgeted.
- **Byte-budget framework (in-context guides)** — `PROCESS_GUIDE.md`, `XP_VALUES.md`, and `TEAMMATE_GUIDE.md` carry per-file line budgets so prose growth is caught before it ships.
- **12-hex-ID grep guard** — SMM event IDs are 12-hex strings, and they age out of the log as sessions roll over. Sister suites scan the shipped plugin guides and emitter prose for stray IDs and refuse to ship any — a hard-coded ID rots the moment its event ages out. Repo-level dev docs (`docs/`, `CLAUDE.md`) are out of the guard's scope; spike and design docs there may cite IDs as anchors during the design window.

### Plan Review — Two Entry Points

Plans can be created two ways: via `EnterPlanMode`/`ExitPlanMode` tools (the agent enters a read-only planning mode) or via a Plan subagent (the `Agent` tool with type `Plan`). Both flows trigger plan review:

1. **ExitPlanMode tool** → `PostToolUse:ExitPlanMode` writes the `.plan-awaiting-review` marker and nudges the agent via `additionalContext`
2. **Plan subagent** → `SubagentStop` writes the marker when `agent_type == "Plan"`

In both cases, `PreToolUse:Write|Edit` **blocks** all writes (except plan files in `.claude/plans/`) until `/xp-review-plan` runs. The review skill's preload clears the marker. This ensures assumptions, decisions, and risks from every plan feed the Shared Mental Model.

### Skills

| Skill | Purpose | When It Runs |
|---|---|---|
| `/xp-kickoff` | Session start orchestrator — sequences retro, work selection, housekeeping | Every session start |
| `/xp-work-selection` | Triage open questions, retro Try items, and select session goals | Kickoff step 5 |
| `/xp-plan` | Execution planning — transforms design sources into ordered milestones with change zones | Before implementation |
| `/xp-system-context` | Autonomous codebase analysis — produces system description, architecture, constraints | Before planning or on demand |
| `/xp-sprint-start` | Decompose milestones into context-rich stories with file domains and interface contracts | After planning |
| `/xp-schedule` | Promote the next dependency-satisfied frontier (`scheduled → in-progress`), pick solo vs teammate mode, set each story's `execution_mode`, and (solo) JIT-create the branch | Before planning each frontier — invoked by the kickoff tail and `/xp-accept`'s post-loop; state-derived gates enforce it |
| `/xp-review-plan` | Plan review — checks size, TDD ordering, decision conflicts, records assumptions | After planning completes |
| `/xp-assign` | Per-story: create the next un-spawned story's branch and spawn ONE CLI teammate (per-story plan→review→spawn loop, NOT a batch fan-out; mode already selected by `/xp-schedule`) | After `/xp-schedule` promotes the teammate batch and each story's plan is reviewed (one /xp-assign per story) |
| `/xp-scaffold-acceptance` | Interactive scaffold of an acceptance test harness (pytest/playwright/bats/cargo/etc.) for a `system_context.json` surface | On demand when adding an automated AC surface |
| `/xp-scaffold-worktree` | Measure whether a fresh worktree can run a declared command, propose a bootstrap candidate, and declare `stack.worktree_bootstrap` **only** after re-measuring proves the gap closed — refuse otherwise | On demand when teammate worktrees fail on state a bare checkout lacks |
| `/xp-quality-review` | The per-increment review — spawns `xp-code-reviewer` for correctness, reuse, quality, efficiency, drift, and debt | Before each commit (commit cadence); at `/xp-story-close` on story cadence |
| `/xp-accept` | Verify acceptance criteria, guide e2e testing, mark stories done or deferred | After implementation |
| `/xp-story-close` | Per-accepted-story merge into the sprint base and cleanup — no promotion or branching of the next story (that's `/xp-schedule`, via `/xp-accept`'s post-loop) | Auto-invoked by `/xp-accept` per accepted story |
| `/xp-sprint-review` | Review what shipped vs planned, update milestones, record velocity | When all stories are done or deferred |
| `/xp-sprint-close` | Push sprint branch, fork close-reviewer, merge into target, cleanup | After sprint review |
| `/xp-plan-close` | Push plan branch, fork close-reviewer, merge into primary, archive | After last milestone's sprint-close |
| `/xp-free-close` | Push free branch, fork close-reviewer, merge into primary, cleanup | End of free session |
| `/xp-end-session` | Emit `session_summary`, force-close open questions, bulk-drop addressed concerns/debts, append to `session_history.json` | End of session |

### Plugin Subagents (auto-invoked)

These are subagents shipped by the plugin under `agents/`, not slash commands. They're spawned by skills or hooks; you don't call them directly.

| Subagent | Purpose | Triggered By |
|---|---|---|
| `xp-retrospective` | Keep/Fix/Try analysis with XP values as lenses | `/xp-kickoff` step 1 (always; emits a seed retro on fresh projects) |
| `xp-housekeeper` | Curate the four-pillar SMM (Intent, Constraints, Risks, Wisdom) | `/xp-kickoff` step 6 |
| `xp-plan-reviewer` | Plan-quality analysis — size, TDD ordering, milestone boundaries, decision conflicts | `/xp-review-plan` |
| `xp-code-reviewer` | Independent code reviewer — self-finds correctness per increment, or validates and fixes `/code-review`'s handed-in findings at close | `/xp-quality-review` |
| `xp-sprint-reviewer` | Reviews what shipped vs planned; updates milestone delivery state | `/xp-sprint-review` |
| `xp-close-reviewer` | Cross-cutting diff review of the full close source branch vs its merge target | `/xp-{free,sprint,plan,story}-close` |
| `xp-system-analyzer` | Reads codebase + CLAUDE.md to produce `system_context.json` | `/xp-system-context` |

### The Shared Mental Model

xp-agents uses a broadcast event log visible to every agent — the main agent, all subagents, and all CLI teammates in parallel worktrees.

```
${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/smm/
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

The SMM lives at `$XP_AGENTS_DATA` (default `~/.xp-agents/data/`), keyed by a hash of the git repo's common directory. It is deliberately NOT under `~/.claude/plugins/data/`, which `claude plugin uninstall` deletes by default — an SMM there would be one uninstall away from silent loss. An SMM found under that older location is relocated for you, by COPY — the original is left in place, so nothing is lost if the copy is interrupted, and you can delete it once you are satisfied. While a teammate is live against the old location, relocation is **declined** and the session resolves in place instead — it is retried at the next session start, so a stale worktree whose branch never merged holds it back indefinitely. Run `python3 plugins/xp-agents/scripts/migrate_smm_root.py` to see what is holding it, then `--confirm --force` to relocate anyway once you have confirmed nothing is running. This means CLI teammates in different git worktrees all share the same event log.

The curated view uses a four-pillar model, written by housekeeping (LLM judgment):
- **Intent** — project goals and active customer intents
- **Constraints** — confirmed decisions, conventions, and architectural boundaries
- **Risks** — concerns, blocking questions, unverified assumptions, technical debt (with severity aging)
- **Wisdom** — lessons learned, retrospective insights, behavioral conventions

Per-pillar size caps and resolution discipline live in [PROCESS_GUIDE.md §Pillars](plugins/xp-agents/PROCESS_GUIDE.md#pillars) — the single source of truth.

Context reaches agents through lightweight **prompt nuggets** at each user prompt (~50-100 tokens of new signal events) and tiered context injection at subagent spawn. Every tier gets `XP_VALUES.md`; on top of that, Explore gets Intent+Constraints only, `xp-code-reviewer` and unknown/ad-hoc types get the full SMM, generic catch-alls (`general-purpose`, `workflow-subagent`, `claude`) get a one-line pointer to render the SMM themselves, and the plugin's own forked `xp-*` agents get nothing extra (their data arrives via skill preloads). The main agent gets the SMM during housekeeping and the process guide via PostToolUse:Skill hook.

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
- **Fix**: What needs improvement — Honesty: were assumptions stated and concerns proportional? Communication: were decisions recorded and questions answered? Courage: were hard problems addressed and bad decisions revisited? Simplicity: were conventions followed and plans right-sized? Feedback: were tests written first and review findings acted on?
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

### Sprint Execution: Frontier Scheduling, Solo and Worktree Subagents

Sprint stories advance in **frontiers** — the set of `scheduled` stories whose dependencies are satisfied. At each frontier, **before planning**, the `/xp-schedule` skill promotes the frontier (`scheduled → in-progress`), picks the execution mode, and sets each story's `execution_mode`. State-derived gates make this structurally unskippable: while `scheduled` stories exist with none `in-progress`, the write gate and the EnterPlanMode gate both block until `/xp-schedule` runs.

**Solo** (sequential) — the lead executes one story at a time. Chosen when the frontier is a single story, or stories share file domains. `/xp-schedule` promotes the lowest-id story, JIT-creates its branch, and the lead enters plan mode for it. No `/xp-assign` step — the lead codes straight after plan review.

**CLI Teammates** (parallel) — chosen when two or more frontier stories have non-overlapping file domains (the user confirms). `/xp-schedule` promotes the whole frontier as a teammate batch; the lead then loops per story: plan → `/xp-review-plan` → `/xp-assign` (which targets the lowest-id un-spawned story, creates its branch, and spawns ONE teammate in an isolated `claude -p` worktree). Each teammate has full autonomy: writes tests, implements, runs the review cycle, commits independently. Tier 1 pattern scanning fires on each teammate commit; Tier 2 `/security-review` fires once at the enclosing close. The lead merges each branch at `/xp-story-close`.

After each story closes, `/xp-accept`'s post-loop calls `/xp-schedule` again for the next frontier — or dispatches `/xp-sprint-review` when none remain. `/xp-story-close` itself only merges and cleans up; it never promotes the next story.

Because hooks are global and the SMM is stored under `XP_AGENTS_DATA` (shared across worktrees), every teammate automatically gets:

- Full session context at spawn — teammates are independent `claude -p` processes, so they never hit SubagentStart; the SessionStart hook gives them XP values + `TEAMMATE_GUIDE.md` + the rendered SMM
- `working_on` conflict detection across teammates
- Commit-gated review cycle enforcement (same gates as solo)
- Decisions and concerns visible to every other agent
- A team-wide retrospective at next session start

---

## Configuration

xp-agents works out of the box with zero configuration. It is opinionated — all enforcement is always on. If a gate is annoying, the solution is to fix the gate, not make it optional.

---

## Development setup

**The gates do not exist until you run this.** `lefthook install` writes the git hooks — nothing does that for you, and a clone that skips it commits and pushes ungated, silently. The commit gate runs lint, format, types and the test files you staged (~12s plus those tests); the full suite runs on **push**, which is where every story close lands it.

```bash
make setup
```

This verifies `pytest -n auto` actually works (however it's installed — pipx below is the recommended route, not a requirement) and installs the lefthook hook. It's idempotent; safe to run again.

The shipping plugin code is **stdlib-only** — every script under `plugins/xp-agents/` runs on Python 3.11+ with no `pip install`. The test suite is allowed external runners (it doesn't ship). If `make setup` reports `pytest -n auto` isn't working, the recommended fix is `pipx`:

```bash
# One-time tooling install (isolated venv, on PATH, no Homebrew conflict):
brew install pipx                    # if not already installed
pipx install pytest
pipx inject pytest pytest-xdist      # parallel test execution
```

You do not need to pre-run the suite yourself — that's what the gate is for. Once `make setup` has run:

```bash
# Run the full suite in parallel (~7,600 tests as of v5.0.0):
pytest -n auto

# Or sequentially via unittest (no pytest required; much slower than the
# parallel run above, which itself measured 432s here):
python3 -m unittest discover -s plugins/xp-agents/tests -p "test_*.py"
```

`lefthook` then runs `pytest -n auto` on every **push** (the commit gate is lint, format, types and the test files you staged — the whole suite measured 432s here, too slow to pay per increment). If `pytest` stops working on PATH, lefthook will fail loud — reinstall it via the steps above, or set `LEFTHOOK=0 git push ...` to bypass for an emergency.

Run a single file: `pytest plugins/xp-agents/tests/hooks/test_session_start_core.py`.
Run a single test: `pytest plugins/xp-agents/tests/hooks/test_session_start_core.py::TestSessionStart::test_clear_source_returns_context`.

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

The five values xp-agents ships are Communication, Simplicity, Feedback, Courage, and **Honesty** — and when they conflict, the precedence is `Honesty > Courage > Simplicity > Feedback > Communication`. Honesty sits at the top because it is what makes the other four mean anything.

A standup where agents report "everything is fine" when tests are failing is worse than no standup — it creates false confidence. A retrospective where no one raises problems produces comfortable fiction. The difference between honest and dishonest teams isn't incremental. It's multiplicative.

| XP Value | Without Honesty | With Honesty |
|---|---|---|
| **Communication** | Agent reports "auth complete." Integration fails — 3 tests red. **Cost: 1 wasted session.** | Agent reports "auth 70% — token refresh not done, 3 tests failing." Other agent pivots. **Cost: zero.** |
| **Feedback** | Reviewer writes "LGTM" on `catch(e) {}`. Pattern spreads. DB goes down — no logs. **Cost: 3 hours + failed demo.** | Reviewer writes a `concern`. Fixed in 5 minutes. |
| **Simplicity** | Agent builds `AbstractEndpointFactory` for one endpoint. **Cost: 200 lines of dead abstraction.** | Agent writes a plain function. Notes "will extract if we add a second." |
| **Courage** | Agent notices single-tenant schema, stays quiet. Three sessions later: 14 files, 23 broken tests. | Agent raises a `concern`. Fixed in 30 minutes. |

xp-agents enforces honesty through data, not aspiration:

- **Honesty signals in the retro** — the retrospective receives concrete sequence-based metrics: longest streak of code writes without a test run, code commits without a recorded security check at story/close boundaries, code-write-to-concern ratio, whether assumptions were stated, and whether a final status was recorded. The retro uses these to flag specific honesty gaps, not vague patterns.
- **Quality review skill** — courage check: were review findings skipped? Drift management: do code changes contradict recorded decisions?
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
| **TDD** | Deterministic: Stop hook blocks if tests are failing; TDD order check on every Write/Edit; test results parsed from Bash output for 24 runners across Python, JS/TS, Go, Rust, Swift, JVM, Ruby, PHP, .NET, Dart, Elixir, and C/C++ | Stop hook, PreToolUse:Write, PostToolUse:Bash |
| **Pair Programming** | Per-increment quality review — an independent code reviewer self-finds correctness, then checks reuse, quality, efficiency, courage, drift, and debt awareness | `/xp-quality-review`, `xp-code-reviewer` |
| **Planning Game** | Plan reviewer checks size, TDD ordering, milestone boundaries, decision conflicts. Three-layer marker enforcement: PostToolUse:ExitPlanMode and SubagentStop:Plan write the gate; PreToolUse:Write blocks until cleared | `/xp-review-plan`, `xp-plan-reviewer`, `/xp-work-selection` |
| **Small Releases** | Deterministic: commit size check on `git commit` | PostToolUse:Bash |
| **Coding Standards** | Lint after every write; convention tracking; cross-agent conflict detection; deterministic secret-pattern scan on staged diffs at commit | PostToolUse:Write, PreToolUse:Bash |
| **Continuous Integration** | Test success and failure parsed from Bash output and PostToolUseFailure; Stop hook blocks on failing tests | PostToolUse:Bash, PostToolUseFailure:Bash, Stop hook |
| **Refactoring** | Commit gate blocks until `/xp-quality-review` runs, once 2+ code files changed since the last review; on story cadence it defers to `/xp-story-close` instead. `[release]`/`[chore]`/`[sprint-direct]`-prefixed messages bypass for legitimate maintenance | PreToolUse:Bash, `/xp-quality-review` |
| **Simple Design** | Plan reviewer flags oversized plans; `/xp-quality-review` required at commit for code changes | `xp-plan-reviewer`, PreToolUse:Bash |
| **Collective Code Ownership** | Prompt nuggets inject new signal events at each user prompt; tiered context at subagent spawn (XP values everywhere, plus Intent+Constraints for Explore, full SMM for `xp-code-reviewer`/Plan, an SMM pointer for generic agents); CLI teammates share the same SMM across worktrees | UserPromptSubmit, SubagentStart |
| **On-Site Customer** | Every user prompt logged as a `customer_input` event; work selection triages questions, Try items, and goals | UserPromptSubmit, `/xp-work-selection` |
| **Retrospective** | Keep/Fix/Try at session start with XP values as analytical lenses; runs unconditionally (seed retro on fresh projects) | SessionStart, `xp-retrospective` |

### Token Cost Model

| Source | Per-occurrence | Frequency | Mitigation |
|---|---|---|---|
| Prompt nugget (UserPromptSubmit) | 50-100 tokens | Every user prompt | Watermark-based, only new signal events |
| SessionStart + kickoff | 2,000-5,000 tokens | Once per session | One-time cost (retro + goals + housekeeping) |
| Retrospective subagent | 10,000-20,000 tokens | Once per session | Only when unanalyzed events exist |
| `/xp-quality-review` at commit | 30,000-60,000 tokens | Once per commit with ≥2 changed code files | Threshold skips small changes; story cadence moves it to `/xp-story-close` |
| `/code-review` at close | 30,000-60,000 tokens | Once per `/xp-{sprint,plan,free}-close` | Threshold-gated on the cumulative close diff |

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

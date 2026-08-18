# Architecture

## Core Concept

Hooks-driven Claude Code plugin. XP practices enforced through command hooks (deterministic) and plugin subagents (judgment). Broadcast event log (SMM) replaces point-to-point mailboxes.

## Subsystem Doctrines

This document covers the plugin's runtime architecture (hooks, SMM, injection, lifecycle). Three subsystems have their own declarative doctrine docs that describe how each works in detail:

- **[`ACCEPTANCE_TESTING_DOCTRINE.md`](ACCEPTANCE_TESTING_DOCTRINE.md)** — what "done" means, the two-loops model (commit + story), `acceptance_execution` schema, surface-coverage policy, capstone stories for milestone-level acceptance.
- **[`BRANCHING_DOCTRINE.md`](BRANCHING_DOCTRINE.md)** — branch / sprint / story / free / plan branch shapes, the Stage 0/1/2/3 model, gate + auto-create discipline, user namespacing, `[release]` / `[chore]` / `[sprint-direct]` commit-prefix escape hatches.
- **[`SECURITY_REVIEW_DOCTRINE.md`](SECURITY_REVIEW_DOCTRINE.md)** — two-tier security review (Tier 1 deterministic patterns per commit, Tier 2 LLM `/security-review` over the cumulative diff at every sprint/plan/free close), separation from quality review, findings recording shape.

Each doctrine doc is the authoritative reference for its subsystem; design-history / migration narratives live in `docs/completed/`.

## SMM Storage

```
${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/smm/
├── events.jsonl              ← append-only, one JSON event per line
├── shared_mental_model.json   ← curated four-pillar view, written by housekeeping
├── system_context.json       ← product/system description (architecture, constraints, branching stage)
├── execution_plan.json       ← ordered milestones with change zones and design context
├── sprint.json               ← active sprint stories, file domains, acceptance criteria
├── session_history.json      ← rolling session summaries for the next kickoff
├── adoption.json             ← durable adopted/deferred ledger (survives event-log compaction)
├── .curation-watermark       ← last-curated event position (for housekeeping + compaction)
├── .coordination.json        ← per-agent working_on for O(1) conflict detection
├── .needs-kickoff                    ← gate marker, cleared by /xp-kickoff
├── .plan-awaiting-review             ← plan review gate marker, cleared by plan reviewer preload
├── .review-cycle-{agent_id}.json     ← review flags, keyed on the REVIEWING SESSION's checkout
├── .review-watermark-{agent_id}.json ← the sha the last review measured from, keyed on the TARGET REPO
├── events.lock                       ← flock for atomic appends
└── retrospectives/                   ← Keep/Fix/Try session artifacts (.json)
```

`XP_AGENTS_DATA` is the SMM data root (defaults to `~/.xp-agents/data/`). It is deliberately NOT `CLAUDE_PLUGIN_DATA`: that resolves under `~/.claude/plugins/data/`, which `claude plugin uninstall` deletes by default, so the project's memory would sit one uninstall away from silent loss. Legacy plugin-data roots are still READ, and an SMM found there is **relocated out** — `init.sh` copies the whole tree to the safe root, leaves the original in place, and writes a forward pointer. It declines to relocate while a teammate looks live against the legacy tree and resolves there instead; that decline can be permanent, because the liveness signal is a worktree DIRECTORY and cleanup refuses to remove one whose branch never merged. `XP_SMM_MIGRATE=off` suppresses relocation (so a tool can report state without changing it) and `XP_SMM_MIGRATE=force` relocates despite the liveness signal — a call only a human should make. `scripts/migrate_smm_root.py` is that human-facing surface: it reports what is holding the SMM back and drives `init.sh` through `XP_SMM_MIGRATE` via `--confirm` / `--confirm --force`, deliberately implementing no copying of its own. Per-project isolation via `project-id` derived from `git rev-parse --git-common-dir`. Shared across worktrees and teammates.

### Marker Write Locality

State markers (`.needs-kickoff`, `.plan-awaiting-review`, `.close-cycle-active`, etc.) are written from exactly two places:

- **Skills** call the `write_marker` / `consume_marker` Bash helpers in `plugins/xp-agents/skills/_preload_base.sh`. These wrap `markers.py` and pass values via `sys.argv` so content with quotes/backslashes is safe.
- **Hooks** call `markers.marker_write` / `markers.marker_consume` directly in Python.

Skills MUST NOT write markers inline (`echo > .marker`, `python3 -c 'import markers; ...'`) — the helpers carry the safe-quoting and SMM-path-resolution discipline, and centralizing the call sites keeps marker semantics inspectable. The `markers.py` CLI exists for test fixtures (constructing a known marker state in unit tests); production code paths must go through the helpers. New markers must be declared as constants in `markers.py` before any caller references them.

### Four-File Architecture

Beyond `events.jsonl`, three persistent files live in the SMM directory:

| File | Created By | Updated By | Purpose |
|---|---|---|---|
| `system_context.json` | `/xp-system-context` | `/xp-system-context` (re-run after architecture changes) | Product/system description — architecture, components, constraints |
| `execution_plan.json` | `/xp-plan` | `/xp-sprint-review` (milestone delivery markers) | Ordered milestones with change zones, impact zones, design details |
| `sprint.json` | `/xp-sprint-start` | `/xp-accept` (story status) | Active sprint stories with context gradient — file domains, interface contracts |

All three are JSON with schema validation and CLI tools (`system_context_cli.py`, `plan_cli.py`, `sprint_cli.py`). System context and execution plan are stable across sprints; sprint.json is ephemeral (one active at a time).

**Sprint state vs. sprint events.** `sprint.json` holds only the *current* sprint's stories and their statuses (planning / in_progress / reviewing / done / deferred) — it is a mutable snapshot of the active sprint, replaced wholesale by `/xp-sprint-start` each cycle. Sprint *lifecycle transitions* (start/end with velocity data) are append-only records in `events.jsonl` as `type: sprint`, written by `subagent_stop._handle_sprint_review_done` after `xp-sprint-reviewer` completes. Historical sprint outcomes survive in events.jsonl after sprint.json is rewritten.

## Event Types

| Type | Generated By | Purpose |
|---|---|---|
| `goal` | Skill (xp-work-selection) + customer | Project north star |
| `customer_input` | Hook (UserPromptSubmit) | User's exact prompt |
| `customer_intent` | Skill (xp-work-selection) | Distilled request — open / delivered / superseded |
| `status` | Hook (PostToolUse, auto) + agent | What's happening, `working_on` files |
| `decision` | Agent + subagent (plan reviewer) | Architectural choices |
| `convention` | Agent | Team standards |
| `concern` | Subagent (quality reviewer) + agent | Problems needing attention |
| `discovery` | Agent | Unexpected findings |
| `question` | Agent + subagent (plan reviewer) | Customer input needed: 🔴 blocking, 🟡 assumed, 🟢 info |
| `answer` | Agent | Response to a question event |
| `assumption` | Agent + subagent (plan reviewer) | Stated beliefs — escalates if contradicted |
| `debt` | Subagent (quality reviewer, retrospective) | Acknowledged tradeoff |
| `commit` | Hook (PostToolUse:Bash, auto) | One record per `git commit` — sha, message, story id. Emitted by three paths that all share `commit_event.make_commit_event`: the attributed commit path, the catch-up observer, and the close-cycle merge emitter |
| `sprint` | Hook (subagent_stop._handle_sprint_review_done) | Sprint lifecycle events (start/end with velocity data) |
| `session_started` | Hook (SessionStart) | Session boundary anchor — bounds "this session's" event reads |
| `session_end` | Hook (SessionEnd) | Duration, unresolved items, final status flag |
| `session_summary` | Skill (xp-end-session) | Authored session wrap-up, appended to `session_history.json` |
| `retrospective` | Subagent (retrospective) | Keep/Fix/Try analysis |

All 18 types are enumerated in `event_schema.VALID_TYPES`; anything outside that
set is rejected at write time.

## Curated SMM (shared_mental_model.json)

Four-pillar model, curated by housekeeping (LLM judgment via `smm_cli.py save`). Not auto-generated — housekeeping reads curation data, merges with existing SMM, and writes a concise (~300-700 token) JSON document with schema validation.

Four pillars:
- **Intent** — Project goals and active customer intents
- **Constraints** — Confirmed decisions, conventions, and architectural boundaries
- **Risks** — Concerns, blocking questions, unverified assumptions, technical debt (with severity)
- **Wisdom** — Lessons learned, retrospective insights, behavioral experiments

### Context Injection

Context reaches the agent through three mechanisms:
- **Prompt nuggets** (UserPromptSubmit via `prompt_nugget.py`): lightweight injection of new signal events since last prompt (~50-100 tokens). Watermark-based — only new concerns, decisions, and discoveries.
- **Skill preload injection** (PreToolUse via `preload_injection.py`): a skill's own preload state, run by the hook and returned as `additionalContext`. Since sprint-007 this is the **sole** channel — no `SKILL.md` carries an instruction-time `!` line, because the second harness never expanded one (only a skill's LOCATOR reached the model there). See `docs/completed/PRELOAD_DELIVERY_MECHANISM.md`.
- **Tiered context injection** (SubagentStart via `subagent_start.py`): every tier receives `XP_VALUES.md` — never the process guide, which SubagentStart does not load. On top of the values: Explore gets Intent+Constraints; `xp-code-reviewer` and unknown/ad-hoc types (including `Plan`) get the full rendered SMM; `general-purpose` / `workflow-subagent` / `claude` get the reference tier (a one-line pointer to run `smm_cli.py render` themselves); `xp-retrospective` and `xp-housekeeper` get path strings to their preload inputs; every other `xp-*` agent gets values only, because its data arrives in the Agent prompt the spawning skill builds from its injected preload state. CLI teammates do **not** appear here at all — they are separate `claude -p` processes and take the SessionStart path instead (see §Teammate Detection).

## Hook Map

All hooks are `type: "command"`. Judgment work uses plugin subagents.

### Command Hooks

| Event | Matcher | Script | What It Does |
|---|---|---|---|
| **SessionStart** | `startup\|resume\|compact\|clear` | `session_start.py` | Init SMM directory, append `session_started`, write `.needs-kickoff` marker, inject GUPP + `XP_VALUES.md` (NO SMM, NO process guide — deferred to kickoff; on `compact` only, the SMM and process guide are re-injected) |
| **SessionStart** | `startup\|resume\|compact\|clear` | `retrospective.py` | Compute session stats, write `.retro-input.json` |
| **UserPromptSubmit** | | `user_prompt_log.py` | Log as customer_input event |
| **UserPromptSubmit** | | `kickoff_gate.py` | Block prompts until `/xp-kickoff` runs (allows the command itself through) |
| **UserPromptSubmit** | | `prompt_nugget.py` | Inject prompt nuggets — new signal events since last prompt (watermark-based, ~50-100 tokens) |
| **PreToolUse** | `Write\|Edit\|MultiEdit` | `pre_tool_write.py` | Conflict blocking (via `.coordination.json`), TDD order check, plan review gate (`.plan-awaiting-review` marker file) |
| **PreToolUse** | `Bash` | `pre_tool_bash.py` | Tier 1 deterministic security scan of the staged diff (fail-closed), staged-lint gate, commit-gated review cycle, branch-protection advisories, cd-into-worktree-git advisory. The review gate arms at `commits.REVIEW_CYCLE_THRESHOLD` (2) changed code files since the last review and blocks on `quality_review_done` alone — `/xp-quality-review` is the whole per-commit gate. On **story** cadence it does not block: it emits a deferral advisory and the review relocates to `/xp-story-close`. No file-modification coordination gate — pre_tool_write covers Edit/Write; trust+merge handles the rest (sprint-105 decision). Also carries the reviewer read-only guard (`pre_tool_bash_reviewer_guard.py`): `xp-code-reviewer` and `xp-close-reviewer` are refused any non-allowlisted `git`, after two incidents where a review's `git reset` mutated shared state |
| **PreToolUse** | `Skill` | `pre_tool_skill.py` | Prepare review guidance for skills; **blocks** a teammate from a lead-owned lifecycle skill, and an `/xp-accept` with no evidence |
| **PreToolUse** | `Skill` | `preload_injection.py` | Run the invoked skill's own preload and return its state as `additionalContext` — the sole channel since the `!` lines were deleted. `skill_preload_map.py` resolves skill → argv + environment. Registered on `Bash` too in the derived variant (`hooks.codex.json`), where the model reaches a skill by reading its `SKILL.md` rather than by a tool call. Runs in parallel with `pre_tool_skill.py`, so it cannot observe that handler's refusal — it recomputes the same verdict itself and skips the preload when the call will be blocked (story-019) |
| **PreToolUse** | `EnterPlanMode` | `pre_tool_plan_mode.py` | Schedule gate — block plan entry until `/xp-schedule` promotes a frontier |
| **PostToolUse** | `Write\|Edit\|MultiEdit` | `post_tool_use.py` | Auto status/working_on, conflict detection |
| **PostToolUse** | `Write\|Edit\|MultiEdit` | `lint_check.py` | Run project linter, inject errors as additionalContext |
| **PostToolUse** | `Bash` | `bash_post_tool.py` | Commit bookkeeping (review cycle reset), test result parsing. On a commit-shaped command `commit_handling._handle_commit` records the commit it can ATTRIBUTE to that command. On every OTHER Bash `commit_observer.observe` catches up on commits that moved HEAD while nothing was watching — a backgrounded commit lands after its own tool call returned, so the launching hook cannot see it. The two make different claims and carry different guards: the first proves "this command produced this commit" (reflog, freshness, message), the second only "a commit is reachable from HEAD with no event, and here is its message read back from git". The observer's cheap path is a `.git/HEAD` file read (`git_head.py`), ~0.2 ms, so watching every Bash costs no fork |
| **PostToolUse** | `Skill\|Agent` | `review_cycle_done.py` | Set review cycle flags — `simplify_done` from the `/code-review` skill only. Every entry in this hook's allowlist records at LAUNCH (a Skill/Agent call returns when the tool returns, which for an inline skill and for a backgrounded Agent-tool subagent is before any work has run), so nothing that gates a commit may live here: `quality_review_done` is set on `SubagentStop` instead. Emits canonical lifecycle events (simplify/security-review/plan-review/assign/housekeeping); nudges next step via `additionalContext`; injects PROCESS_GUIDE.md after `xp-housekeeper` completes |
| **PostToolUse** | `Skill\|Agent` | `accept_terminal.py` | Drain the accept-in-flight marker on `/xp-accept`'s terminal dispatch (`/xp-schedule` or `/xp-sprint-review`), via exact-match allowlist |
| **PostToolUse** | `ExitPlanMode` | `post_tool_exit_plan.py` | Write `.plan-awaiting-review` marker, capture plan file path, nudge `/xp-review-plan` |
| **PostToolUse** | `AskUserQuestion` | `question_answered.py` | Record user answer to clarification question |
| **PostToolUseFailure** | `Bash` | `bash_failure.py` | Capture failed test runs. `async: true` |
| **PostToolUseFailure** | `AskUserQuestion` | `question_answered.py` | Record clarification when question is dismissed |
| **SubagentStart** | | `subagent_start.py` | Tiered context injection + `XP_VALUES.md` for every tier (Explore: Intent+Constraints; `xp-code-reviewer`/Plan/unknown: full SMM; generic catch-alls: SMM reference pointer; other `xp-*`: values only) |
| **SubagentStop** | | `subagent_stop.py` | Record completion + conflict detection. Owns the review cycle's completion signal via `review_cycle_legs.update_review_cycle_flags`: an `xp-code-reviewer` completion sets `quality_review_done`, records the code files that review covered (so its own fixes don't re-arm the commit gate) and emits `qr_complete` — this is the only event in the review family that fires after the work has run. Handles xp-* subagent completions before the is_xp_agent skip: `_handle_housekeeping_done` (consume KICKOFF + NEEDS_HOUSEKEEPING + NEEDS_SPRINT markers, emit completion event — does NOT return context; SubagentStop `additionalContext` is routed to the finished subagent, not the parent), `_handle_sprint_review_done` (record sprint end + velocity), `_handle_close_reviewer_done` (consume CLOSE_CYCLE_ACTIVE), `_handle_plan_review_done` (emit the plan_reviewed completion record on every path — this leg is its sole producer since `/xp-review-plan` went inline — and additionally write the ASSIGN_PENDING marker on teammate-mode plans; returns None, the reviewer's own Next-step block tells the main agent to run `/xp-assign`). Writes `.plan-awaiting-review` marker file for Plan subagent. |
| **Stop** | | `tdd_stop_gate.py` | Block if tests failing |
| **Stop** | | `sprint_stop_gate.py` | Sprint lifecycle cascade (accept → review): blocks on in-progress + accept marker → run /xp-accept; sprint complete + no sprint_end event → run /xp-sprint-review |
| **Stop** | | `close_cycle_stop_gate.py` | Block when CLOSE_CYCLE_ACTIVE marker present — nudges agent to run /security-review then invoke xp-close-reviewer. Defers on ASKING_USER. Records a high-severity concern + emits stderr if `stop_hook_active` bypass coincides with an active marker |
| **Stop** | | `housekeeping_stop_gate.py` | Block if housekeeping hasn't run (defers when ASKING_USER set) |
| **Stop** | | `session_end_warning.py` | Soft warning: unresolved concerns, missing final status |
| **Stop** | | `teammate_stop_gate.py` | Block teammates from stopping with uncommitted changes or incomplete review cycle |
| **TeammateIdle** | | `teammate_idle.py` | TDD enforcement for teammates (exit 2 if tests failing) |
| **TaskCompleted** | | `task_completed.py` | TDD enforcement for task completion (exit 2 if tests failing) |
| **WorktreeCreate** | | `worktree_create.py` | Set up worktree branch base for teammate spawning |
| **PreCompact** | | `pre_compact.py` | Back up SMM state |
| **PostCompact** | | `compact.py` | Compact event log (watermark-based, retains recent + session_end + referenced events) |
| **SessionEnd** | | `session_end.py` | Append session_end event |
| **SessionEnd** | | `compact.py` | Compact event log at session end. `async: true` |

### Plugin Subagents (agents/ directory)

Plugin subagents with full tool access. Each is spawned by an inline skill that threads the hook-injected preload state into the Agent prompt — no skill forks any more (story-013 converted the last three).

| Subagent | Trigger | Method | Purpose |
|---|---|---|---|
| `xp-code-reviewer` | `/xp-quality-review` skill (inline) | Agent tool | Independent code review — code-review accountability, drift management, debt awareness, XP-lens review |
| `xp-retrospective` | `/xp-kickoff` Step 1 | Agent tool (synchronous) | Keep/Fix/Try analysis, session stats, debt escalation. Reads `.retro-input.json`; emits a seed retrospective on a fresh project |
| `xp-plan-reviewer` | `/xp-review-plan` skill (inline) | Agent tool | Plan size, TDD ordering, decision conflicts. Writes assumption/question/decision events |
| `xp-housekeeper` | `/xp-kickoff` Step 6 | Agent tool (synchronous) | Four-pillar SMM curation with LLM judgment |
| `xp-sprint-reviewer` | `/xp-sprint-review` skill (inline) | Agent tool | Sprint review: what shipped vs planned, execution_plan.json milestone updates, velocity |
| `xp-close-reviewer` | `/xp-story-close`, `/xp-sprint-close`, `/xp-plan-close`, `/xp-free-close` | Agent tool | Holistic close-review at story/sprint/plan/free integration points (mode-aware). The close skills are inline and spawn it — they are not themselves forked |
| `xp-system-analyzer` | `/xp-system-context` skill (inline) | Agent tool | Autonomous codebase analysis — product, architecture, constraints. (The *skill* is `xp-system-context`; the agent file is `agents/xp-system-analyzer.md`) |

### Skills

Every skill is inline: it runs in the main agent for full tool access (AskUserQuestion, Bash, Agent), and a delegating skill *spawns* its subagent with the Agent tool rather than forking. No skill carries `context: fork` — story-013 converted the last three (`/xp-review-plan`, `/xp-sprint-review`, `/xp-system-context`) because hook-side preload injection does not cross a fork boundary.
- `/xp-kickoff` — orchestrator, sequences retro → work selection → housekeeping at session start
- `/xp-work-selection` — sprint setup, work selection, retro Try items
- `/xp-quality-review` — orchestrator: spawns `xp-code-reviewer` subagent for independent review (code-review accountability, drift, debt, XP-lens), resolves plan concerns inline
- `/xp-plan` — create/update execution plan with milestones (`execution_plan.json`)
- `/xp-sprint-start` — create sprint from execution plan milestones (`sprint.json`)
- `/xp-accept` — acceptance testing gate, mark stories done/deferred, dispatch `/xp-story-close` per accepted story; post-loop dispatches `/xp-schedule` for the next frontier (or `/xp-sprint-review` when none remain)
- `/xp-schedule` — sole owner of `scheduled → in-progress`: promote the next dependency-satisfied frontier, decide mode (solo vs CLI teammates), set each story's `execution_mode`, and (solo) JIT-create the branch. Runs before planning; state-derived gates (write + EnterPlanMode) enforce it
- `/xp-assign` — per-story: read the most-recent per-story plan, target the lowest-id un-spawned teammate story, create its branch, and spawn ONE teammate via `spawn_teammate.py` (per-story plan→review→spawn loop, NOT a batch fan-out). Teammate-only — mode selection and solo branching belong to `/xp-schedule`. Auto-runs after `/xp-schedule` promotion and `/xp-review-plan` (one story at a time)
- `/xp-story-close` — per-accepted-story: review (close-reviewer mode=story), merge into sprint base via `close_common.py merge`, cleanup teammate worktree if present. Does NOT promote or branch the next story
- `/xp-sprint-close` — push sprint branch, fork close-reviewer, merge into target, cleanup
- `/xp-plan-close` — push plan branch, fork close-reviewer, merge into primary, archive plan
- `/xp-free-close` — push free branch, fork close-reviewer, merge into primary, cleanup
- `scripts/close_common.py` — shared close pipeline used by all four close skills above; eliminates the ~80% bash duplication that previously lived across SKILL.md files. Seven subcommands: `preflight`, `push`, `create-pr`, `hook-present`, `diff-command`, `close-review-gate`, `merge`

`XP_VALUES.md` is injected directly at SubagentStart, for every tier. `PROCESS_GUIDE.md` is a separate payload with two callers, neither of them SubagentStart: `review_cycle_done.py` (after `xp-housekeeper` completes) and `session_start.py` (on the `compact` source only).

### Notifications

Desktop notifications for 🔴 blocking questions fire inline at the `append_event()` choke point via `resolution.py` (macOS `osascript` / Linux `notify-send`).

### Recursion Prevention

All subagent names start with `xp-`. Plugin name is `xp-agents`, so agent_type becomes `xp-agents:xp-*`. Command hooks check `agent_type.startswith("xp-")` and skip.

## Injection Architecture

| When | What's Injected |
|---|---|
| Session start | GUPP + `XP_VALUES.md` (NO SMM, NO process guide — deferred to kickoff) |
| After housekeeping | Agent Reads curated SMM file directly (housekeeping step 8) |
| After housekeeping | PROCESS_GUIDE.md via PostToolUse:Skill\|Agent (`review_cycle_done.py`) when `xp-housekeeper` completes |
| Each user prompt | Prompt nuggets — new signal events since last prompt (watermark-based, ~50-100 tokens) |
| Before Write/Edit | Conflict check (blocks), TDD order check, plan review gate — all file-based, zero event log reads |
| Before Bash | Tier 1 security patterns + staged lint, then the commit-gated review cycle (blocks until `quality_review_done`; defers on story cadence), cd-into-worktree-git advisory. NO Bash file-modification gate — see the PreToolUse:Bash row in the Hook Map (sprint-105 dropped it; trust+merge model) |
| Subagent spawn | `XP_VALUES.md` for every tier, plus: Explore→Intent+Constraints; xp-code-reviewer/Plan/unknown→full SMM; general-purpose / workflow-subagent / claude→SMM reference pointer; xp-retrospective/xp-housekeeper→preload path strings; every other `xp-*` agent→nothing extra, because its data arrives in the Agent prompt the spawning skill builds from its injected preload state. Teammates are not subagents and never reach this hook |
| After compaction | Full SMM + PROCESS_GUIDE.md re-injection via SessionStart (`compact` source) |

Injection order in SessionStart `additionalContext`:
1. GUPP ("Resume immediately")
2. `XP_VALUES.md`
3. On the `compact` source only: rendered SMM, then `PROCESS_GUIDE.md`

After the forked `xp-housekeeper` subagent finishes, the post-completion injection split is:

- **SubagentStop** (`subagent_stop._handle_housekeeping_done`) consumes the KICKOFF and NEEDS_HOUSEKEEPING markers and emits a status event. **It does NOT return context** — SubagentStop's `additionalContext` is delivered to the finished subagent (continuing its turn), not the parent, so it cannot inject into the main agent.
- **PostToolUse:Skill\|Agent** (`review_cycle_done.py`) fires for the same Agent-tool completion, detects `subagent_type == xp-housekeeper`, and returns PROCESS_GUIDE.md as `additionalContext`. The curated SMM is already in context because housekeeping step 8 has the agent Read the file.

All injection is via `additionalContext` except the curated SMM file (Read by agent during housekeeping).

## Conflict Detection

Five structural patterns detected deterministically by `post_tool_use.py` and `subagent_stop.py`:

| Pattern | Method |
|---|---|
| Overlapping `working_on` | Array comparison across status events |
| Assumption contradicted by discovery | Reference chain traversal |
| Convention violation | Decision references convention but diverges |
| Stale question | 🔴 question with no answer after 20+ events |
| Superseded decision | Two decisions, same topic, no concern between |

Critical conflicts → exit 2 (block). Non-critical → event log only.

## Session Flows

### Session Start
```
SessionStart → session_start.py: init SMM directory, write .needs-kickoff marker
               inject GUPP + XP_VALUES.md (NO SMM, NO process guide in context)
             → retrospective.py: prepare .retro-input.json

User types   → kickoff_gate.py blocks: "Run /xp-kickoff"
             → User runs /xp-kickoff

/xp-kickoff:
             0. Prepare: system-context bootstrap, branching stage, orphan-branch triage
             1. Retro (always) → xp-retrospective agent, synchronously
             2. Session mode (free vs sprint)
             3. Execution plan  → /xp-plan          (sprint mode, conditional)
             4. Sprint start    → /xp-sprint-start  (sprint mode, conditional)
             5. Work selection (goals, question triage) → /xp-work-selection
             6. Housekeeping → xp-housekeeper agent (curates four-pillar SMM)
             7. Render the curated SMM; .needs-kickoff cleared on housekeeper completion

Next prompt  → Gates pass through (marker cleared)
             → Prompt nuggets inject new signal events
             → Work begins with curated SMM
```

### Mid-Session
```
UserPrompt   → prompt_nugget.py: inject new signal events since last prompt
PreToolUse   → pre_tool_write.py (Write/Edit): conflicts, TDD, plan review gate (all file-based)
             → pre_tool_bash.py (Bash): Tier 1 security scan, staged lint,
                                        commit review gate, cd-into-worktree-git advisory
Tool executes
PostToolUse  → post_tool_use.py: auto status, conflicts (Write/Edit)
             → lint_check.py: linter (Write/Edit)
             → bash_post_tool.py: commit/test analysis (Bash)
             → review_cycle_done.py: set review-cycle flags + canonical lifecycle events; inject PROCESS_GUIDE.md after xp-housekeeper (Skill|Agent)
```

### Stop
```
Stop         → tdd_stop_gate.py: block if tests failing
             → sprint_stop_gate.py: sprint lifecycle cascade (accept → review)
             → close_cycle_stop_gate.py: block while CLOSE_CYCLE_ACTIVE marker present
             → housekeeping_stop_gate.py: block if housekeeping hasn't run
             → session_end_warning.py: soft warning (unresolved concerns)
             → teammate_stop_gate.py: block teammates with uncommitted changes
```

Note: LLM security review is Tier 2 — `/security-review` at `/xp-{sprint,plan,free}-close` Step 4, over the cumulative close diff. `/xp-accept` and `/xp-story-close` never fire it (`xp-story-close/SKILL.md` Step 4 is literally "Security Review (skipped)"), because every story-close is dispatched inside an active sprint whose close already covers it. The per-commit gate enforces `/xp-quality-review` alone via `pre_tool_bash.py` + the review-cycle marker. See PreToolUse:Bash in the Hook Map and `SECURITY_REVIEW_DOCTRINE.md`.

### Subagent Lifecycle
```
SubagentStart → subagent_start.py: tiered injection; XP_VALUES.md on EVERY tier
                Explore: Intent+Constraints only (~200 tokens)
                xp-code-reviewer: full SMM (needs Constraints for drift management)
                Default (Plan / unknown ad-hoc types): full SMM
                general-purpose / workflow-subagent / claude: SMM reference pointer
                  (a `smm_cli.py render` command line, not a render) and no
                  sequential-discipline note — the one tier that omits it
                xp-retrospective: SMM_DIR + RETRO_INPUT path strings
                xp-housekeeper: SMM_DIR + CURATION_INPUT + work-selection block
                Other xp-* agents: values only (their state is threaded into
                  the Agent prompt by the skill that spawns them)
                CLI teammates: never reach this hook — separate `claude -p`
                  processes, served by SessionStart (XP Values + TEAMMATE_GUIDE
                  + rendered SMM)
SubagentStop  → subagent_stop.py: record completion, conflict detection
              → xp-* subagent handlers (consume markers, emit lifecycle events):
                  housekeeping → consume KICKOFF + NEEDS_HOUSEKEEPING + NEEDS_SPRINT
                  sprint-reviewer → record sprint end + velocity
                  close-reviewer → consume CLOSE_CYCLE_ACTIVE
                  plan-reviewer → emit plan_reviewed; ASSIGN_PENDING if teammate
              → Write .plan-awaiting-review marker file for Plan subagent
```

## Plugin Structure

```
plugins/xp-agents/
├── .claude-plugin/plugin.json       ← plugin manifest
├── XP_VALUES.md                     ← XP values (Honesty, Communication, Simplicity, Feedback, Courage)
├── PROCESS_GUIDE.md                 ← process rules for lead/solo agents (skills, commit gates, sprint flow)
├── TEAMMATE_GUIDE.md                ← DO/DON'T/SKIP/KEEP rules for CLI teammates
├── hooks/hooks.json                 ← all hook registrations (command hooks only)
├── agents/                          ← plugin subagents (full tool access)
├── skills/                          ← skills (inline + forked), each with SKILL.md + scripts/
│   └── _preload_base.sh             ← shared preload helpers (dump_smm, dump_guide, dump_diff)
├── scripts/                         ← command hooks + shared modules (Python 3.11+, stdlib only)
└── smm/                             ← SMM engine modules (append, compact, materialize, schema, CLI tools)
```

## Platform Constraints

- All matching hooks run **in parallel** — no ordering between hooks, no `additionalContext` visibility between hooks
- Agent hooks (`type: "agent"`) are documented as working but limited — they support Read/Grep/Glob only (no Bash/Write), return ok/reason decisions, and have a 60-second default timeout. We use command hooks + plugin subagents instead for tasks requiring Bash or extended processing
- Plugin subagents have full tool access and return full conversational response
- `additionalContext` appends after prompt cache — cache is preserved
- PostToolUse supports `additionalContext` and `decision: "block"`
- Prompt/agent hooks use `ok`/`reason` format, NOT `decision`/`block`
- `allowed-tools` gates what the MODEL may run from a skill body, and nothing else. It did once pre-approve the instruction-time `!` preload line via `Bash(*/skills/*/scripts/*)`, but sprint-007 deleted every such line: `preload_injection.py` now runs each preload with `subprocess.run` from inside the hook, which never consults `allowed-tools`. The grant is therefore only load-bearing for a skill that still invokes its own script from a numbered step — a still-open concern tracks which of the 16 carry it as dead permission surface
- **SubagentStop only supports `decision:"block"` or silence** — `decision:"approve"` with `reason` is silently dropped. `additionalContext` is delivered to the finished subagent (continuing its turn), not the parent — so it cannot message the main agent (and can bury a subagent's final message). This limits enforcement options for plan review
- Plugin cache requires version bump to update — `/reload-plugins` alone isn't sufficient if version is unchanged
- File-based coordination (`.retro-input.json`) is a race — design for graceful degradation
- **`${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` are NOT exported into the agent's Bash tool environment** in `claude -p` (and regular `claude`). Claude Code substitutes them when injecting `SKILL.md` content and hook command strings, but raw markdown loaded via our own loaders (e.g. `plugin_loader.load_process_guide`, `plugin_loader.load_teammate_guide`) leaks the literal variable into agent Bash, where it expands to empty. Loaders that inject guide content as `additionalContext` MUST run text through `plugin_loader.expand_plugin_root` first

## Error Handling

Fail loud, never corrupt, always recoverable.

| Scenario | Behavior |
|---|---|
| Malformed event | Materializer skips, emits concern |
| Unknown event type | Rejected at write time — `validate_event` fails on any type outside `VALID_TYPES`, so it never reaches the log or the renderer |
| SMM directory missing | Hooks pass through, next SessionStart recreates |
| Materializer crash mid-write | Atomic write via tempfile + rename |
| Lock timeout (`LOCK_TIMEOUT_SECONDS = 10`, override `XP_LOCK_TIMEOUT_SECONDS`) | `LockTimeoutError` is raised — **never** an unlocked append. Hook callers log-and-swallow it (`_common.append_safe` / `bulk_append_safe`, with a structured trace in `hook_errors.jsonl`) or suppress it (`session_end.py`), so the event is dropped rather than corrupting the log |
| Retrospective with no prior session data | Runs anyway and emits a *seed* retrospective (Keep around adopting XP, Try items as skill suggestions, zero Fix). There is no "insufficient data" short-circuit — kickoff Step 1 never gates on `.retro-input.json` |
| Schema validation failure | Append rejected, stderr error |
| xp-agent subagent | Command hooks skip (recursion prevention) |

## Debt Aging

| Age | Rendering |
|---|---|
| 0-3 sessions | Normal |
| 4-6 sessions | ⚠️ |
| 7+ sessions | 🔴 |

Age computed at materialize time by counting `session_end` events after debt timestamp.

## Event Log Compaction

Compaction runs at three points: after the curated SMM is written (`smm_cli.py save`, covering both forked and inline housekeeping), at session end (`SessionEnd` hook), and during context compaction (`PostCompact` hook). All use the same watermark-based policy:

| Event Type | Retention Rule |
|---|---|
| Status, customer_input | Compact freely |
| Decisions | Retain for 3 sessions, then compact |
| Assumptions, questions | Retain for 5 sessions, then compact |
| Concerns, debt | Retain while unresolved |
| Goals | Retain while unresolved |
| Session_end | Keep last 3 (for aging calculations) |
| Retrospectives | Keep last 2 (archived in `retrospectives/` directory) |
| Resolved items | Compact (resolution events prove they were addressed) |

Only events before the curation watermark are eligible. Events after the watermark are retained unconditionally.

## CLI Teammates

CLI teammates are the **sprint-default parallel execution mode**. When `/xp-schedule` selects parallel work for a frontier, `/xp-assign` spawns CLI teammates one story at a time (independent `claude -p` processes in git worktrees), not Claude Code's `Agent Teams` feature. Mode selection belongs to `/xp-schedule` and happens *before* planning — see §Frontier Scheduling below. Each teammate runs the full hook lifecycle (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SessionEnd), writes its own commits with its own TDD + review cycle, and shares the same SMM as the lead.

**When Agent Teams is preferred instead:** ad-hoc multi-agent research or analysis where teammates need to be co-tenant in a single Claude Code session — e.g., one agent researching while another summarizes for the user, with shared conversation context. CLI teammates can't share conversation state; Agent Teams can't isolate file domains in worktrees. Sprint-driven parallel implementation of stories with non-overlapping file domains is always CLI teammates; everything else stays in Agent Teams (or solo).

SMM at `${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/smm/` is shared across all worktrees and teammates. Because hooks are global:

- Every teammate gets prompt nuggets at each user prompt
- Every teammate's code gets quality reviewer subagent nudges
- Every teammate's `working_on` is tracked for conflict detection
- Every teammate's decisions are visible to all others
- Retrospective analyzes the whole team's session

### Teammate Detection and Enforcement

Teammates are detected by `is_worktree_teammate()`, which has **two legs**:

1. **cwd leg** — the session's `cwd` (hook payload first, then the process cwd as a fallback) contains a `worktree-story-` path segment. Location-independent, since worktrees moved out of the repo to a sibling of the SMM dir.
2. **env leg** — `XP_TEAMMATE_NAME` names a teammate, *and* `spawn_teammate`'s lifetime-scoped `.in-place-active-*` marker is live for that name under the resolved SMM dir. This leg exists for **in-place (solo-delegation) teammates**, whose cwd is the main checkout; without it they would be misread as the lead. `XP_TEAMMATE_NAME` is a documented leaky var, so the marker guard is load-bearing: a leaked env with no live marker is not a teammate, and with neither an `smm_dir` argument nor an explicit `SMM_DIR` the leg fails closed.

The shared helper is `identity.in_place_teammate_name()`, which also backs `tdd_check._reader_scope`, `pre_tool_skill._is_live_teammate`, and `commit_event._resolve_story_id` — so every gate inherits the same guard. Each teammate is an independent `claude -p` CLI process with full hook lifecycle support.

**Hooks that fire for teammates:** SessionStart, SessionEnd, Stop, PreToolUse, PostToolUse, UserPromptSubmit (all hooks fire — full session).
**SessionStart path:** Injects XP Values + TEAMMATE_GUIDE.md + rendered SMM (no kickoff markers, no GUPP).
**SessionEnd path:** Records "teammate completed" event with branch name.

The teammate stop gate (`teammate_stop_gate.py`) blocks teammates from stopping with uncommitted changes or incomplete review cycle.

### Frontier Scheduling and Team Spawn Flow

Mode selection happens at `/xp-schedule`, **before** planning — not at `/xp-assign`. `/xp-schedule` reads the frontier (dependency-satisfied `scheduled` stories) and decides:

**Solo mode** — chosen when the frontier is a single story, or 2+ stories share file domains. `/xp-schedule` promotes the lowest-id story, sets `execution_mode=solo`, JIT-creates its branch, and the lead plans + executes it directly (no `/xp-assign`).

**CLI teammate mode** — chosen when 2+ frontier stories have non-overlapping file domains (user confirms). `/xp-schedule` promotes the whole frontier (`execution_mode=teammate`); the lead then loops plan→review→`/xp-assign` per story, one at a time.

Flow:
1. `/xp-schedule` reads the frontier, picks mode, promotes (`scheduled → in-progress`), sets `execution_mode`; solo also JIT-branches.
2. State-derived gates (write + EnterPlanMode) blocked everything until this ran.
3. Lead enters plan mode for ONE story → `/xp-review-plan`.
4. Teammate mode only: `_handle_plan_review_done` arms `.assign-pending`, so `/xp-assign` runs — it targets the lowest-id un-spawned story, creates its branch, and spawns ONE teammate via `Bash run_in_background` calling `spawn_teammate.py | teammate_output_filter.py`. Lead then loops back to step 3 for the next story (the spawned teammate runs async).
5. Each teammate gets a self-contained prompt and works independently: TDD, review cycle, commits — all in its own worktree.
6. As each teammate's task-notification fires, the precedence is **plan → SPAWN → accept**: the lead spawns any story that is already planned, reviewed and un-spawned before it runs `/xp-accept` on the teammate that just finished, so the background is never empty for a whole close cycle. With nothing left to spawn, it accepts immediately — precedence never stalls acceptance. Each accepted story merges at `/xp-story-close` (close does not promote the next story). Spawns and accepts **interleave** — don't accumulate unaccepted teammates.
7. `/xp-accept`'s post-loop calls `/xp-schedule` for the next frontier, repeating the loop.

## Enforcement vs. Agent Compliance

**Fully enforced (no agent compliance needed):** Prompt nugget injection, status/working_on tracking, Write/Edit conflict detection (via `.coordination.json` in `pre_tool_write.py`; Bash file-mods are NOT gated — see the sprint-105 decision in the PreToolUse:Bash row of the Hook Map; trust+merge handles cross-agent Bash damage at story-close), customer input logging, session bookkeeping, TDD stop gate (`tdd_stop_gate.py`), lint, commit-gated review cycle (`pre_tool_bash.py` + `markers.py` — `/xp-quality-review` is the gate, blocking at 2+ changed code files on commit cadence and deferring to `/xp-story-close` on story cadence; Tier 1 security patterns fire unconditionally, Tier 2 LLM `/security-review` runs at close), plan review nudge via `.plan-awaiting-review` marker, kickoff gate (UserPromptSubmit), reviewer read-only guard (`pre_tool_bash_reviewer_guard.py` — the two reviewer subagents cannot run mutating git), ANSI stripping at write time, event log compaction.

**Agent compliance needed (mitigated by process guide + subagent nudges):** Decision recording, event quality, judgment events (assumptions, questions, discoveries), final status at session end, invoking nudged subagents/skills (quality reviewer, plan reviewer, retrospective), running `/xp-kickoff` sub-skills (retro, goals, housekeeping) when orchestrator directs.

## Event Lifecycle

Resolution via `metadata: {"resolves": ["target-event-id"]}`. Questions resolved by `answer` events with `references`.

| Type | Resolution Pattern | Who Drives Closure | Active → Reference |
|------|-------------------|-------------------|-------------------|
| Goal | `metadata.resolves` | `xp-housekeeper` | Unresolved in A1, completed in R8 |
| Concern | `metadata.resolves` | `xp-housekeeper` + agents mid-session | Unresolved in A4, resolved in R7 |
| Debt | `metadata.resolves` | `xp-housekeeper` + quality reviewer | Open in R6 (with aging), resolved omitted |
| Decision | `metadata.resolves` (superseded) | `xp-housekeeper` | Active in Constraints, superseded omitted |
| Question | `answer` event with `references` | `/xp-work-selection` | Blocking in A3, resolved in R3 |

### Kickoff Gate

Single gate: `kickoff_gate.py` (UserPromptSubmit). Blocks prompts until `/xp-kickoff` runs. Allows the command itself through. "startup" source = hard block, "clear" source = nudge only.

## Data Quality

- **ANSI stripping**: `_append_impl.py` strips ANSI escape codes from `content` at write time
- **Content truncation**: `materialize.py` truncates `customer_input` content to 300 chars in the housekeeping preload (`_CUSTOMER_INPUT_TRUNCATE_LIMIT`), flagging the summary with `content_truncated`. Summary-side only — the raw event is unchanged. At write time `event_schema.CONTENT_BUDGETS` bounds every type except `customer_input` and `commit` (both `None`), which are capped only by `MAX_CONTENT_LENGTH`. Budgets reject, they never truncate
- **Concern deduplication**: `detect_conflicts()` checks existing unresolved concerns before generating new ones

## Design Principles

1. Hooks enforce, subagents advise
2. Broadcast over point-to-point
3. Zero dependencies (Python stdlib only)
4. Crash-safe by construction
5. Decisions survive compaction
6. Command hooks for determinism, subagents for judgment
7. Global hooks, automatic participation
8. The customer's voice is in the log

## Future Vision: Autonomous Teams (3.0)

**Prerequisite:** v2.0 shipped (sprint lifecycle + CLI teammates), dogfooded on a real project for multiple weeks.

**Goal:** CLI teammates execute a requirements document with minimal human intervention. Human approves goals and priorities once, then reviews outputs.

### What v2.0 Provides

Sprint lifecycle (product spec → sprint → stories → accept → review → retro), teammate hooks (TeammateIdle, TaskCompleted), teammate guide (TEAMMATE_GUIDE.md), team spawn analysis, tiered context injection, commit-gated review cycle for all agents. The enforcement infrastructure is complete — 3.0 builds autonomy on top.

### Blocks as Maturity Signal

Blocks fire for: TDD failure, working_on conflicts, plan review, commit review cycle, teammate idle/complete gates. These blocks aren't friction — they're the system reporting that agents aren't yet coordinated enough for autonomy. When blocks stop firing because the system genuinely doesn't need them, that's the readiness signal for 3.0.

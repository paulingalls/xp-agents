# Milestones: v1.5 → v2.0

## Overview

v1.5 tightens solo enforcement — commit-gated review cycle replaces Stop gates. v2.0 adds sprint lifecycle and Agent Teams support. All work happens on a branch.

The sprint model applies to all work (solo and teams). A solo session may plan a sprint that runs solo, or planning may reveal parallelizable work that warrants a team. The product spec ensures agents have what they need to run autonomously regardless of execution mode.

Migration is additive — no data migration needed. First kickoff with new code moves things forward.

---

## v1.5 — Tighten Solo Enforcement

### M1: Marker Infrastructure + Review Cycle Marker

> **Design ref:** [Commit-Gated Review Cycle](AGENT_TEAMS_DESIGN.md#commit-gated-review-cycle) — marker file format, gate logic, flag lifecycle

Create `markers.py` module consolidating all marker file operations, then add the review cycle marker.

**Consolidate surviving markers:**

| Marker | Currently in | Pattern |
|---|---|---|
| `.tdd-{agent_id}.json` | `pre_tool_write.py` | agent-scoped JSON tracker |
| `.security-triaged` | `security.py` | JSON with timestamp |
| `.needs-kickoff` | `session_start.py` / `kickoff_gate.py` / `kickoff_done.py` | presence + content gate |
| `.plan-awaiting-review` | `post_tool_exit_plan.py` / `pre_tool_write.py` / `subagent_stop.py` | presence + content gate |

Note: `.simplify-{agent_id}.json` and `.quality-review-{agent_id}.json` are NOT consolidated — their owning scripts (`simplify_gate.py`, `quality_review_gate.py`) are removed in M3.

Common operations: `path()`, `read()`, `write()` (atomic), `exists()`, `consume()` (read + delete). Currently duplicated across 6+ files.

**Add review cycle marker:**

```json
{
  "last_review_commit": "abc123def",
  "simplify_done": false,
  "quality_review_done": false,
  "security_review_done": false
}
```

**Not consolidated** (different concerns):
- `.coordination.json` — real-time multi-agent coordination, different cadence, stays in `coordination.py`
- `.retro-input.json` — temp data file, not a gate marker
- `.lint-warned` — one-shot O_EXCL flag, unique pattern

**Depends on:** nothing
**Changes:** new `scripts/markers.py`, update `pre_tool_write.py`, `security.py`, `session_start.py`, `kickoff_gate.py`, `kickoff_done.py`, `post_tool_exit_plan.py`, `subagent_stop.py` to use `markers.py`, tests. Note: `simplify_gate.py` and `quality_review_gate.py` are NOT consolidated — they're removed in M3.

### M2: Commit-Gated Review Cycle

> **Design ref:** [Commit-Gated Review Cycle](AGENT_TEAMS_DESIGN.md#commit-gated-review-cycle) — PreToolUse:Bash gate logic, PostToolUse:Bash bookkeeping, SubagentStop flag updates; [Gate Architecture](AGENT_TEAMS_DESIGN.md#gate-architecture) — full gate chain; [Key Design Points](AGENT_TEAMS_DESIGN.md#key-design-points) — why commit-gated, not stop-gated

Move simplify, quality review, and security triage enforcement from Stop to commit time.

**Refactor first:**
- Extract commit detection/parsing from `bash_post_tool.py` into a shared utility (currently duplicates logic with `pre_tool_bash.py` — both call `is_git_commit()` but bash_post_tool also parses commit message, gets committed files). A `CommitInfo` helper or shared `commits.py` module would serve both Pre and Post hooks cleanly.
- Split `bash_post_tool.py` `run()` (100+ lines, handles commits AND test results AND lint). Extract commit handling into its own function so the review cycle bookkeeping has a clean place to live.

**PreToolUse:Bash (gate):**
- Detect `git commit` commands (existing `is_git_commit()`)
- Read review cycle marker
- Use `git diff --cached --name-only` + `git diff --name-only {last_review_commit}..HEAD` to count code files (existing `is_code_file()`)
- If threshold met: enforce simplify → quality review → security triage (sequential `elif` chain)
- If below threshold: enforce security triage only

**PostToolUse:Bash (bookkeeping):**
- After commit detected: `git rev-parse HEAD` for new hash
- Update marker: new `last_review_commit`, all flags reset to false

**SubagentStop (flag updates):**
- Detect simplify subagent completion → set `simplify_done: true`
- Detect quality review subagent completion → set `quality_review_done: true`

**Security triage completion:**
- Set `security_review_done: true` in marker

**Depends on:** M1
**Changes:** new `scripts/commits.py` (or similar), `pre_tool_bash.py`, `bash_post_tool.py`, `subagent_stop.py`, `security_review_done.py`, hooks.json, tests

### M3: Remove Stop Gates for Simplify/Quality Review

> **Design ref:** [Remaining TeammateIdle/TaskCompleted Gates](AGENT_TEAMS_DESIGN.md#remaining-teammateidletaskcompleted-gates) — TDD stays at Stop, simplify/quality/security move to commit-gated

**Refactor (cleanup):**
- Remove `simplify_gate.py` and `quality_review_gate.py` entirely (dead code now)
- Remove old `.simplify-{agent_id}.json` and `.quality-review-{agent_id}.json` tracker logic
- Remove simplify nudge from `bash_post_tool.py` (replaced by commit-gated enforcement)
- Clean up any imports or references to removed modules

**Updates:**
- Remove simplify/quality review hooks from Stop in hooks.json
- Keep `tdd_stop_gate.py` at Stop (solo TDD enforcement)
- Update BEHAVIORAL_GUIDE.md — remove "stop hooks saying run /simplify are requirements" language, add commit-gated language

**Depends on:** M2
**Changes:** hooks.json, remove `simplify_gate.py`, remove `quality_review_gate.py`, `bash_post_tool.py`, BEHAVIORAL_GUIDE.md, tests

### M4: Update v1 Documentation

- Update ARCHITECTURE.md: hook map, session flows, enforcement section, SMM storage (new marker file)
- Update SMM_DESIGN.md: mention review cycle marker in storage model
- Update CLAUDE.md: any references to Stop-based review enforcement

**Depends on:** M3
**Changes:** docs only

### M4b: Security Triage as Forked Subagent [SHIPPED]

Convert `/xp-security-triage` from inline skill to `context: fork` with a dedicated agent. The diff and security review results stay in the subagent's context — the main agent gets a summary only.

**New agent: `agents/xp-security-triage.md`**
- `effort: low` — classify-and-dispatch is lightweight work
- Tools: Read, Grep, Glob, Bash, Skill (needs Skill for `/security-review`)
- System prompt: see the diff (from preload), determine if code files changed, run `/security-review` if yes, return findings

**Update skill: `skills/xp-security-triage/SKILL.md`**
- Add `context: fork`, `agent: xp-agents:xp-security-triage`
- Preload script unchanged — diff + marker write still happen at preload time
- Skill body becomes the task prompt for the subagent

**Verify empirically:** Can a forked subagent invoke `/security-review` (a built-in skill) via the Skill tool? The current inline skill already uses `Skill(security-review)` successfully. If it doesn't work from a subagent, fallback: subagent does the triage, main agent runs `/security-review`.

**Token savings:** Diff stays in subagent context, not main conversation. On a typical 200-line diff, ~1-2K tokens saved. If `/security-review` also runs in the subagent, its output stays contained too.

**Hook compatibility:** `review_cycle_done.py` (PostToolUse:Skill) sets the security review flag when the skill completes — this still fires because the Skill tool completes in the main conversation regardless of fork. Verify SubagentStop also fires for the forked agent (it should, matching the retro/plan-reviewer pattern).

**Acceptance criteria:**
- [x] `agents/xp-security-reviewer.md` exists with `tools: Read, Grep, Glob, Bash, Skill`, `model: inherit`, `skills: [xp-smm-protocol]`, and instructs subagent to run `Skill(security-review)` and record result via `append.sh`
- [x] `skills/xp-security-triage/SKILL.md` has `context: fork` and `agent: xp-agents:xp-security-reviewer` in frontmatter
- [x] Preload scripts (`preload_diff.sh`, `mark_triaged.py`) unchanged — preload runs in main agent before fork
- [x] `review_cycle_done.py` (PostToolUse:Skill) sets `security_review_done` flag for both `"security-review"` and `"xp-security-triage"` skill names
- [x] Backward compat: `review_cycle_done.py` writes old `.security-triaged` marker alongside review cycle flag
- [x] Triage vs review distinction: `/xp-security-triage` completion sets flag but does NOT record "review complete" event; only `/security-review` records the completion event
- [x] `test_plugin_integrity.py` includes `xp-security-reviewer` in `_SUBAGENT_NAMES`
- [x] Agent prompt includes SMM content trust warning

**Depends on:** nothing
**Changes:** new `agents/xp-security-reviewer.md`, update `skills/xp-security-triage/SKILL.md`, tests

### M4c: TaskCreated Signal Events

Add a `TaskCreated` hook to record task creation in the event log as signal events for retrospective analysis.

**New hook: `task_created.py`**
- Listen on `TaskCreated` event
- Record a `status` event: "Task created: {task_subject}"
- Include task metadata (task_id, description) for retro signal analysis
- Skip xp-agent tasks (recursion guard)

**Retrospective integration:**
- Add task-creation events to `_classify_status_events` in `retrospective.py` — new counter alongside file_writes, test_runs, commits
- Retro can report: "12 tasks created" as a session stat, helping assess whether planning produced right-sized task breakdowns

**Hooks.json:** Register `task_created.py` on the `TaskCreated` event. Light hook — no blocking, async is fine since it's just recording.

**Acceptance criteria:**
- [ ] `scripts/task_created.py` exists with `run(input_data, smm_dir=None)` and `__main__` entry point
- [ ] Records `status` event: "Task created: {task_subject}" with task_id and description in event metadata
- [ ] Recursion guard: skips xp-agent tasks via `_common.is_xp_agent()`
- [ ] Registered in `hooks.json` under `TaskCreated`, async, appropriate timeout
- [ ] `retrospective.py` `_classify_status_events()` counts "Task created:" events as `task_creations`
- [ ] Handles malformed input and missing SMM gracefully (exit 0, no crash)
- [ ] Tests cover: event recording, metadata, recursion guard, retro classification, malformed input

**Depends on:** nothing
**Changes:** new `scripts/task_created.py`, hooks.json, `retrospective.py` (classification), tests

### M4d: disallowedTools on Subagents

Replace explicit `tools` allowlists with `disallowedTools` denylists on existing subagents where it improves future-proofing.

**xp-retrospective and xp-plan-reviewer:** Currently `tools: Read, Grep, Glob, Bash`. Change to `disallowedTools: Write, Edit, MultiEdit, Agent` — inherits all tools, explicitly denies mutation. More future-proof if the platform adds new read-only tools.

**xp-security-triage (from M4b):** Already needs Skill tool — use `disallowedTools: Write, Edit, MultiEdit, Agent` to inherit everything except mutation tools.

**Verify:** Test that `disallowedTools` works correctly on plugin subagents (not in the restricted fields list per docs, but worth confirming).

**Acceptance criteria:**
- [ ] `agents/xp-retrospective.md` replaces `tools: Read, Grep, Glob, Bash` with `disallowedTools: Write, Edit, MultiEdit, Agent`
- [ ] `agents/xp-plan-reviewer.md` replaces `tools: Read, Grep, Glob, Bash` with `disallowedTools: Write, Edit, MultiEdit, Agent`
- [ ] `agents/xp-security-reviewer.md` uses `disallowedTools: Write, Edit, MultiEdit, Agent` (retains Skill access for `/security-review`)
- [ ] All three agents retain functional access to Read, Grep, Glob, Bash (verified empirically)
- [ ] Mutation tools (Write, Edit, MultiEdit, Agent) are blocked for all three agents
- [ ] Plugin loads without validation errors when `disallowedTools` is present
- [ ] Tests verify frontmatter uses `disallowedTools` instead of `tools`

**Depends on:** M4b (for security triage agent)
**Changes:** `agents/xp-retrospective.md`, `agents/xp-plan-reviewer.md`, `agents/xp-security-reviewer.md`, tests

### M4e: Worktree Path Normalization [SHIPPED]

Fix `normalize_path()` so `.coordination.json` conflict detection works across worktrees.

**Problem:** `normalize_path()` in `_common.py` already returns repo-relative paths by stripping `git rev-parse --show-toplevel`. But when a file doesn't exist (e.g., Agent A created it in the main checkout but it doesn't exist in Agent B's worktree), the fallback to `os.path.normpath()` doesn't resolve symlinks, while the git root prefix uses `os.path.realpath()` which does. On macOS (`/var` → `/private/var`), the prefix strip fails → falls back to absolute → cross-worktree conflict missed.

**Fix:** When the normpath-based prefix strip fails for a non-existent file, walk up to the nearest existing ancestor, resolve its symlinks, rejoin the tail, and retry the prefix strip. Targeted fallback — only activates when inside a git repo and the initial strip fails.

**Acceptance criteria:**
- [x] Non-existent file paths normalize to repo-relative when an existing ancestor can be resolved
- [x] Cross-worktree paths normalize identically — Agent A in main checkout and Agent B in worktree produce the same repo-relative path, enabling `.coordination.json` conflict detection
- [x] macOS symlink mismatch handled: ancestor-walk resolves symlinks before retrying prefix strip
- [x] Ancestor walk stops gracefully at filesystem root without crash or infinite loop
- [x] Existing files still use `os.path.realpath()` directly (no behavior change)
- [x] Paths outside the git repo still fall back to absolute (no behavior change)
- [x] Tests in `test_common.py` and `test_coordination.py` cover all scenarios

**Depends on:** nothing
**Changes:** `scripts/_common.py` (`normalize_path()`), tests in `test_common.py`, `test_coordination.py`, `test_scaling.py`

---

## v2.0 — Sprint-Driven XP

### M5: Sprint Event Type [SHIPPED]

> **Design ref:** [New Event Types — `sprint`](AGENT_TEAMS_DESIGN.md#sprint) — event format, start/end metadata; [Compaction Rules for Sprint Events](AGENT_TEAMS_DESIGN.md#compaction-rules-for-sprint-events) — retention policy

Add `sprint` event type to the event schema for boundary markers.

**Refactor first:**
- ✅ `compact.py` `compact_after_curation()` is 130+ lines with complex retention logic. Extract retention rule evaluation into a separate function (e.g., `should_retain(event, session_ends, smm_ids) -> bool`) so adding sprint rules doesn't further bloat the main function.

**Add sprint type:**

```json
{"type": "sprint", "content": "...", "metadata": {"sprint_id": "...", "action": "start|end", ...}}
```

- ✅ Add to `event_schema.py` / `schema.json` with validation (requires `sprint_id`, `action`)
- ✅ Add compaction rules: retain `start` while active, retain `end` for 1 sprint
- ✅ Tests for schema validation, compaction retention
- ✅ Add `EVENT_TYPE_*` constants for all 15 event types in production code

**Depends on:** nothing (can parallel with M1-M4)
**Changes:** `event_schema.py`, `schema.json`, `compact.py`, tests

### M6: Product Spec Skill (`/xp-product-spec`) [SHIPPED]

> **Design ref:** [`product_spec.md` Format](AGENT_TEAMS_DESIGN.md#product_specmd-format) — file format with `[planned]`/`[delivered]` markers; [File Lifecycle](AGENT_TEAMS_DESIGN.md#file-lifecycle) — created by this skill, updated by sprint review

Design and implement the skill that creates/refines `product_spec.md`.

- ✅ Conversation-driven: guides the lead through requirements gathering
- ✅ Can ingest existing docs (PRDs, GitHub issues, design docs)
- ✅ Outputs structured `product_spec.md` with `[planned]` feature markers
- ✅ Supports updates: add new features, refine existing ones
- ✅ File lives in SMM directory

**Depends on:** nothing
**Changes:** new skill (`skills/xp-product-spec/SKILL.md`), `save_product_spec.py`, `preload.sh`, tests

### M7: Sprint Start Skill (`/xp-sprint-start`)

> **Design ref:** [`sprint.md` Format](AGENT_TEAMS_DESIGN.md#sprintmd-format) — file format with stories, status, acceptance criteria; [Sprint Start](AGENT_TEAMS_DESIGN.md#sprint-start-first-iteration) — planning flow; [Planning Hierarchy](AGENT_TEAMS_DESIGN.md#planning-hierarchy) — three levels of persistence; [Failed Stories](AGENT_TEAMS_DESIGN.md#failed-stories) — deferred story handling

Design and implement the skill that creates `sprint.md` from `product_spec.md`.

- Reads `[planned]` features from product_spec.md
- Selects features for this sprint by priority
- Decomposes into user stories with acceptance criteria, T-shirt sizes, dependencies
- XL stories must be split
- Customer confirms sprint scope
- Writes `sprint.md` + sprint start event to events.jsonl
- Handles deferred stories carried from previous sprint

**Acceptance criteria:**
- [x] Skill reads `product_spec.md` and extracts all `[planned]` features (ignores `[delivered: ...]`)
- [x] Decomposes features into user stories with unique IDs (`story-NNN`), acceptance criteria (including E2E test definitions), T-shirt sizes (S/M/L), and dependencies
- [x] XL stories are split during planning — no XL stories in final `sprint.md`
- [x] Customer confirms sprint scope via `AskUserQuestion` before files are written; rejection cancels without writing
- [x] Writes `sprint.md` to SMM directory with stories in priority order, all marked `ready`
- [x] Records `sprint` event (type: `sprint`, metadata: `sprint_id`, `action: "start"`) to events.jsonl
- [x] Carries forward `deferred` stories from previous sprint, presenting them separately in confirmation
- [x] Rejects missing `product_spec.md` or no `[planned]` features with clear error messages
- [x] Tests cover: file output format, event recording, customer confirmation flow, deferred story carryover, error cases

**Depends on:** M5, M6
**Changes:** new skill (`skills/xp-sprint-start/SKILL.md`), tests

### M8a: Sprint State Detection Hooks

> **Design ref:** [Mid-Sprint Iterations](AGENT_TEAMS_DESIGN.md#mid-sprint-iterations-subsequent-sessions) — full kickoff flow; [Solo Iteration](AGENT_TEAMS_DESIGN.md#solo-iteration) — gated lifecycle

Add sprint state detection to the deterministic hooks that run before and after kickoff. These are mechanical checks — no judgment.

`session_start.py` (SessionStart) — add sprint state detection:
- Check `product_spec.md` exists → if not, write `.needs-product-spec` marker
- Check `sprint.md` exists with active stories → if not, write `.needs-sprint` marker
- Clear accept marker (new iteration starting)
- Markers read by `kickoff_gate.py` to inform the block message, and by the skill to know what to orchestrate

`kickoff_done.py` (PostToolUse:Skill) — add sprint validation:
- After kickoff completes, verify sprint.md has in-progress stories (story selection happened)
- If not, nudge: "No stories selected for this iteration"

**Acceptance criteria:**
- [x] `session_start.py` writes `.needs-product-spec` marker when `product_spec.md` missing from SMM dir
- [x] `session_start.py` writes `.needs-sprint` marker when `sprint.md` missing or has no `ready`/`in-progress` stories
- [x] `session_start.py` does NOT create markers when both files exist with active stories
- [x] `session_start.py` clears `.accept` marker on session start (new iteration)
- [x] `kickoff_done.py` reads `sprint.md` after kickoff and nudges "No stories selected" when no `in-progress` stories
- [x] `kickoff_gate.py` reads markers and includes missing resource info in block message
- [x] Markers use atomic writes via `markers.py`, symlink-safe
- [x] Tests cover: marker creation/clearing for each file state, nudge messages, no-marker steady state

**Depends on:** M7
**Changes:** `session_start.py`, `kickoff_gate.py`, `kickoff_done.py`, `markers.py`, tests

### M8b: Sprint-Aware Kickoff Skill

> **Design ref:** [Mid-Sprint Iterations](AGENT_TEAMS_DESIGN.md#mid-sprint-iterations-subsequent-sessions) — full kickoff flow; [On-Site Customer](AGENT_TEAMS_DESIGN.md#on-site-customer) — customer availability / assumption handling

Update `/xp-kickoff` skill for sprint-aware orchestration.

**Refactor first:**
- Review current kickoff skill structure. It orchestrates retro → goals → questions → housekeeping. Adding sprint awareness means more steps. Ensure the skill's flow is cleanly extensible — each step should be a distinct section, not deeply nested conditionals.

**Skill orchestration (judgment):**

`/xp-kickoff` reads markers set by M8a and orchestrates:
1. Session retro (reflect before planning — surfaces unanswered questions, Try items)
2. `.needs-product-spec` set? → run `/xp-product-spec`
3. `.needs-sprint` set? → run `/xp-sprint-start`
4. Housekeeping with Sprint pillar (curates SMM, surfaces unverified assumptions in Risks)
5. Story selection: show ready stories, lead picks, questions resolved in context, mark in-progress

No standalone question triage — questions handled in the phase where they naturally arise. Story selection replaces per-session goal collection — sprint stories ARE the goals.

**Acceptance criteria:**
- [x] Kickoff reads `.needs-product-spec` marker → runs `/xp-product-spec` if set
- [x] Kickoff reads `.needs-sprint` marker → runs `/xp-sprint-start` if set
- [x] Full orchestration order: retro → product spec check → sprint check → housekeeping → story selection
- [x] When neither marker set (mid-sprint steady state): skips product spec and sprint start, proceeds to housekeeping and story selection
- [x] Story selection displays `ready` stories from `sprint.md`, lead picks stories to mark `in-progress`
- [x] Sprint stories replace goal collection — `/xp-goal-collection` not called when sprint active
- [x] Questions handled inline during story selection, not as standalone triage step
- [x] Backward compatible: kickoff still works without markers or sprint files (first-time project)
- [x] Tests cover: full flow with both markers, partial markers, no markers, story selection

**Depends on:** M6, M7, M8a
**Changes:** `skills/xp-kickoff/SKILL.md`, tests

### M8c: Accept Skill + Gate

> **Design ref:** [Solo Iteration — Accept](AGENT_TEAMS_DESIGN.md#solo-iteration) — accept flow + Stop gate; [Team Iteration — Accept](AGENT_TEAMS_DESIGN.md#team-iteration) — PR review → merge → e2e; [Goal Completion](AGENT_TEAMS_DESIGN.md#goal-completion) — story status lifecycle; [Gate Architecture](AGENT_TEAMS_DESIGN.md#gate-architecture) — accept gate in the full chain

(Previously M8b — renumbered after M8 split.)

Design and implement `/xp-accept` skill and the deterministic hooks that enforce and track it.

**Deterministic hooks:**

`accept_gate.py` (Stop) — gate enforcement:
- Read sprint.md — any stories `in-progress`?
- YES and accept marker not set → BLOCK: "Run /xp-accept to verify acceptance criteria before stopping"
- NO in-progress stories → allow stop

`accept_done.py` (PostToolUse:Skill) — completion bookkeeping:
- Fires when `/xp-accept` completes
- Set accept marker (via `markers.py`)
- Check sprint.md: all stories done or deferred? → nudge `/xp-sprint-review` (sprint complete)

Accept marker lifecycle:
- **Cleared** by `session_start.py` (new iteration)
- **Set** by `accept_done.py` (accept completed)
- **Read** by `accept_gate.py` (Stop enforcement)

**Skill (judgment):**

`/xp-accept`:
1. Read sprint.md — find stories marked `in-progress`
2. For each story: present acceptance criteria, lead verifies
3. Run e2e tests defined in criteria
4. Lead marks each story `done` or `deferred`
5. Update sprint.md
6. In team mode: includes PR review → merge → integrated e2e

The skill does the judgment work (verifying criteria, running tests, updating stories). The hooks handle the mechanical bookkeeping (marker, gate, sprint completion detection).

**Acceptance criteria:**
- [x] `accept_gate.py` (Stop) blocks when `sprint.md` has `in-progress` stories and accept marker not set
- [x] `accept_gate.py` allows stop when no `in-progress` stories (all `done`/`deferred`/`ready`) or no `sprint.md`
- [x] `accept_gate.py` skips for xp-agents (recursion guard)
- [x] `accept_done.py` (PostToolUse:Skill) sets accept marker when `/xp-accept` completes
- [x] `accept_done.py` detects sprint completion (all stories done/deferred) and nudges `/xp-sprint-review`
- [x] Accept marker cleared by `session_start.py` on new session, set by `accept_done.py`, read by `accept_gate.py`
- [x] `/xp-accept` skill reads `sprint.md`, presents in-progress story acceptance criteria, guides e2e test execution, lead marks each story `done` or `deferred`, updates `sprint.md`
- [x] Corrupt/missing `sprint.md` handled gracefully: gate allows stop, skill shows error, hooks log concern
- [x] Marker write failures logged as concern, not fatal
- [x] Tests cover: gate blocking/allowing, marker lifecycle, skill flow, sprint completion detection, error cases

**Depends on:** M7, M8a, M8b
**Changes:** new `accept_gate.py` (Stop), new `accept_done.py` (PostToolUse:Skill), new skill (`skills/xp-accept/SKILL.md`), `session_start.py` (clear marker), `markers.py`, hooks.json, tests

### M9: Sprint Pillar in Housekeeping

> **Design ref:** [Sprint-Aware Curated View](AGENT_TEAMS_DESIGN.md#sprint-aware-curated-view) — Sprint pillar format; [Housekeeping Sprint Curation](AGENT_TEAMS_DESIGN.md#housekeeping-sprint-curation) — what it computes

Add Sprint section to the curated SMM.

**Refactor first:**
- `materialize.py` `prepare_curation_data()` builds the preload JSON for housekeeping. Before adding sprint data, review its structure — ensure the output format is cleanly extensible (adding a `sprint` key alongside existing `current_smm`, `new_since_last_curation`, etc.).

**Deterministic data prep (preload script):**
- Parse `sprint.md` and compute structured sprint data: goal, story counts by status, blockers (unmet dependencies)
- Add to curation preload JSON as a `sprint` section — same pattern as `retrospective.py` preparing `.retro-input.json`
- Housekeeping skill receives pre-computed sprint data, applies judgment for what to include in the Sprint pillar summary

**Skill (judgment):**
- Housekeeping decides how to summarize sprint progress in the curated SMM
- Sprint pillar is a summary pointing to sprint.md for details

**Acceptance criteria:**
- [x] `prepare_curation_data()` returns `sprint` key alongside existing keys (`current_smm`, `new_since_last_curation`, `retro_history`, `aging`, `health`) [7ba8768]
- [x] Sprint data includes: `sprint_id`, `goal`, `started` date, `stories_by_status` (ready/in-progress/done/deferred counts), `blockers` list [2a1548f]
- [x] Missing/malformed `sprint.md` returns empty sprint data (all counts 0, no crash) [2a1548f]
- [x] Housekeeping SKILL.md includes "Curate Sprint" section with format: `- <sprint_id>: <goal> [N stories: R ready, I in-progress, D done, F deferred]` [42fc766]
- [x] Sprint pillar appears in curated SMM as new section (Sprint, Intent, Constraints, Risks, Wisdom) [42fc766]
- [x] No `sprint.md` → Sprint section shows "No active sprint" [42fc766]
- [x] Tests cover: sprint parsing, blocker detection, empty/missing sprint, curation preload format [2a1548f, 7ba8768]

**Depends on:** M7
**Changes:** `smm/sprint_parser.py` (new), `smm/materialize.py` (add sprint data to curation preload), `skills/xp-housekeeping/SKILL.md`, tests

### M10: Tiered Sprint Context Injection

> **Design ref:** [Context Injection by Role](AGENT_TEAMS_DESIGN.md#context-injection-by-role) — who gets what; [Collective Code Ownership](AGENT_TEAMS_DESIGN.md#collective-code-ownership) — cross-teammate communication via native messaging

Update SubagentStart to inject sprint context by role. Also update the plan reviewer to recommend execution mode, and add PostCompact sprint reinjection.

**Refactor first:**
- `subagent_start.py` tiering is currently a simple if/else on agent_type. Adding sprint tiers (plan reviewer gets sprint.md, teammates get assigned stories, retro gets sprint.md) adds more branches. Extract the tiering logic into a clear dispatch — a dict mapping agent types to injection functions, or a series of named functions. This keeps the `run()` function from becoming a long conditional chain.

**Add sprint tiers:**

| Agent | Gets |
|---|---|
| Simplify/lint subagents | SMM only (no change) |
| Plan reviewer | SMM + sprint.md |
| Teammates | SMM + assigned stories from sprint.md |
| Retrospective | SMM + sprint.md |

**Update plan reviewer for execution mode:**
- Update `agents/xp-plan-reviewer.md` instructions to analyze parallelization and recommend execution mode (solo / subagents / Agent Team)
- Plan reviewer should assess: are tasks sequential or parallelizable? Do file domains overlap? Is the work large enough to justify team coordination overhead?
- This is a prerequisite for M15 — the plan reviewer is supposed to tell the lead "run `/xp-spawn-team`" when appropriate

**PostCompact sprint reinjection:**
- Update the PostCompact flow to reinject sprint.md alongside the curated SMM
- After compaction, the lead's context loses sprint state — reinjection ensures story selection and accept gates still work
- Same tiering logic applies: lead gets full sprint.md, lightweight agents get nothing

**Acceptance criteria:**
- [x] `subagent_start.py` tiering refactored into clean dispatch (dict or named functions), `run()` ≤80 lines
- [x] Simplify/lint subagents receive SMM only (unchanged)
- [x] Plan reviewer receives SMM + `sprint.md` (when it exists)
- [x] Teammates receive SMM + their assigned stories only (filtered from `sprint.md`)
- [x] Retrospective receives SMM + `sprint.md`
- [x] Missing `sprint.md` degrades gracefully — inject SMM only, no error
- [x] Plan reviewer instructions updated to recommend execution mode (solo/subagent/Agent Team) based on parallelization analysis
- [x] PostCompact hook reinjects `sprint.md` alongside curated SMM
- [x] Tests cover: each tier (4+ agent types), missing sprint.md, plan reviewer execution mode output

**Depends on:** M7
**Changes:** `subagent_start.py`, `agents/xp-plan-reviewer.md`, PostCompact hook, tests

### M11: Sprint Review Skill (`/xp-sprint-review`)

> **Design ref:** [Sprint End](AGENT_TEAMS_DESIGN.md#sprint-end-all-stories-done-or-deferred) — review flow, velocity stats; [File Lifecycle](AGENT_TEAMS_DESIGN.md#file-lifecycle) — sprint review updates product_spec.md

Design and implement the forked skill that runs at sprint end.

**Deterministic data prep (preload script):**
- Parse sprint.md: count stories by status (done, deferred, added mid-sprint)
- Parse product_spec.md: identify features that map to completed stories
- Compute velocity stats: stories_planned, stories_delivered, stories_carried
- Prepare structured review data for the subagent

**Forked skill + subagent (judgment + writes):**
- Subagent analyzes what shipped vs what was planned
- Maps completed stories to product spec features (judgment — hook can't do this)
- Updates product_spec.md directly: mark features `[delivered: sprint-XXX]`

**Deterministic bookkeeping (PostToolUse:Skill hook):**
- `sprint_review_done.py` fires when `/xp-sprint-review` completes
- Recomputes velocity stats from sprint.md (stories by status — the subagent just updated it with delivered features, so counts are current). This avoids coupling the hook to the subagent's output format or the preload's temp data.
- Writes sprint end event to events.jsonl with velocity metadata (stories_planned, stories_delivered, stories_carried)
- Nudges `/xp-sprint-retro` if appropriate

Subagent writes when judgment is needed (mapping stories → features). Hook handles mechanical bookkeeping (events, markers, nudges).

**Acceptance criteria:**
- [x] Preload parses `sprint.md` (stories by status) and `product_spec.md` (features → stories mapping), computes velocity stats
- [x] Subagent maps completed stories to product spec features and updates `product_spec.md` with `[delivered: sprint-XXX]` markers
- [x] Already-delivered features (`[delivered: sprint-YYY]`) are not modified
- [x] `sprint_review_done.py` (PostToolUse:Skill) recomputes velocity from `sprint.md` and writes sprint end event (type: `sprint`, `action: "end"`, velocity metadata)
- [x] Sprint end event uses `EVENT_TYPE_SPRINT` constant and passes `validate_event()`
- [x] Hook nudges `/xp-sprint-retro` after sprint review completes
- [x] Missing `sprint.md` or `product_spec.md` handled gracefully in preload
- [x] Tests cover: preload parsing, product_spec updates, velocity computation, event recording, nudge

**Depends on:** M6, M7
**Changes:** new skill (`skills/xp-sprint-review/SKILL.md`), new agent (`agents/xp-sprint-reviewer.md`), new `sprint_review_done.py` hook, preload script, tests

### M12: Sprint Retro Skill (`/xp-sprint-retro`)

> **Design ref:** [Retrospective](AGENT_TEAMS_DESIGN.md#retrospective) — two retro levels, sprint retro data sources; [Sustainable Pace](AGENT_TEAMS_DESIGN.md#sustainable-pace) — velocity tracking, carry-over signals

Design and implement the forked cross-iteration retrospective (same pattern as existing session retro).

**Deterministic data prep (preload script):**
- Collect all session retros from the sprint (from `retrospectives/` directory)
- Compute velocity from sprint events: stories_planned vs stories_delivered vs stories_carried
- Parse sprint.md for story completion data, sizing accuracy
- Prepare structured retro data for the subagent

**Forked skill + subagent (judgment + writes):**
- Subagent analyzes patterns across all iterations in the sprint
- Assesses T-shirt sizing accuracy
- Identifies process improvements for next sprint
- Produces and saves Keep/Fix/Try at the sprint level (same Write pattern as session retro subagent)

**Acceptance criteria:**
- [x] Preload collects all session retros from `retrospectives/` directory for the current sprint
- [x] Preload computes velocity from sprint events (stories planned/delivered/carried) and parses `sprint.md` for story completion and sizing data
- [x] Preload output is deterministic (no judgment) — structured JSON with `session_retros`, `velocity_stats`, `story_data`, `sprint_metadata`
- [x] Subagent analyzes cross-iteration patterns, T-shirt sizing accuracy, and process improvements
- [x] Subagent produces sprint-level Keep/Fix/Try (not session-level detail)
- [x] Output saved via `save_retrospective.py` pattern — timestamped JSON in `retrospectives/`, event in `events.jsonl`
- [x] Handles missing/incomplete data gracefully (no retros, no sprint events, missing sprint.md)
- [x] Tests cover: preload data collection, velocity computation, sizing analysis, saved output format

**Depends on:** M7
**Changes:** new skill (`skills/xp-sprint-retro/SKILL.md`), new agent (`agents/xp-sprint-retro.md`), preload script, tests

### M13: Teammate Hooks

> **Design ref:** [Hook Compatibility — Empirical Results](AGENT_TEAMS_DESIGN.md#hook-compatibility--empirical-results-2026-03-23) — what fires for teammates; [Remaining TeammateIdle/TaskCompleted Gates](AGENT_TEAMS_DESIGN.md#remaining-teammateidletaskcompleted-gates) — TDD enforcement; [Teammate Detection](AGENT_TEAMS_DESIGN.md#teammate-detection) — detection patterns; [Output Mechanism Differences](AGENT_TEAMS_DESIGN.md#output-mechanism-differences) — exit 2 + stderr

Implement TeammateIdle and TaskCompleted hooks.

**Refactor first:**
- Extract the SMM dir validation boilerplate that appears in every hook (`resolve_smm_dir()` → `try_validate_smm_dir()` → return None) into a `_common.get_validated_smm_dir()` helper. Currently duplicated across 6+ scripts. Clean this up before adding two more scripts that would copy the same pattern.
- Review TDD gate logic in `tdd_stop_gate.py` — the test-passing check will be reused by both new hooks. Extract the core TDD check into a shared function so all three hooks use the same logic.

**New hooks:**
- **TeammateIdle:** TDD enforcement (tests must pass before going idle)
- **TaskCompleted:** TDD enforcement (tests must pass before task marked complete)
- Both use exit 2 + stderr to block
- Detect teammate events via `teammate_name` field

**Acceptance criteria:**
- [x] `_common.get_validated_smm_dir()` helper extracts SMM dir validation boilerplate, used by 6+ existing scripts
- [x] Shared TDD check function extracted from `tdd_stop_gate.py`, used by all three hooks (Stop, TeammateIdle, TaskCompleted)
- [x] `teammate_idle.py` blocks (exit 2 + stderr) when tests failing, allows (exit 0) when passing
- [x] `task_completed.py` blocks (exit 2 + stderr) when tests failing, allows (exit 0) when passing
- [x] Both hooks detect teammates via `teammate_name` field; skip gracefully if absent
- [x] Both registered in `hooks.json` under `TeammateIdle` and `TaskCompleted` events
- [x] Missing `events.jsonl` or SMM handled gracefully (exit 0, no crash)
- [x] Tests cover: TDD check logic, teammate detection, exit codes, stderr messages, edge cases

**Depends on:** Agent Teams platform stabilization
**Changes:** `_common.py`, `tdd_stop_gate.py` (extract shared logic), new `task_completed.py`, new `teammate_idle.py`, hooks.json, tests

### M14: Teammate Behavioral Guide

> **Design ref:** [Teammate Behavioral Guide](AGENT_TEAMS_DESIGN.md#teammate-behavioral-guide) — DO/DON'T/SKIP/KEEP rules; [Teammates vs Subagents](AGENT_TEAMS_DESIGN.md#teammates-vs-subagents) — key differences; [Collective Code Ownership](AGENT_TEAMS_DESIGN.md#collective-code-ownership) — "message the lead immediately" for urgent discoveries

Update SubagentStart to detect teammates and inject appropriate guide.

**Note:** M10 already refactored `subagent_start.py` tiering into a clean dispatch. Adding teammate detection builds on that clean base — no additional refactoring needed.

**Add teammate injection:**
- Detect via `is_teammate_by_agent_type()` (existing pattern)
- **DO:** Claim tasks, write tests first, commit frequently, stay in file domain, message lead for urgent discoveries
- **DON'T:** Run kickoff, housekeeping, goals, retrospectives
- **SKIP:** EnterPlanMode (built-in plan approval handles this)
- Commit-gated reviews enforced automatically via PreToolUse:Bash

**Acceptance criteria:**
- [x] `subagent_start.py` detects teammates via `is_teammate_by_agent_type()` and injects teammate-specific guide
- [x] Teammate guide includes DO (claim tasks, TDD, commit frequently, stay in file domain, message lead for urgent discoveries)
- [x] Teammate guide includes DON'T (no kickoff, housekeeping, goals, retrospectives)
- [x] Teammate guide includes SKIP (EnterPlanMode — built-in plan approval handles it)
- [x] Existing non-teammate agent tiers unchanged (Explore, Plan, xp-* agents)
- [x] Guide content does not reference lead-only ceremonies or skills
- [x] Guide references commit-gated review cycle as automatic enforcement
- [x] Tests cover: teammate detection, guide content verification, non-teammate agents unaffected

**Depends on:** M10, M13
**Changes:** `subagent_start.py`, BEHAVIORAL_GUIDE.md (add teammate section or separate guide), tests

### M15: Spawn Team Skill (`/xp-spawn-team`)

> **Design ref:** [Team Launch Mechanism](AGENT_TEAMS_DESIGN.md#team-launch-mechanism) — skill flow, spawn prompt content; [Team Iteration](AGENT_TEAMS_DESIGN.md#team-iteration) — full team lifecycle; [When to Use Agent Teams](AGENT_TEAMS_DESIGN.md#when-to-use-agent-teams) — decision criteria; [Worktree Strategy](AGENT_TEAMS_DESIGN.md#worktree-strategy) — tradeoffs, decision criteria; [Best Practices](AGENT_TEAMS_DESIGN.md#best-practices) — team size, domain separation, context feeding

Design and implement the forked skill that structures an Agent Team from the sprint plan.

**Forked skill + subagent** (same pattern as plan reviewer):
- Preloads dump sprint.md + current plan for the subagent
- Subagent analyzes file domains, parallelization, task structuring
- Returns structured instructions to the lead (keeps analysis out of lead context)

**Subagent output:**
- How many teammates to spawn (based on parallel group count)
- Task descriptions with acceptance criteria, file domains, context
- Worktree decision (based on overlap analysis)
- Spawn prompt content (XP rules, domain boundaries)

Does NOT spawn the team directly — instructs the lead on exactly what to do.

**Worktree support:** If the subagent recommends worktrees, `.coordination.json` cross-worktree conflict detection requires M4e (worktree path normalization). Without M4e, worktree mode should not be recommended — the subagent should note this constraint.

**Acceptance criteria:**
- [ ] Preload dumps SMM + `sprint.md` + current plan for subagent
- [ ] Subagent identifies distinct file domains and detects parallel task groups
- [ ] Subagent recommends team size (1-5 teammates) with rationale
- [ ] Each task description includes: title, file domain, acceptance criteria, relevant context, TDD expectation
- [ ] Worktree decision: recommends worktrees for large teams with non-overlapping domains; notes M4e constraint if applicable
- [ ] Output is structured instructions for the lead — does NOT spawn team directly
- [ ] Handles edge cases: no parallel work → recommend solo, single task → solo more efficient, missing sprint/plan → clear error
- [ ] Tests cover: domain analysis, team sizing, task descriptions, worktree decision logic, error cases

**Depends on:** M4e, M7, M13, M14, Agent Teams platform
**Changes:** new skill (`skills/xp-spawn-team/SKILL.md`), new agent (`agents/xp-spawn-team.md`), tests

### M16: Update v2 Documentation

> **Design ref:** [Three-File Architecture](AGENT_TEAMS_DESIGN.md#three-file-architecture) — SMM storage model; [Platform Findings](AGENT_TEAMS_DESIGN.md#platform-findings-from-docs-and-empirical-testing-2026-03-23) — confirmed behaviors + limitations; [v1 Limitations That Affect v2](AGENT_TEAMS_DESIGN.md#v1-limitations-that-affect-v2) — full change list

- Update ARCHITECTURE.md with full v2 design (sprint lifecycle, three-file architecture, new hooks, new skills, updated enforcement)
- Update SMM_DESIGN.md (Sprint pillar, tiered injection, product_spec.md/sprint.md)
- Update CLAUDE.md as needed

**Acceptance criteria:**
- [ ] ARCHITECTURE.md updated: sprint lifecycle section, three-file architecture, new hooks in hook map, new skills list, tiered injection table
- [ ] ARCHITECTURE.md covers all v2 milestones M5-M15 (sprint events, product spec, sprint start, detection hooks, kickoff, accept, sprint review, sprint retro, teammate hooks, teammate guide, spawn team)
- [ ] SMM_DESIGN.md updated: Sprint pillar, product_spec.md/sprint.md in storage model, file lifecycle
- [ ] CLAUDE.md updated: teammate constraints, new hook patterns, any changed conventions
- [ ] All hook names, skill names, and agent names match actual implementation filenames
- [ ] Event types table matches `event_schema.py` constants and `schema.json`
- [ ] No stale v1-only references (e.g., "stop-gated review" replaced with "commit-gated")
- [ ] Internal consistency across all three docs (no contradictions)

**Depends on:** M5-M15
**Changes:** docs only

---

## Dependency Graph

```
v1.5 (solo enforcement):
  M1 → M2 → M3 → M4  [SHIPPED]
  M4b (security triage subagent)      [SHIPPED]
  M4c (TaskCreated events)            — independent
  M4d (disallowedTools)               → M4b [SHIPPED]
  M4e (worktree path normalization)   [SHIPPED]

v2.0 (sprint/teams):
  M5 (sprint events)     ─┐  [SHIPPED]
  M6 (product spec skill) ─┼→ M7 (sprint start) → M8a (sprint detection hooks) → M8b (kickoff skill) → M8c (accept)
                    [SHIPPED]
                           │                    → M9 (sprint pillar)
                           │                    → M10 (tiered injection + plan reviewer + PostCompact)
                           │                         → M14 (teammate guide)
                           │                    → M11 (sprint review)
                           │                    → M12 (sprint retro)
                           │
  M13 (teammate hooks)     → M14 → M15 (spawn team)
  M4e (worktree paths)     → M15

  M16 (docs) depends on all above
```

M1-M4 shipped in v1.5.0-v1.5.10. M4b, M4e shipped independently. M5, M6 shipped. M4c and M4d remain as independent items. M7 (Sprint Start) is next on the critical path — nearly everything depends on it. M9 and M10 can run in parallel after M7 (M10 no longer depends on M9). M13-M15 depend on the Agent Teams platform stabilizing.

---

## What's NOT in Scope

- Agent Teams platform changes (we design around platform constraints)
- Per-teammate model selection (platform limitation — accept until added)
- Nested teams (platform limitation — keep teams flat)
- Automated story → task mapping (lead manages manually for now)

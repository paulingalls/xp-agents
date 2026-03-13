# Development Milestones

## Milestone 1: SMM Foundation

**Goal**: Data layer.

**Deliverables**:
- [ ] `smm/schema.json` — 11 event types: `customer_input`, `status`, `decision`, `convention`, `concern`, `discovery`, `question`, `assumption`, `pair_guidance`, `session_end`, `retrospective`. `status` has `working_on`. `question` has `priority` (🔴/🟡/🟢). All events have optional `metadata`, `schema_version`, `references`.
- [ ] `smm/init.sh` — Initialize `~/.claude/xp-agents/{project-id}/smm/`. Derives `project-id` from `git rev-parse --git-common-dir`. Idempotent. Validates Python 3.10+. Creates `events.jsonl`, `events.lock`, `retrospectives/`. Crash-safe. Uses `${CLAUDE_PLUGIN_ROOT}`.
- [ ] `smm/append.sh` — Atomic append. JSON construction, schema validation, `flock` writes. Generates `id` and `ts`. Exits 1 on validation failure.
- [ ] `LICENSE` (MIT), `CHANGELOG.md`

**Acceptance Criteria**:
- Schema covers all 11 types with correct fields
- `init.sh` derives consistent project-id across worktrees
- `init.sh` idempotent; recovers from partial completion
- `append.sh` validates, rejects malformed, handles 20 concurrent writes
- Python stdlib only, use match/case where appropriate, macOS + Linux

---

## Milestone 2: SMM Engine

**Goal**: Read side.

**Deliverables**:
- [ ] `smm/materialize.py` — events.jsonl → SHARED_MENTAL_MODEL.md. Groups by type. Detects structural conflicts. Atomic write (tempfile + rename). Skips malformed lines (emits concern). Unknown types rendered under "Unknown Events".
- [ ] `smm/read_delta.py` — Events since `.watermark-{agent-id}`. Tiered filtering: full, blocking-only (🔴 + pair_guidance), 🔴-only. Accepts `agent_id` param (default `main`). Updates watermark after read.

**Acceptance Criteria**:
- Correct Markdown from sample logs covering all 11 types
- Conflict alerts for overlapping working_on, assumption-discovery contradictions, convention violations
- Per-agent watermarks, tiered filtering
- Handles empty, single-event, and corrupted logs
- Kill mid-write → old or new version, never half-written

---

## Milestone 3.1: Core Hooks — Session Lifecycle

**Goal**: Plugin skeleton. After this, the plugin loads, sessions are tracked, SMM injects.

**Deliverables**:
- [ ] `hooks/hooks.json` — All hook registrations. Correct matchers, timeouts, handler types. Paths use `${CLAUDE_PLUGIN_ROOT}`.
- [ ] `.claude-plugin/plugin.json` — Plugin manifest.
- [ ] `settings.json` — Default plugin settings.
- [ ] `scripts/session_start.py` — SessionStart (startup, resume, compact). Calls `init.sh`. Checks for unanalyzed events. Two modes: unanalyzed events → prepare retro input + instruction for retrospective agent hook + GUPP + skills. No events → full SMM directly + GUPP + skills. Output via `additionalContext`.
- [ ] `scripts/session_end.py` — SessionEnd. Computes duration, event count, unresolved items, active working_on, missing final status flag. Appends `session_end` event. Non-blocking.
- [ ] `scripts/pre_compact.py` — PreCompact. Timestamped backup of events.jsonl and SHARED_MENTAL_MODEL.md.
- [ ] `scripts/subagent_start.py` — SubagentStart. Runs materializer, injects full SMM via `additionalContext`. Creates `.watermark-{agent_id}`.

**Acceptance Criteria**:
- Plugin loads without errors
- SessionStart initializes SMM on first run, re-injects after compaction
- SessionStart detects unanalyzed events and signals for retrospective
- SessionEnd captures all summary fields
- SubagentStart injects SMM and creates watermark
- All hooks pass through gracefully when SMM missing
- All hooks check agent_id/agent_type, skip `xp-` prefixed agents

---

## Milestone 3.2: Core Hooks — PreToolUse

**Goal**: Delta injection, conflict prevention, TDD ordering.

**Deliverables**:
- [ ] `scripts/pre_tool_use.py` — PreToolUse (matcher: `*`). Reads `agent_id` (fallback `main`). Tiered delta injection via `additionalContext`: full delta for Write/Edit/MultiEdit/Bash(git commit), 🔴+pair_guidance for other Bash, 🔴-only for Read/Grep/Glob. Checks `working_on` overlap → exit 2 if conflict. TDD order tracking: records file write order, flags implementation-before-test.

**Acceptance Criteria**:
- Correct tier of delta based on tool_name
- Per-agent watermarks via agent_id
- Blocks on working_on overlap (exit 2 with explanation)
- Flags implementation-before-test ordering via additionalContext
- Fast — minimal overhead on every tool call

---

## Milestone 3.3: Core Hooks — PostToolUse ✅

**Goal**: Auto status, conflict detection, lint, commit/test tracking.

**Status**: Complete (389 total tests: 190 SMM + 199 hooks, 72 new tests for M3.3).

**Deliverables**:
- [x] `scripts/post_tool_use.py` — PostToolUse (matcher: `Write|Edit|MultiEdit`). Auto-generates `status` with `working_on` from `tool_input.file_path`. Structural conflict detection (all 5 patterns). Semantic context enrichment via references.
- [x] `scripts/lint_check.py` — PostToolUse (matcher: `Write|Edit|MultiEdit`). Detects project linter config (ruff, eslint, prettier, flake8). Runs linter if found. Appends concern for lint errors. Warns once if no config. Degrades gracefully.
- [x] `scripts/bash_post_tool.py` — PostToolUse (matcher: `Bash`). Git commits: auto-drafts decisions (draft: true), commit size check. Test runs (pytest/jest/go test): parses pass/fail, appends status + concern.
- [x] `hooks/hooks.json` — PostToolUse section with Write|Edit|MultiEdit and Bash matchers.
- [x] `settings.json` — `commit_size_threshold: 10`.
- [x] Shared helpers extracted to `_common.py` (`normalize_path`, `extract_file_path`).

**Acceptance Criteria**:
- ✅ Auto-generates status/working_on from file paths
- ✅ Structural conflicts detected (all 5 patterns from architecture)
- ✅ Semantic conflict context recorded for decisions/conventions
- ✅ Auto-drafts decisions from significant changes
- ✅ Lint runs when config found, silent when not
- ✅ Commit size flagged when too large
- ✅ Test results parsed and recorded

---

## Milestone 3.4: Core Hooks — Customer & Subagent Tracking ✅

**Goal**: Customer voice, notifications, subagent bookkeeping.

**Status**: Complete (439 total tests: 190 SMM + 249 hooks, 50 new tests for M3.4).

**Deliverables**:
- [x] `scripts/user_prompt_log.py` — UserPromptSubmit. Reads `prompt` from input. Appends as `customer_input` event with `agent_id="customer"`. Truncates to 10,000 chars.
- [x] Notification inline in `smm/_append_impl.py` — `_detect_platform()`, `_sanitize_notification()`, `_notify_blocking_question()`. Fires at the choke point (`append_event()`) so every 🔴 question gets notified regardless of source. macOS `osascript` / Linux `notify-send`.
- [x] `scripts/subagent_stop.py` — SubagentStop. Reads `agent_id` (default "subagent"). Appends minimal `status` event. Runs conflict detection (patterns 2-5, no file_path).
- [x] `detect_conflicts()` and `make_concern()` extracted to `scripts/_common.py` with optional `file_path`/`cwd` (skips pattern 1 when None). `post_tool_use.py` imports from `_common`.
- [x] `hooks/hooks.json` — Added UserPromptSubmit + SubagentStop sections (5s timeout on SubagentStop).
- [x] Integration tests — subprocess-based tests for both new scripts (exit codes, event content, edge cases).

**Design change from plan**: No separate `scripts/customer_notify.py` — notification logic lives inline in `_append_impl.py` at the `append_event()` choke point. This ensures every 🔴 question gets notified immediately regardless of whether it comes from a command hook or agent hook via `append.sh`.

**Acceptance Criteria**:
- ✅ Every user prompt logged as customer_input event
- ✅ Desktop notification on macOS and Linux for 🔴 questions
- ✅ Subagent work recorded, conflicts detected (patterns 2-5)
- ✅ All hooks skip xp- prefixed agents
- ✅ Graceful degradation when SMM missing
- ✅ Integration tests verify scripts work end-to-end as subprocesses

---

## Milestone 4: Agent Hooks — Quality & Navigation ✅

**Goal**: XP practice enforcement on every code change.

**Status**: Complete (502 total tests: 190 SMM + 312 hooks, 39 new tests for M4).

**Deliverables**:
- [x] `prompts/navigator.md` — PreToolUse agent hook (matcher: `Write|Edit|MultiEdit`). Reads tool_input + SMM. Strategic guidance. Can block (exit 2) if change contradicts decisions. Self-filters trivial changes (whitespace, comments, renames). Writes `pair_guidance` events to log.
- [x] `prompts/quality_reviewer.md` — PostToolUse agent hook (async, matcher: `Write|Edit|MultiEdit`). Courage + simplicity. Flags: empty catch, missing error handling, unnecessary complexity, premature abstraction, growing file size. Writes `concern` events. Clean code gets clean review.
- [x] `scripts/plan_review.py` — SubagentStop command hook (matcher: `Plan`). Deterministic plan analysis: step counting, TDD strategy detection, size flags, decision/convention lookup. Returns context for plan_reviewer agent hook via `additionalContext`.
- [x] `prompts/plan_reviewer.md` — Highest-leverage review in the system. Must check: (1) respects milestone boundaries — flag work pulled from future milestones, (2) TDD-ordered — test files before implementation files, (3) small enough — flag plans with >10 steps, (4) surfaces assumptions — extract as `assumption` events to SMM, (5) conflicts with existing decisions/conventions in the materialized SMM. Extracts `decision` and `assumption` events.
- [x] `hooks/hooks.json` — Added PreToolUse navigator agent, PostToolUse async quality_reviewer agent, SubagentStop Plan matcher with plan_review.py + plan_reviewer agent.
- [x] `find_related_decisions()` extracted from `post_tool_use.py` to `_common.py` for reuse by `plan_review.py`.

**Design change from plan**: No separate `scripts/navigator_gate.py` — command hooks cannot gate/skip subsequent agent hooks in the same matcher array (they always fire). Significance filtering moved into the navigator prompt itself: trivial changes (whitespace, comments, single-line renames) get an immediate empty response. This eliminates one deliverable and simplifies hook registration.

**Acceptance Criteria**:
- ✅ Navigator self-filters trivial changes, provides strategic guidance for significant ones
- ✅ Navigator can block on decision contradictions, writes pair_guidance events
- ✅ Quality reviewer flags real issues, approves clean code (no false positives)
- ✅ Quality reviewer runs async, writes concerns to SMM
- ✅ Plan reviewer flags oversized plans (>10 steps), detects missing TDD strategy
- ✅ Plan review extracts decisions/conventions for plan_reviewer context
- ✅ All agent hooks skip xp- prefixed agents (recursion prevention in prompts)
- ✅ Plugin version bumped to 0.4.0

---

## Milestone 5: Agent Hooks — Session Lifecycle ✅

**Goal**: Retrospective, customer triage, subagent review, TDD gate.

**Status**: Complete (551 total tests: 190 SMM + 361 hooks, 49 new tests for M5).

**Deliverables**:
- [x] `scripts/retrospective.py` — SessionStart command hook. Checks for unanalyzed events (≥5 threshold). Gathers event log + last 2-3 retrospective files. Writes `.retro-input.json` atomically. Always exits 0. Returns context summary when retro needed.
- [x] `prompts/retrospective_analyst.md` — SessionStart agent hook. Keep/Fix/Try with XP values as lenses (Honesty, Communication, Courage, Simplicity, Respect). Reads `.retro-input.json`. Writes to `retrospectives/<timestamp>.json`. Runs materializer. Cross-session trend detection from previous retros. "Insufficient data" when `.retro-input.json` absent.
- [x] Retrospective output schema — already existed in `smm/schema.json` (keep/fix/try arrays with event_refs and values/xp_value fields).
- [x] `prompts/customer_proxy.md` — SessionStart agent hook. Reads SMM for unanswered 🔴 and 🟡 questions. Triages via AskUserQuestion. Records answers as events via `append.sh`.
- [x] `prompts/subagent_reviewer.md` — SubagentStop agent hook (async). Reads `agent_transcript_path`. Reviews: convention adherence, complexity, decision alignment. Writes `concern` events. Skips xp- agents.
- [x] `prompts/tdd_check.md` — Stop prompt hook (single-turn, no tool access). Evaluates test status from conversation context. Blocks if tests failing. Respects `stop_hook_active` guard to prevent infinite loops.
- [x] `scripts/session_start.py` refactored — retro logic moved to `retrospective.py`. Session start now handles only SMM init + materialization + GUPP + skills injection.
- [x] `hooks/hooks.json` — Added SessionStart (retrospective.py + retrospective_analyst + customer_proxy), SubagentStop default (subagent_reviewer async), Stop (tdd_check prompt).

**Design decisions**:
- `retrospective.py` always exits 0. Signals via `.retro-input.json` file presence (not exit codes). The analyst agent checks for the file.
- `tdd_check.md` is a prompt-type hook (not command/agent). Single-turn evaluation, returns `{"decision": "block"|"allow"}`.
- `stop_hook_active` is a field in the Stop hook input JSON. True when agent was already blocked once — prevents infinite loops.

**Acceptance Criteria**:
- ✅ Retrospective produces Keep/Fix/Try grounded in specific events
- ✅ Every Keep has event references, every Fix has XP value context, every Try is actionable
- ✅ "Insufficient data" for <5 events (handled by not writing .retro-input.json)
- ✅ Cross-session trends from previous retrospectives
- ✅ Customer proxy triages via AskUserQuestion, records answers
- ✅ Subagent reviewer evaluates holistic output, skips own agents
- ✅ TDD check blocks on test failure, respects stop_hook_active
- ✅ Keep/Fix/Try visible to user at session start
- ✅ Plugin version bumped to 0.5.0

---

## Milestone 6: CLAUDE.md & Skills

**Goal**: Behavioral rules and reference knowledge.

**Deliverables**:
- [ ] `CLAUDE.md` (~2,500–3,500 tokens) — Honesty Principle (7 rules), XP Values, SMM Protocol (read before modify, record decisions, never silently override, working_on, GUPP), Standup Protocol, Session End Protocol (final status before finishing), Retrospective Protocol, Code Quality (test first, lint, flag complexity), Courage Commitments.
- [ ] `skills/smm-protocol/SKILL.md` (~1,000–2,000 tokens) — Event types, working_on, references, conflict response, good vs. bad event examples.
- [ ] `skills/xp-values/SKILL.md` (~1,000–2,000 tokens) — Values as behaviors, honesty as foundation.
- [ ] `skills/pair-programming/SKILL.md` (~1,000–2,000 tokens) — Navigator/driver protocol, pair_guidance events.

**Acceptance Criteria**:
- CLAUDE.md 2,500–3,500 tokens, readable in <3 minutes
- No contradictions with hook enforcement
- Skills have valid frontmatter with trigger/skip_when
- Developer can append an event correctly after reading smm-protocol alone

---

## Milestone 7: Integration Testing & Packaging

**Goal**: End-to-end, marketplace ready.

**Deliverables**:
- [ ] `.claude-plugin/marketplace.json`
- [ ] READMEs (repo root + plugin level)
- [ ] Integration tests:
  - Full session lifecycle: start → work → subagent → stop → next session retrospective
  - 3-session accumulation test
  - Agent Teams simulation: concurrent writes, shared SMM across worktrees
  - All hook events fire correctly
  - All conflict detection patterns trigger
  - Customer question full flow (question → notification → AskUserQuestion → answer)
  - Plan subagent → review → decisions extracted
  - Compaction → full SMM re-injection
- [ ] Edge cases: empty project, 1000+ events, concurrent writes, malformed events, missing SMM, recursion prevention, worktree project-id resolution
- [ ] CHANGELOG.md complete

**Acceptance Criteria**:
- Marketplace install and direct install both work
- 3-session integration passes
- All edge cases handled
- User scope install, SMM at `~/.claude/xp-agents/{project-id}/smm/`
- Zero external dependencies

---

## Milestone 8: Hardening & Optimization

**Goal**: Production-ready.

**Deliverables**:
- [ ] Performance benchmarks (materialization 100–5,000 events, delta reader optimization)
- [ ] Async verification (PostToolUse agent hooks, PostToolUse additionalContext testing)
- [ ] Log management (`smm/compact.py` — snapshot + archive)
- [ ] Recovery (`smm/repair.py` — rebuild from corrupted log)
- [ ] Schema versioning (`smm/migrate.py`, additive-only policy)
- [ ] Agent Teams verification (all items from architecture)
- [ ] CHANGELOG final

**Acceptance Criteria**:
- Materialization <500ms for 1,000 events
- Graceful degradation under all conditions
- Repair recovers corrupted logs
- Migration upgrades between schema versions
- Agent Teams items verified
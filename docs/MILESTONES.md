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

## Milestone 3.3: Core Hooks — PostToolUse

**Goal**: Auto status, conflict detection, lint, commit/test tracking.

**Deliverables**:
- [ ] `scripts/post_tool_use.py` — PostToolUse (matcher: `Write|Edit|MultiEdit`). Auto-generates `status` with `working_on` from `tool_input.file_path`. Structural conflict detection (Tier 1). Semantic conflict context (Tier 2): records recent decisions for PreToolUse delivery on decision/convention appends. Auto-drafts `decision` events from significant changes (`draft: true`).
- [ ] `scripts/lint_check.py` — PostToolUse (matcher: `Write|Edit|MultiEdit`). Detects project linter config (`.eslintrc`, `.prettierrc`, `pyproject.toml`, etc.). Runs linter if found. Appends results as status event. Degrades gracefully if none configured.
- [ ] `scripts/bash_post_tool.py` — PostToolUse (matcher: `Bash`). Parses `tool_input.command` and `tool_response`. Git commits: checks diff size, auto-drafts decisions from commit messages. Test runs: parses pass/fail, appends status.

**Acceptance Criteria**:
- Auto-generates status/working_on from file paths
- Structural conflicts detected (all 5 patterns from architecture)
- Semantic conflict context recorded for decisions/conventions
- Auto-drafts decisions from significant changes
- Lint runs when config found, silent when not
- Commit size flagged when too large
- Test results parsed and recorded

---

## Milestone 3.4: Core Hooks — Customer & Subagent Tracking

**Goal**: Customer voice, notifications, subagent bookkeeping.

**Deliverables**:
- [ ] `scripts/user_prompt_log.py` — UserPromptSubmit. Reads `prompt` from input. Appends as `customer_input` event.
- [ ] `scripts/customer_notify.py` — Notification. OS detection (macOS `osascript` / Linux `notify-send`). Desktop notification for 🔴 questions.
- [ ] `scripts/subagent_stop.py` — SubagentStop. Reads `last_assistant_message`, `agent_id`. Appends `status` summarizing subagent work. Structural conflict detection.

**Acceptance Criteria**:
- Every user prompt logged as customer_input event
- Desktop notification on macOS and Linux for 🔴 questions
- Subagent work recorded, conflicts detected
- All hooks skip xp- prefixed agents

---

## Milestone 4: Agent Hooks — Quality & Navigation

**Goal**: XP practice enforcement on every code change.

**Deliverables**:
- [ ] `scripts/navigator_gate.py` — PreToolUse command hook (matcher: `Write|Edit|MultiEdit`). Significance filter: new file, large edit, file in SMM decisions/conventions. Start conservative.
- [ ] `prompts/navigator.md` — PreToolUse agent hook. Reads tool_input + SMM. Strategic guidance. Can block (exit 2) if change contradicts decisions. Writes `pair_guidance` events to log.
- [ ] `prompts/quality_reviewer.md` — PostToolUse agent hook (async, matcher: `Write|Edit|MultiEdit`). Courage + simplicity. Flags: empty catch, missing error handling, unnecessary complexity, premature abstraction, growing file size. Writes `concern` events. Clean code gets clean review.
- [ ] `scripts/plan_review.py` — SubagentStop command hook (matcher: `Plan`). Passes plan to plan_reviewer agent hook.
- [ ] `prompts/plan_reviewer.md` — Reviews plan: size, incremental delivery, test strategy. Extracts decisions/assumptions to SMM.

**Acceptance Criteria**:
- Navigator gate fires for significant changes, skips trivial
- Navigator provides strategic guidance, blocks on decision contradictions
- Navigator writes pair_guidance events
- Quality reviewer flags real issues, approves clean code
- Quality reviewer runs async, writes concerns to SMM
- Plan reviewer flags oversized plans, extracts decisions/assumptions
- All agent hooks skip xp- prefixed agents

---

## Milestone 5: Agent Hooks — Session Lifecycle

**Goal**: Retrospective, customer triage, subagent review, TDD gate.

**Deliverables**:
- [ ] `scripts/retrospective.py` — Data preparation. Checks for unanalyzed events. Gathers event log + last 2-3 retrospective files. Writes `.retro-input.json`. Exit 0 = needed, exit 1 = not needed.
- [ ] `prompts/retrospective_analyst.md` — SessionStart agent hook. Keep/Fix/Try with XP values as lenses (Honesty, Communication, Courage, Simplicity, Respect). Writes to `retrospectives/<timestamp>.json`. Runs materializer. Returns Keep/Fix/Try + SMM to main agent. "Insufficient data" for <5 events.
- [ ] Retrospective output schema (see architecture doc for full spec)
- [ ] `prompts/customer_proxy.md` — SessionStart agent hook. Reads open questions. Triages via AskUserQuestion. Records answers as events. Skipped if no open questions.
- [ ] `prompts/subagent_reviewer.md` — SubagentStop agent hook (async). Reads agent_transcript_path. Reviews: conventions, complexity, decision alignment. Writes concerns. Skips xp- agents.
- [ ] `prompts/tdd_check.md` — Stop prompt hook. Tests passing? Agent completed commitments? Blocks if not. `stop_hook_active` guard.

**Acceptance Criteria**:
- Retrospective produces Keep/Fix/Try grounded in specific events
- Every Keep has event references, every Fix has XP value context, every Try is actionable
- "Insufficient data" for <5 events
- Cross-session trends from previous retrospectives
- Customer proxy triages via AskUserQuestion, records answers
- Subagent reviewer evaluates holistic output, skips own agents
- TDD check blocks on test failure, respects stop_hook_active
- Keep/Fix/Try visible to user at session start

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

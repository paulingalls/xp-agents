# Development Milestones

**Test Summary** (317 automated tests, 0 manual):
| Suite | Tests | Covers |
|-------|-------|--------|
| `smm/test_smm.py` | 78 | Milestone 1 (Foundation) |
| `smm/test_engine.py` | 112 | Milestone 2 (Engine) |
| `scripts/test_hooks.py` | 127 | Milestones 3.1, 3.2, cross-cutting |

---

## Milestone 1: SMM Foundation ✅

**Goal**: Data layer.

**Status**: Complete (2026-03-12)

**Deliverables**:
- [x] `smm/schema.json` — 12 event types (added `answer`): `customer_input`, `status`, `decision`, `convention`, `concern`, `discovery`, `question`, `answer`, `assumption`, `pair_guidance`, `session_end`, `retrospective`. `status` has `working_on`. `question` has `priority` (🔴/🟡/🟢). `decision`/`convention` require `topic`. `pair_guidance` requires `tool_name`. All events have optional `metadata`, `schema_version`, `references`.
- [x] `smm/init.sh` — Initialize `~/.claude/xp-agents/{project-id}/smm/`. Derives `project-id` from `git rev-parse --git-common-dir` (resolved to absolute path, SHA256 first 12 chars). Idempotent. Validates Python 3.10+. Creates `events.jsonl`, `events.lock`, `retrospectives/`.
- [x] `smm/append.sh` — Thin bash wrapper delegating to `smm/_append_impl.py`.
- [x] `smm/_append_impl.py` — Event construction, hand-written validation, `fcntl.flock` atomic append with 2-second timeout. Uses `match/case`, `argparse`, `pathlib`. Stdlib only.
- [x] `LICENSE` (MIT), `CHANGELOG.md`

**Acceptance Criteria** (all automated in `smm/test_smm.py` + `scripts/test_hooks.py`):
- [x] Schema covers all 12 types with correct required/optional fields — `TestSchemaJson`
- [x] `init.sh` derives consistent project-id (absolute path resolution before hashing) — `TestInit.test_init_succeeds`
- [x] `init.sh` idempotent; second call succeeds silently — `TestInit.test_init_idempotent`
- [x] All 12 event types append successfully; invalid types and missing required fields rejected (exit 1) — `TestAppendIntegration`
- [x] 20 concurrent writes: all valid JSON, zero corruption, 20 unique agent_ids — `TestConcurrentWrites.test_20_concurrent_writes`
- [x] Python stdlib only, match/case throughout, macOS compatible — `TestStdlibOnly.test_no_external_imports`

---

## Milestone 2: SMM Engine ✅

**Goal**: Read side.

**Status**: Complete (2026-03-12)

**Deliverables**:
- [x] `smm/materialize.py` — events.jsonl → SHARED_MENTAL_MODEL.md. Groups by type. Detects 5 structural conflicts. Atomic write (tempfile + rename). Skips malformed lines (warns to stderr). Unknown types rendered under "Unknown Events".
- [x] `smm/read_delta.py` — Events since `.watermark-{agent-id}`. Tiered filtering: full, blocking-only (🔴 + pair_guidance), 🔴-only. Accepts `agent_id` param (default `main`). Watermark only advances on full reads.
- [x] `smm/test_engine.py` — 112 tests covering all acceptance criteria.

**Acceptance Criteria** (all automated in `smm/test_engine.py`):
- [x] Correct Markdown from sample logs covering all 12 types — `TestRenderMarkdown.test_all_12_types_render`
- [x] Conflict alerts for overlapping working_on, assumption-discovery contradictions, convention violations, stale questions, superseded decisions — `TestConflictDetection` (5 tests)
- [x] Per-agent watermarks, tiered filtering — `TestWatermark`, `TestFilterByTier`, `TestReadDelta`
- [x] Handles empty, single-event, and corrupted logs — `TestParseEvents`
- [x] Kill mid-write → old or new version, never half-written (atomic write via tempfile + rename) — `TestMaterializeToFile.test_atomic_write_complete`

---

## Milestone 3.1: Core Hooks — Session Lifecycle ✅

**Goal**: Plugin skeleton. After this, the plugin loads, sessions are tracked, SMM injects.

**Status**: Complete (2026-03-12)

**Deliverables**:
- [x] `hooks/hooks.json` — All hook registrations. Correct matchers, timeouts, handler types. Paths use `${CLAUDE_PLUGIN_ROOT}`.
- [x] `.claude-plugin/plugin.json` — Plugin manifest.
- [x] `settings.json` — Default plugin settings.
- [x] `scripts/session_start.py` — SessionStart (startup, resume, compact). Calls `init.sh`. Checks for unanalyzed events. Two modes: unanalyzed events → prepare retro input + instruction for retrospective agent hook + GUPP + skills. No events → full SMM directly + GUPP + skills. Output via `additionalContext`.
- [x] `scripts/session_end.py` — SessionEnd. Computes duration, event count, unresolved items, active working_on, missing final status flag. Appends `session_end` event. Non-blocking.
- [x] `scripts/pre_compact.py` — PreCompact. Timestamped backup of events.jsonl and SHARED_MENTAL_MODEL.md.
- [x] `scripts/subagent_start.py` — SubagentStart. Runs materializer, injects full SMM via `additionalContext`. Creates `.watermark-{agent_id}`.

**Acceptance Criteria** (all automated in `scripts/test_hooks.py`):
- [x] Plugin loads without errors — `TestPluginConfig` (4 tests)
- [x] SessionStart initializes SMM on first run, re-injects after compaction — `TestSessionStart.test_startup_returns_context`, `test_compact_returns_context`
- [x] SessionStart detects unanalyzed events and signals for retrospective — `TestSessionStart.test_retro_triggered_when_enough_events`, `test_retro_not_triggered_with_few_events`, `test_retro_reset_after_retrospective_event`
- [x] SessionEnd captures all summary fields — `TestSessionEnd` (duration, event_count, unresolved, working_on, final_status — 14 tests)
- [x] SubagentStart injects SMM and creates watermark — `TestSubagentStart.test_returns_smm_content`, `test_writes_watermark`
- [x] All hooks pass through gracefully when SMM missing — `test_graceful_no_smm_dir` / `test_missing_smm_dir` on all 4 hooks
- [x] All hooks check agent_id/agent_type, skip `xp-` prefixed agents — `test_xp_agent_skips` on all 4 hooks

---

## Milestone 3.2: Core Hooks — PreToolUse ✅

**Goal**: Delta injection, conflict prevention, TDD ordering.

**Status**: Complete (2026-03-12)

**Deliverables**:
- [x] `scripts/pre_tool_use.py` — PreToolUse (matcher: `*`). Reads `agent_id` (fallback `main`). Tiered delta injection via `additionalContext`: full delta for Write/Edit/MultiEdit/Bash(git commit), 🔴+pair_guidance for other Bash, 🔴-only for Read/Grep/Glob. Checks `working_on` overlap → exit 2 if conflict. TDD order tracking: records file write order, flags implementation-before-test.
- [x] `scripts/_common.BlockedError` — Exception for exit-2 blocking, keeps `run()` testable.

**Acceptance Criteria** (all automated in `scripts/test_hooks.py`):
- [x] Correct tier of delta based on tool_name — `TestClassifyTier` (9 tests)
- [x] Per-agent watermarks via agent_id — `TestPreToolUseRun.test_write_gets_full_delta`
- [x] Blocks on working_on overlap (exit 2 with explanation) — `TestCheckWorkingOnOverlap` (5 tests), `TestPreToolUseRun.test_conflict_raises_blocked`
- [x] Flags implementation-before-test ordering via additionalContext — `TestCheckTddOrder` (5 tests)
- [x] Fast — minimal overhead on every tool call — `TestPreToolUsePerformance` (100 runs < 2s, 1000 xp-agent skips < 1s)

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

**Deferred Security Items** (from M3.2 security audit, 2026-03-12):
- [ ] **Unbounded events.jsonl reads** (HIGH) — `_common.read_events_raw()`, `read_delta._read_with_lock()`, and `materialize.parse_events()` all slurp entire file into memory. Fires on every tool call via PreToolUse. Fix: compaction that truncates old events, and/or byte-offset watermarks to avoid re-reading old data, and/or file size cap that triggers compaction.
- [ ] **SIGALRM is process-global** (MEDIUM) — `_append_impl.py`, `read_delta.py`, `materialize.py` all use `signal.alarm()` for flock timeout. Not thread-safe, only one alarm active at a time, only works in main thread. Fix: replace with `fcntl.flock(LOCK_NB)` in a retry loop with `time.monotonic()` deadline.
- [ ] **TDD tracker TOCTOU** (MEDIUM) — `pre_tool_use.check_tdd_order()` does read-modify-write on `.tdd-{agent_id}.json` with no locking. Concurrent PreToolUse hooks for same agent can lose writes. Fix: flock around the read-modify-write cycle.
- [ ] **Watermark read/write race in read_delta** (MEDIUM) — `read_delta()` reads watermark, reads events under shared lock, then writes watermark outside any lock. Concurrent callers for same agent_id can regress watermark. Fix: exclusive lock around the full read_delta sequence.
- [ ] **Backup rotation** (MEDIUM) — `pre_compact.py` creates timestamped backups with no pruning. Unbounded disk growth over time. Fix: keep last N backups (e.g., 10), delete older ones after creating new.
- [ ] **Symlink following on event reads** (LOW) — `read_delta._read_with_lock()`, `materialize._read_with_lock()`, and `_common.read_events_raw()` use `path.read_text()` which follows symlinks, while the write path correctly uses `O_NOFOLLOW`. Fix: open `events.jsonl` with `O_RDONLY | O_NOFOLLOW` in all read paths.
- [ ] **Watermark/line-count mismatch in subagent_start** (LOW) — `subagent_start.py` sets watermark from `len(events)` (valid parsed events) but `read_delta` watermarks are line-based. Malformed lines cause drift. Fix: use `read_delta.read_events_from()` which returns `total_lines`.
- [ ] **Content field length limits** (LOW) — `_append_impl.validate_event()` checks types but not string lengths. Multi-megabyte `content` field bloats event log. Fix: max length for `content` (e.g., 8KB), `topic` (256B), other string fields.
- [ ] **Watermark/tracker file accumulation** (LOW) — Each unique agent_id creates `.watermark-{id}` and `.tdd-{id}.json` files. Many subagents over time fills SMM dir. Fix: clean up stale files during session end or compaction.

**Acceptance Criteria**:
- Materialization <500ms for 1,000 events
- Graceful degradation under all conditions
- Repair recovers corrupted logs
- Migration upgrades between schema versions
- Agent Teams items verified
- All deferred security items addressed or risk-accepted

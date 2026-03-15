# Development Milestones

## Milestone 1: SMM Foundation ✅

**Goal**: Data layer.

**Deliverables**:
- [x] `smm/schema.json` — 11 event types: `customer_input`, `status`, `decision`, `convention`, `concern`, `discovery`, `question`, `assumption`, `pair_guidance`, `session_end`, `retrospective`. `status` has `working_on`. `question` has `priority` (🔴/🟡/🟢). All events have optional `metadata`, `schema_version`, `references`.
- [x] `smm/init.sh` — Initialize `~/.claude/xp-agents/{project-id}/smm/`. Derives `project-id` from `git rev-parse --git-common-dir`. Idempotent. Validates Python 3.10+. Creates `events.jsonl`, `events.lock`, `retrospectives/`. Crash-safe. Uses `${CLAUDE_PLUGIN_ROOT}`.
- [x] `smm/append.sh` — Atomic append. JSON construction, schema validation, `flock` writes. Generates `id` and `ts`. Exits 1 on validation failure.
- [x] `LICENSE` (MIT), `CHANGELOG.md`

**Acceptance Criteria**:
- ✅ Schema covers all 11 types with correct fields
- ✅ `init.sh` derives consistent project-id across worktrees
- ✅ `init.sh` idempotent; recovers from partial completion
- ✅ `append.sh` validates, rejects malformed, handles 20 concurrent writes
- ✅ Python stdlib only, use match/case where appropriate, macOS + Linux

---

## Milestone 2: SMM Engine ✅

**Goal**: Read side.

**Deliverables**:
- [x] `smm/materialize.py` — events.jsonl → SHARED_MENTAL_MODEL.md. Groups by type. Detects structural conflicts. Atomic write (tempfile + rename). Skips malformed lines (emits concern). Unknown types rendered under "Unknown Events".
- [x] `smm/read_delta.py` — Events since `.watermark-{agent-id}`. Tiered filtering: full, blocking-only (🔴 + pair_guidance), 🔴-only. Accepts `agent_id` param (default `main`). Updates watermark after read.

**Acceptance Criteria**:
- ✅ Correct Markdown from sample logs covering all 11 types
- ✅ Conflict alerts for overlapping working_on, assumption-discovery contradictions, convention violations
- ✅ Per-agent watermarks, tiered filtering
- ✅ Handles empty, single-event, and corrupted logs
- ✅ Kill mid-write → old or new version, never half-written

---

## Milestone 3.1: Core Hooks — Session Lifecycle ✅

**Goal**: Plugin skeleton. After this, the plugin loads, sessions are tracked, SMM injects.

**Deliverables**:
- [x] `hooks/hooks.json` — All hook registrations. Correct matchers, timeouts, handler types. Paths use `${CLAUDE_PLUGIN_ROOT}`.
- [x] `.claude-plugin/plugin.json` — Plugin manifest.
- [x] `settings.json` — Default plugin settings.
- [x] `scripts/session_start.py` — SessionStart (startup, resume, compact). Calls `init.sh`. Checks for unanalyzed events. Two modes: unanalyzed events → prepare retro input + instruction for retrospective agent hook + GUPP + skills. No events → full SMM directly + GUPP + skills. Output via `additionalContext`.
- [x] `scripts/session_end.py` — SessionEnd. Computes duration, event count, unresolved items, active working_on, missing final status flag. Appends `session_end` event. Non-blocking.
- [x] `scripts/pre_compact.py` — PreCompact. Timestamped backup of events.jsonl and SHARED_MENTAL_MODEL.md.
- [x] `scripts/subagent_start.py` — SubagentStart. Runs materializer, injects full SMM via `additionalContext`. Creates `.watermark-{agent_id}`.

**Acceptance Criteria**:
- ✅ Plugin loads without errors
- ✅ SessionStart initializes SMM on first run, re-injects after compaction
- ✅ SessionStart detects unanalyzed events and signals for retrospective
- ✅ SessionEnd captures all summary fields
- ✅ SubagentStart injects SMM and creates watermark
- ✅ All hooks pass through gracefully when SMM missing
- ✅ All hooks check agent_id/agent_type, skip `xp-` prefixed agents

---

## Milestone 3.2: Core Hooks — PreToolUse ✅

**Goal**: Delta injection, conflict prevention, TDD ordering.

**Deliverables**:
- [x] `scripts/pre_tool_use.py` — PreToolUse (matcher: `*`). Reads `agent_id` (fallback `main`). Tiered delta injection via `additionalContext`: full delta for Write/Edit/MultiEdit/Bash(git commit), 🔴+pair_guidance for other Bash, 🔴-only for Read/Grep/Glob. Checks `working_on` overlap → exit 2 if conflict. TDD order tracking: records file write order, flags implementation-before-test.

**Acceptance Criteria**:
- ✅ Correct tier of delta based on tool_name
- ✅ Per-agent watermarks via agent_id
- ✅ Blocks on working_on overlap (exit 2 with explanation)
- ✅ Flags implementation-before-test ordering via additionalContext
- ✅ Fast — minimal overhead on every tool call

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

## Milestone 5.1: Agent Hooks — Session Lifecycle ✅

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

## Milestone 5.2: SMM Enhancements — Schema & Materializer ✅

**Goal**: New event types, two-tier materialized view, debt aging, session stats.

**Status**: Complete (585 total tests: 228 SMM + 309 hooks + 50 integration, 34 new tests for M5.2).

**Deliverables**:
- [x] Add `goal`, `debt`, and `customer_intent` event types to `schema.json` and `_append_impl.py`. `customer_intent` has `intent_status` (open / delivered / superseded). `debt` requires `files` array. `goal` has no extra required fields.
- [x] Update `retrospective.py` — `_compute_session_stats()` computes pair_guidance_count, status_count, concerns raised/resolved, questions open/answered, decisions total/draft. Included in `.retro-input.json`.
- [x] Rewrite `materialize.py` — two-tier output: Active Context (goals, conflict alerts, 🔴 questions, unacknowledged concerns, customer intent, agent status, navigator guidance) above Reference (decisions, conventions, resolved questions, discoveries, assumptions, technical debt, resolved concerns)
- [x] Debt aging in `materialize.py` — `bisect.bisect_right` on session_end timestamps. Thresholds: 0–3 normal, 4–6 ⚠️, 7+ 🔴.
- [x] Goals pinned at top of Active Context with 🎯 prefix
- [x] Customer Intent section in Active Context — open items only with 📋 prefix, source refs resolved via `by_id`
- [x] Navigator guidance scoped to current session (events after `last_session_end_pos`)
- [x] Customer Input section removed from materialized view
- [x] `read_delta.py` — `format_delta()` handles goal, debt, customer_intent
- [x] Centralized `_append_impl.py` as foundational module — `resolve_smm_dir`, `_validate_smm_dir`, `_validate_agent_id`, `LockTimeoutError`, `read_with_lock`, `write_watermark`, `compute_resolutions`, `VALID_TYPES`, `PRIORITY_*` constants defined once. `materialize.py`, `read_delta.py`, `_common.py` import from it.
- [x] Security: watermark symlink protection (O_NOFOLLOW), `normalize_path` resolves symlinks, `references`/`files` items validated as strings

**Design decisions**:
- `_append_impl.py` is the foundational module: all shared SMM primitives defined once, consumers import. Eliminates 6 duplicated functions.
- `compute_resolutions()` shared by materializer, retrospective, session_end, and detect_conflicts — single definition of "which questions are answered, which concerns are resolved."
- Navigator guidance scoped by event position vs. `last_session_end_pos` (not session_id), since session_id is not stored on guidance events.
- `PRIORITY_BLOCKING` / `PRIORITY_ASSUMED` / `PRIORITY_INFO` replace `PRIORITY_RED` — semantic names instead of color names.

**Acceptance Criteria**:
- ✅ Goals appear at top of materialized SMM with 🎯 prefix
- ✅ Active Context / Reference tiers render with `---` dividers and `## ACTIVE CONTEXT` / `## REFERENCE` headers
- ✅ Customer Intent section shows open items only with 📋 prefix
- ✅ Debt age renders correctly based on session_end count after debt timestamp
- ✅ Debt at 7+ sessions renders with 🔴
- ✅ Navigator guidance clears across sessions (scoped to after last session_end)
- ✅ Session stats computed and included in `.retro-input.json`
- ✅ All 15 event types render correctly
- ✅ Plugin version bumped to 0.5.2

---

## Milestone 5.3: SMM Enhancements — Debt & Goal Integration ✅

**Goal**: Wire goals, debt, and customer intent into agent prompts and tiered injection.

**Deliverables**:
- [x] Update `customer_proxy.md` — on first run (empty SMM / no goal events), ask for project goals via AskUserQuestion. Non-blocking. On subsequent sessions: reconcile customer intent — review open `customer_intent` events against status/commit/decision events in log, mark delivered, distill new intents from `customer_input` events since last session. Err toward keeping intents open when completion is ambiguous.
- [x] Update `navigator.md` — when agent modifies a file with associated debt, include debt in guidance. Nudge to address or justify skipping.
- [x] Update `quality_reviewer.md` — can write `debt` events for acknowledged tradeoffs (distinct from `concern`). Writes `concern` if agent touches file with debt and doesn't address it.
- [x] Update `retrospective_analyst.md` — can write `debt` events when a Fix is deferred intentionally. Aging debt (4+ sessions) appears in Fix items with escalating urgency. Debt referenced by multiple concerns gets highest priority. Analyze session stats for plugin health anomalies: flag 0 navigator guidance with many writes, high unresolved concern ratio, 0 decisions despite significant work. Compare stats against previous retrospectives for cross-session trends.
- [x] Update `pre_tool_use.py` tiered injection — non-write tools get Active Context only, write tools get full SMM
- [x] Add `enforcement` setting to `settings.json` — `strict` (default) or `advisory`. In advisory mode, all exit-2 blocks become warnings via additionalContext instead. Same hooks fire, same events recorded — nothing blocks. All blocking hooks (`pre_tool_use.py`, `tdd_check.md`, `navigator.md`) read this setting.

**Acceptance Criteria**:
- [x] `strict` mode blocks on TDD failure, working_on conflicts, decision contradictions
- [x] `advisory` mode converts all blocks to warnings — same events recorded, no exit 2
- [x] Default is `strict` — no behavior change for users who don't touch settings
- [x] First session on a new project asks for goals
- [x] Customer proxy distills new intents from customer_input events
- [x] Open intents carried forward across sessions
- [x] Delivered intents marked based on event log activity (not code inspection)
- [x] Ambiguous completion keeps intent open
- [x] Debt events tracked separately from concerns
- [x] Navigator nudges on debt when touching associated files
- [x] Quality reviewer flags ignored debt as concern
- [x] Retrospective escalates aging debt in Fix items
- [x] Retrospective flags plugin health anomalies from session stats
- [x] Cross-session stat trends surfaced in Keep/Fix/Try
- [x] Non-write PreToolUse injection contains only Active Context

---

## Milestone 5.4: Auto-Simplify at Loop End ✅

**Goal**: Automatically run `/simplify` when the agent finishes a loop that changed files. Cross-file reuse, quality, and efficiency review at natural boundaries — not per-file.

**Status**: Complete (637 total tests, 16 new tests for M5.4).

**Deliverables**:
- [x] `scripts/simplify_gate.py` — Stop command hook. Reads events since last `customer_input` to detect file changes (via `status` events with `working_on`). Checks tracker file (`.simplify-{agent_id}.json`) to avoid re-triggering after simplify already ran. If files changed and simplify hasn't run: writes tracker, blocks via exit 2 with stderr instruction to run `/simplify`. If no files changed or simplify already ran: exits 0 silently.
- [x] `hooks/hooks.json` — Register `simplify_gate.py` as command hook on Stop, before `tdd_check.md`. Order: simplify gate (command) → tdd check (prompt).
- [x] Tests for `simplify_gate.py`: file changes detected, no changes skips, tracker prevents re-trigger, new loop resets tracker, xp-agent recursion prevention, stop_hook_active guard, missing SMM graceful degradation, integration tests (subprocess exit codes).

**Design decisions**:
- **No prompt hook** — hooks within the same Stop entry run in parallel, so command hook's `additionalContext` is not visible to a prompt hook. Command hook blocks directly via exit 2.
- **No settings gate** — always on. Can add opt-out later if needed.
- **No special SMM integration** — simplify's subagents are captured by existing SubagentStop hooks, its code fixes by existing PostToolUse hooks. The hook infrastructure *is* the integration layer.
- **Tracker file per agent** — `.simplify-{agent_id}.json` in SMM dir, contains loop identifier (last `customer_input` event ID). New loop = new ID = fresh trigger. No explicit clearing needed.
- **Order matters** — simplify gate runs before tdd_check. Simplify may fix code, then tdd_check verifies tests still pass.

**Acceptance Criteria**:
- ✅ Agent that modifies files gets `/simplify` instruction at Stop
- ✅ Agent that only reads/answers questions stops without simplify
- ✅ Simplify runs at most once per loop (tracker prevents re-trigger)
- ✅ After simplify fixes code, tdd_check still gates on test status
- ✅ Existing SubagentStop and PostToolUse hooks capture simplify's work in SMM
- ✅ xp- agents skip the gate (recursion prevention)
- ✅ Missing SMM dir degrades gracefully (no simplify, no crash)

---

## Milestone 5.5: Security Review Gate & Retrospective Security Lens ✅

**Goal**: Block `git push` until a security review has been run. Add security awareness to the retrospective. Leverage Anthropic's built-in `/security-review` — we own enforcement, they own review quality.

**Status**: Complete (711 total tests: 228 SMM + 406 hooks + 77 integration, 42 new tests for M5.5).

**Deliverables**:
- [x] `pre_tool_use.py` — detect `git push` in Bash commands (new classification alongside `git commit`). Check `.security-reviewed-{commit-hash}` tracker file in SMM dir. If no tracker for current HEAD: write `security_review_requested` event to SMM, inject `additionalContext` instructing agent to run `/security-review` (strict mode blocks via exit 2, advisory mode warns). If tracker exists: pass through.
- [x] Three-path security review detection — all paths write the `.security-reviewed-{HEAD-hash}` tracker file when a security review is detected:
  - **Path 1: User-initiated** — `user_prompt_log.py` (UserPromptSubmit) scans the prompt for security review patterns (`/security-review`, `security review`, `security audit`). On match, writes tracker with current HEAD hash.
  - **Path 2: Agent-initiated** — `subagent_stop.py` (SubagentStop) checks `last_assistant_message` for security review output signatures (severity markers, vulnerability format, "No vulnerabilities found"). On match, writes tracker.
  - **Path 3: Gate-requested** — push gate blocks and writes `security_review_requested` event. Detection happens via Path 1 or Path 2 when the review actually runs.
- [x] Tracker file management — `.security-reviewed-{commit-hash}` in SMM dir. Keyed on HEAD commit hash so new commits invalidate. Old tracker files cleaned up on write (keep only current). Atomic write pattern.
- [x] `prompts/retrospective_analyst.md` — add security lens: were security concerns raised during the session? Were they addressed? Did pushes happen without security review (tracker gaps)? Were `security_review_requested` events followed by completion? Surface as Fix items under the Courage value.
- [x] Tests: push gate detection, tracker prevents re-trigger, new commits invalidate tracker, UserPromptSubmit pattern matching, SubagentStop message detection, xp-agent recursion prevention, missing SMM graceful degradation, advisory vs strict mode behavior

**Design decisions**:
- **Three detection paths** — security reviews can originate from the user (`/security-review` command or natural language request), the agent (self-initiated), or our push gate (enforcement). All three paths are observable through existing hooks: UserPromptSubmit sees user input, SubagentStop sees subagent output, and the push gate writes a request event. No reliance on agent cooperation to write the tracker.
- **Leverage `/security-review`** — Anthropic's built-in skill handles language-specific patterns (Python, TypeScript, Go, Rust, etc.). We don't write our own security scanner.
- **Gate on invocation, not outcome** — our gate checks whether a security review was run, not what it found. The review writes its own findings; the agent decides how to act on them. This keeps us decoupled from the skill's internals.
- **Commit hash keying** — tracker keyed on `git rev-parse HEAD`. Push with new commits after the review? Hash changed, review needed again. Multiple pushes of the same HEAD? Tracker still valid.
- **No `origin/HEAD` dependency** — our gate doesn't need `origin/HEAD`. If `/security-review` needs it internally, that's Anthropic's concern, not ours.
- **Retrospective security lens** — lightweight addition to existing prompt. Security is a quality dimension analyzed under the Courage value (were hard security questions raised?).

**Acceptance Criteria**:
- ✅ `git push` blocked in strict mode until security review has been run
- ✅ `git push` warns in advisory mode with enforcement indicator
- ✅ New commits after security review invalidate the tracker
- ✅ Same HEAD push passes without re-review
- ✅ User typing `/security-review` or "run a security review" writes tracker (Path 1)
- ✅ Subagent completing a security review writes tracker (Path 2)
- ✅ Push gate writes `security_review_requested` event when blocking (Path 3)
- ✅ Retrospective surfaces security review gaps as Fix items
- ✅ xp-agents skip the gate (recursion prevention)
- ✅ Missing SMM degrades gracefully
- ✅ Works regardless of project language

---

## Milestone 6: CLAUDE.md & Skills ✅

**Goal**: Behavioral rules and reference knowledge.

**Status**: Complete (730 total tests: 228 SMM + 131 engine + 422 hooks + 79 integration, 14 new tests for M6).

**Deliverables**:
- [x] `BEHAVIORAL_GUIDE.md` (~2,000–3,000 tokens) — Honesty Principle (7 rules), XP Values as behavior, Skills reference library (with explicit invocation guidance), Session Lifecycle (start/during/end), Code Quality (TDD, lint, complexity, small commits, security), Courage Commitments. Delivered via `additionalContext` injection in `session_start.py`, not as plugin CLAUDE.md (which is not an official plugin component).
- [x] `skills/smm-protocol/SKILL.md` (~1,000–1,500 tokens) — Event types, working_on, references, conflict response, good vs. bad event examples, common recording patterns.
- [x] `skills/xp-values/SKILL.md` (~1,000–1,500 tokens) — Values as behaviors, honesty as foundation, value priority when conflicting, practical examples.
- [x] `skills/pair-programming/SKILL.md` (~1,000–1,500 tokens) — Navigator/driver protocol, pair_guidance events, conflict resolution, debt in pair programming, session flow.

**Design change from plan**: `CLAUDE.md` renamed to `BEHAVIORAL_GUIDE.md` to avoid confusion with the dev guide at repo root. Content delivered via `session_start.py` `additionalContext` injection rather than as a plugin CLAUDE.md file (which is not an official plugin component per the plugin reference docs). Skills prominently referenced in the guide with explicit "invoke when" instructions since they are voluntary (not hook-enforced).

**Acceptance Criteria**:
- ✅ BEHAVIORAL_GUIDE.md ~2,000–3,000 tokens, readable in <3 minutes
- ✅ No contradictions with hook enforcement (tested)
- ✅ Skills have valid frontmatter with name + description
- ✅ Developer can append an event correctly after reading smm-protocol alone
- ✅ Skills are prominently referenced in guide to drive voluntary usage
- ✅ Graceful degradation when BEHAVIORAL_GUIDE.md is missing
- ✅ Injection order: SMM → enforcement → behavioral guide → GUPP → skills
- ✅ Plugin version bumped to 0.6.0

---

## Milestone 6.5: Agent Hook → Plugin Subagent Migration ✅

**Goal**: Fix non-functional agent hooks by migrating to plugin subagents with full tool access.

**Status**: Complete (715 total tests: 228 SMM + 131 engine + 406 hooks + 80 integration).

**Discovery**: Agent hooks (type: "agent" in hooks.json) can only use Read/Grep/Glob tools — no Bash, Write, or Edit (confirmed empirically 2026-03-14). All 6 agent hook prompts that called `append.sh` or returned advisory guidance never actually worked as designed.

**Solution**: Plugin subagents (`agents/` directory) have full tool access. Command hooks trigger them via `additionalContext` nudge or exit 2 blocking.

**Deliverables**:
- [x] 6 plugin subagents in `agents/` directory: xp-navigator, xp-quality-reviewer, xp-retrospective, xp-customer-proxy, xp-plan-reviewer, xp-subagent-reviewer
- [x] All agent hooks removed from `hooks/hooks.json` — only command + 1 prompt hook remain
- [x] Command hooks updated with subagent nudges: pre_tool_use.py (navigator), post_tool_use.py (quality reviewer), retrospective.py (retrospective), session_start.py (customer proxy), subagent_stop.py (plan reviewer block + subagent reviewer nudge)
- [x] Old prompt files deleted (navigator.md, quality_reviewer.md, etc.) — only tdd_check.md remains in prompts/
- [x] plan_review.py command hook removed (redundant)

**Acceptance Criteria**:
- ✅ No agent hooks in hooks.json (only command + prompt)
- ✅ All 6 subagent files have valid frontmatter with tools, skills, model
- ✅ Background subagents (quality-reviewer, subagent-reviewer) have background: true
- ✅ Customer proxy is foreground (needs AskUserQuestion)
- ✅ Plan reviewer uses exit 2 blocking (deterministic, like simplify_gate)
- ✅ All subagents preload smm-protocol skill and include append.sh usage
- ✅ Recursion prevention works via existing is_xp_agent() check
- ✅ Plugin version bumped to 0.7.0

---

## Milestone 7: Integration Testing & Packaging ✅

**Goal**: End-to-end, marketplace ready.

**Status**: Complete (736 total tests: 228 SMM + 131 engine + 415 hooks + 92 integration, 21 new tests for M7).

**Deliverables**:
- [x] `.claude-plugin/marketplace.json` — marketplace publishing manifest
- [x] `TestPluginIntegrity` (9 tests) — validates all plugin artifacts exist and are well-formed
- [x] Integration tests:
  - [x] Full session lifecycle: start → pre_tool_use(Write) → post_tool_use → session_end
  - [x] 3-session accumulation test with cross-session retro trends
  - [x] Concurrent multi-agent writes (5 workers, ThreadPoolExecutor)
  - [x] Plan subagent → block + review instruction
  - [x] Compaction → full SMM re-injection
- [x] Edge cases: empty project, 1000+ events, concurrent writes, worktree project-id sharing
- [x] CHANGELOG.md complete

**Acceptance Criteria**:
- ✅ Marketplace manifest exists with required fields
- ✅ 3-session integration passes with cross-session trend visibility
- ✅ 1000+ events handled without error across pre_tool_use, materialize, retrospective
- ✅ Concurrent writes (5 agents) produce no corruption or duplicate IDs
- ✅ Worktree shares same SMM directory as main repo
- ✅ Empty project degrades gracefully with goal collection nudge
- ✅ All plugin artifacts validated (scripts, prompts, agents, skills, settings)
- ✅ Zero external dependencies confirmed
- ✅ Plugin version bumped to 0.8.0

---

## Milestone 8: Hardening & Optimization ✅

**Goal**: Production-ready. SMM integrity verification.

**Status**: Complete (802 total tests: 98 SMM + 188 engine + 415 hooks + 101 integration, 66 new tests for M8).

**Deliverables**:
- [x] Performance benchmarks — materialize <100ms/100, <500ms/1000, <2000ms/5000 events. read_delta <50ms/1000@500. compact <1000ms/5000. repair <1000ms/5000
- [x] Async/Agent Teams verification — watermark isolation (3 agents concurrent), compact resets watermarks
- [x] Log management (`smm/compact.py`) — archives old events, keeps permanent types + unresolved items + last N sessions. PostCompact hook
- [x] Recovery (`smm/repair.py`) — skips malformed, validates required fields, deduplicates, sorts. Dry-run available
- [x] Schema versioning (`smm/migrate.py`) — CURRENT_VERSION=2, v1→v2 normalizes timestamps. Forward-compatible (future versions pass through)
- [x] **Drift Signals** (A8) — stale decisions (5+ sessions), ignored conventions (3+ unresolved concerns). Event-log-only
- [x] **Velocity Signal** (A9) — events this session, total sessions, decisions made/revisited, churn topics, concern resolution ratio
- [x] CHANGELOG, MILESTONES, version bump to 0.9.0

**Acceptance Criteria**:
- ✅ Materialization <500ms for 1,000 events
- ✅ Graceful degradation under all conditions
- ✅ Repair recovers corrupted logs
- ✅ Migration upgrades between schema versions
- ✅ Agent Teams items verified (watermark isolation, concurrent access)
- ✅ Drift signals detect: superseded decisions, ignored conventions (via concern count), stale decisions (no recent activity), contradicted assumptions
- ✅ Drift analysis uses event log only — no codebase I/O, no materialization performance impact
- ✅ Velocity signal accurately reports events per session and flags decision churn

---
---

## 2.0 — Autonomous Teams (Future)

**Prerequisite**: 1.0 shipped, dogfooded on a real project for multiple weeks. Friction points identified through retrospectives.

**Goal**: Agent Teams can execute a requirements document with minimal human intervention. Human approves goals and priorities once, then reviews outputs — not every decision.

**Milestone 9: Backlog & Planning Game**

- [ ] `backlog_item` event type — priority, acceptance criteria, dependencies, status (ready / in-progress / done / blocked)
- [ ] Backlog section in materialized SMM with progress summary
- [ ] Planning game at SessionStart — customer proxy picks next ready item, assigns to agent or teammate
- [ ] Plan reviewer validates plans against backlog — right item, respects dependencies, right-sized
- [ ] Burn down rendering in materializer — items completed vs. remaining, velocity, projected completion

**Milestone 10: Requirements Decomposition**

- [ ] SessionStart hook reads requirements document (markdown or structured) from project
- [ ] Decomposition agent breaks requirements into backlog items with acceptance criteria and dependencies
- [ ] Customer confirms priority ranking once via AskUserQuestion
- [ ] Backlog items flow into planning game automatically on subsequent sessions

**Milestone 11: Autonomous Decision-Making**

- [ ] Draft decision lifecycle in `materialize.py` — promotion (no concerns after N sessions → confirmed), escalation (concern count exceeds threshold → 🔴 question for customer). Same aging pattern as debt, applied in reverse: time without problems → confidence.
- [ ] Convention-based gates — conventions can require explicit customer approval for specific domains (e.g., "all auth decisions require approval"). Navigator and plan reviewer already enforce conventions, so this is configuration, not new code.
- [ ] Retrospective feedback loop — analyst tracks draft decision outcomes. High revision/contradiction rate → Fix item: "too many auto-decisions revised in {domain}, increase customer involvement." Evidence-based calibration, not a numeric threshold.
- [ ] Promotion thresholds configurable in `settings.json` — sessions-to-promote, concern-count-to-escalate. Conservative defaults.

**Open Questions (resolve during 1.0 dogfooding)**:
- How does the planner distribute backlog items across Agent Team teammates?
- What's the right default sessions-to-promote for draft decisions?
- How do dependencies between backlog items interact with multi-agent parallelism?
- Should the burn down feed into session length / sustainable pace decisions?
- What granularity of requirements decomposition produces right-sized backlog items?
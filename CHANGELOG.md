# Changelog

## v0.9.24 — Event Lifecycle System

### Added
- **Event lifecycle resolution** — `metadata.resolves` mechanism for explicitly closing goals, concerns, and debt. The materializer is a pure view: renders open vs. resolved, no heuristic aging or pruning.
- **`/xp-session-review`** — orchestrator skill that sequences retro → goals → housekeeping at session start. Enforced by dual gates.
- **`/xp-housekeeping`** — lifecycle triage skill. Reviews open goals, unresolved concerns, draft decisions, and technical debt. Asks user for status, records resolutions.
- **Session review gate (UserPromptSubmit)** — `session_review_gate.py` blocks prompts until `/xp-session-review` runs. Allows the command itself through.
- **Session review gate (PreToolUse)** — defense-in-depth, blocks ALL tools when `.needs-session-review` marker exists. xp-agents skip via recursion prevention.
- **Completed Goals** reference section in materialized SMM
- **ANSI escape code stripping** at write time in `_append_impl.py`
- **Concern content truncation** to 500 chars in materialized output
- 28 new tests (858 total)

### Changed
- **`session_start.py` slimmed** — no longer injects SMM or nudges. Writes `.needs-session-review` marker, injects behavioral guide + GUPP + skills only. Fresh SMM is injected after session review completes via PreToolUse delta.
- **`compute_resolutions()` rewritten** — uses `metadata.resolves` as sole resolution mechanism for goals, concerns, and debt. Old `references`-based concern resolution removed.
- **Agent status scoped to current session** — prior session agents no longer appear in materialized SMM
- **Open debt only** in Technical Debt section — resolved debt filtered out

### Fixed
- **`session_review_gate.py` SMM dir resolution** — was passing None to `try_validate_smm_dir`, making gate dead code in production
- **Marker deletion timing** — marker now cleared only when session review completes (step 4), not when it starts. Prevents gate bypass if review aborted.

## v0.9.20 — Security Review Hook, TDD unittest Detection, Preload Permission Fix

### Fixed
- **Push gate proper fix** — replaced second-push bypass with PostToolUse:Skill hook (`security_review_done.py`) that writes the `.security-reviewed-{hash}` tracker only when `/security-review` actually completes
- **TDD stop gate blind to unittest** — `bash_post_tool.py` only detected pytest/jest/go test. Added `python3 -m unittest` detection and result parsing so the TDD stop gate has data to work with
- **Skill preload permissions** — `!` command preloads go through the same Bash permission check as user commands. Fixed by adding `allowed-tools` patterns (e.g., `Bash(*/skills/*/scripts/*)`) to skill frontmatter to pre-approve preload scripts
- **Navigator allowed-tools cleanup** — removed redundant `Bash(*/preload.sh)` from navigator skill; `Bash(*/skills/*/scripts/*)` already covers it

### Added
- `scripts/security_review_done.py` — PostToolUse:Skill hook that writes security tracker after `/security-review` completes
- PostToolUse:Skill hook entry in `hooks.json`
- unittest result parser in `bash_post_tool.py` (handles `Ran N tests`/`FAILED (failures=X, errors=Y)`)
- Integration test for unittest detection pipeline

### Discovered
- **bash_failure.py false positive** — lefthook ruff formatting failures get misclassified as "Test run failed (pytest)" because the full lefthook output contains test-like patterns. The TDD stop gate then blocks on a non-test failure. Needs investigation.
- **Plugin cache requires version bump** — `/reload-plugins` alone isn't sufficient if the version in `plugin.json` hasn't changed. Bump version to force cache invalidation.

## v0.9.19 — Preload Fix, Navigator Gate, Push Gate Fix

### Fixed
- **Skill preload permissions** — removed `!`command`` preloads from all 7 skills that failed with Bash permission errors. Forked skills now load data via `Read` + `Bash(*/init.sh)` in `allowed-tools`. Inline skills reference SMM context already in conversation.
- **Push gate stuck** — second push attempt after security review now auto-clears the gate by detecting the existing `security_review_requested` event for the current HEAD.

### Added
- **Navigator gate on TaskCompleted** — blocks task completion unless navigator guidance (`pair_guidance` event) has been provided. Second attempt allows through to prevent infinite loops. Addresses the retro finding that navigator produced 0 guidance events.
- **Inline retrospective data** — SessionStart now includes session health signals, key event summaries, and K/F/T analysis instructions directly in `additionalContext`, so the main agent can perform retrospective analysis without needing to invoke the `/xp-retrospective` skill separately.

### Changed
- `retrospective.py` — enriched `_build_context_summary` with health signals (navigator silence, concern resolution ratio, draft decisions) and condensed key event list
- `task_completed.py` — converted from quality-reviewer nudge to navigator gate + quality-reviewer nudge

### Discovered
- **Agent hooks broken** — `type: "agent"` hooks fail on all events with "Messages are required for agent hooks. This is a bug." Platform issue in Claude Code, not fixable from plugin side. Use command/prompt hooks or forked skills instead.
- **`!`command`` preloads not auto-approved** — plugin skill preload scripts go through the same Bash permission check as user commands. No plugin-level permission override exists.
- **Dead code** — `prompts/tdd_check.md` (unused prompt hook file), 8 preload shell scripts (no longer referenced from SKILL.md)

## v0.9.17 — Skill-Based Agent Execution

### Added
- `docs/PLUGIN_TOOLS.md` — comprehensive reference for all plugin tool types (hooks, skills, subagents) and their data flows
- `skills/xp-goal-collection/` — inline skill for first-session goal collection (split from customer-proxy)
- `skills/xp-question-triage/` — inline skill for question triage and intent reconciliation (split from customer-proxy)
- `skills/xp-navigator/` — forked skill wrapping the navigator subagent with `!`command`` preload
- `skills/xp-quality-reviewer/` — forked skill wrapping the quality reviewer subagent
- `skills/xp-plan-reviewer/` — forked skill wrapping the plan reviewer subagent
- `skills/xp-retrospective/` — forked skill wrapping the retrospective subagent
- `skills/xp-subagent-reviewer/` — forked skill wrapping the subagent reviewer subagent
- `skills/_preload_base.sh` — shared preload base for deterministic SMM state injection via `!`command``
- Security review carryforward — when diff between last reviewed commit and HEAD contains only non-code files, carry forward the review instead of blocking
- `_common.is_code_file()` and `_common.diff_has_code_changes()` — shared code/non-code classification for security review carryforward

### Changed
- All hook nudge messages now say "Run /skill-name" instead of "Invoke the subagent"
- Customer-proxy functionality split into two focused skills for better auto-matching
- `lefthook.yml` — shellcheck now uses `-x -e SC1091` for source following

### Removed
- `agents/xp-customer-proxy.md` — replaced by inline skills `/xp-goal-collection` and `/xp-question-triage`
- `skills/xp-customer-proxy/` — replaced by the two focused skills above

### Design decisions
- **Inline skills for user interaction** — customer-facing skills run inline in the main agent for full tool access (AskUserQuestion, Bash)
- **Forked skills for analysis** — reviewer/navigator skills use `context: fork` + `agent:` to delegate to existing subagents with preloaded SMM state
- **`!`command`` for deterministic setup** — preload scripts run before skill content loads, agent cannot skip them
- **Security review carryforward** — fail-closed design: assumes code changes on error, only skips review when diff is provably non-code
- **Split customer-proxy** — single-responsibility: goal collection is first-run, question triage is ongoing. Better description matching for auto-invocation

## v0.9.0 — Milestone 8: Hardening & Optimization

### Added
- `smm/compact.py` — Log compaction: archives old events, keeps permanent types (decision, convention, goal, debt, assumption, retrospective) + unresolved questions/concerns + last N sessions. Configurable `keep_sessions` (default 3). Archives to `backups/archive-{ts}.jsonl`. Removes all watermarks after compaction. Registered as PostCompact hook
- `smm/repair.py` — Log recovery: skips malformed JSON, validates required fields, deduplicates by event ID, sorts by timestamp. Backs up original to `backups/pre-repair-{ts}.jsonl`. Writes `.repair-report.json`. Supports `--dry-run`
- `smm/migrate.py` — Schema versioning framework: additive-only migrations with `CURRENT_VERSION = 2`. v1→v2: normalize timestamps to include timezone. Events with `schema_version > CURRENT` pass through unchanged (forward-compatible)
- **Drift Signals** (A8) — New Active Context section in materializer. Detects: stale decisions (topic with no activity in 5+ sessions), ignored conventions (3+ unresolved concerns referencing convention). Event-log-only analysis, no codebase I/O
- **Velocity** (A9) — New Active Context section in materializer. Metrics: events this session, total sessions, decisions made/revisited, churn topics (3+ decisions on same topic), concern resolution ratio
- Performance benchmarks — `materialize()` <100ms/100 events, <500ms/1000, <2000ms/5000. `read_delta()` <50ms/1000@500. `compact()` <1000ms/5000. `repair()` <1000ms/5000
- Watermark isolation tests — 3 agents concurrent delta read, each gets independent watermark
- Integration tests for compact/repair/migrate — subprocess-level: compact then session_start, repair corrupted then materialize, migrate idempotent re-run
- 66 new tests (802 total: 98 SMM + 188 engine + 415 hooks + 101 integration)

### Changed
- `smm/schema.json` — `schema_version` now allows values `[1, 2]`
- `hooks/hooks.json` — Added PostCompact hook for `compact.py` (5s timeout)
- `smm/materialize.py` — Two new Active Context sections: Drift Signals (A8) and Velocity (A9). Now has `detect_drift_signals()` and `compute_velocity()` functions

### Design decisions
- **Compact retention: 3 sessions + permanent types** — configurable via `keep_sessions`. Unresolved questions/concerns always retained regardless of age
- **Repair strategy: skip, don't fix** — malformed lines dropped, not corrected. Dedup + sort. Dry-run for inspection
- **Schema v2 is minimal** — proves the migration framework works. Real schema evolution (e.g., `backlog_item`) happens in M9+
- **Drift thresholds hardcoded** — stale=5 sessions, ignored=3 concerns. Can add settings later
- **Velocity always in Active Context** — actionable signal, not archival. Informs current session behavior
- **No new event types** — all M8 analysis uses existing event types
- **compact.py as PostCompact hook** — runs after Claude Code's built-in compaction

## v0.8.0 — Milestone 7: Integration Testing & Packaging

### Added
- `.claude-plugin/marketplace.json` — marketplace publishing manifest with owner, plugin name, and description
- `TestPluginIntegrity` (9 tests) — validates marketplace.json, plugin.json, hooks.json script references, agent files, skill files, settings.json, behavioral guide, and no external dependencies
- `TestFullSessionLifecycle` (1 test) — chains session_start → pre_tool_use(Write) → post_tool_use → session_end, verifying event accumulation, working_on propagation, and subagent nudges at each step
- `TestPlanReviewFlow` (2 tests) — Plan subagent blocks with plan-reviewer instruction, regular subagent nudges subagent-reviewer
- `TestThreeSessionAccumulation` (1 test) — 3-session retro data accumulation, verifying cross-session trend visibility in `.retro-input.json` previous_retros
- `TestCompactionReinjection` (1 test) — seed → pre_compact → truncate → session_start verifies SMM re-injection after compaction
- `TestLargeEventLog` (3 tests) — 1000 events through pre_tool_use, materialize, and retrospective without error
- `TestConcurrentAgentWrites` (1 test) — 5 workers run full subagent lifecycle concurrently, no event corruption, no duplicate IDs
- `TestWorktreeSharing` (1 test) — git worktree derives same SMM path as main repo, events visible from both locations
- `TestEmptyProject` (2 tests) — fresh git repo with no events, session_start nudges for goals, pre_tool_use produces navigator nudge
- 21 new tests (736 total: 228 SMM + 131 engine + 415 hooks + 92 integration)

### Design decisions
- **marketplace.json follows Claude Code marketplace format** — name, owner, plugins array with source and description
- **Edge cases tested via subprocess** — all tests run scripts as subprocesses matching production execution
- **Worktree test auto-skips** when git worktree add fails (CI environments without worktree support)
- **Concurrent test uses ThreadPoolExecutor** with 5 workers, verifies flock-based serialization holds under contention

## v0.7.0 — Milestone 6.5: Agent Hook to Plugin Subagent Migration

### Changed
- **Agent hooks replaced with plugin subagents** — Agent hooks (type: "agent" in hooks.json) can only use Read/Grep/Glob tools (confirmed empirically: Bash test failed). They cannot write events via `append.sh` or return advisory guidance. All 6 agent hook prompts have been converted to plugin subagents in `agents/` directory with full tool access (Bash, Read, Write, Edit, AskUserQuestion)
- **Command hooks now trigger subagents** via `additionalContext` injection (nudge) or exit 2 blocking (deterministic):
  - `pre_tool_use.py` — nudges xp-navigator for Write/Edit/MultiEdit
  - `post_tool_use.py` — nudges xp-quality-reviewer (background), returns additionalContext
  - `retrospective.py` — nudges xp-retrospective when retro data available
  - `session_start.py` — nudges xp-customer-proxy when goals missing or open questions
  - `subagent_stop.py` — blocks for Plan subagents (xp-plan-reviewer), nudges xp-subagent-reviewer for others
- **hooks.json** — all type: "agent" entries removed. Only type: "command" and one type: "prompt" (tdd_check.md) remain
- `plan_review.py` command hook removed (redundant with plan reviewer subagent)

### Added
- `agents/xp-navigator.md` — pair programming guidance (haiku, preloads smm-protocol + pair-programming skills)
- `agents/xp-quality-reviewer.md` — courage + simplicity code review (haiku, background: true)
- `agents/xp-retrospective.md` — Keep/Fix/Try analysis (inherit, preloads smm-protocol + xp-values skills)
- `agents/xp-customer-proxy.md` — goal collection + question triage (inherit, foreground for AskUserQuestion)
- `agents/xp-plan-reviewer.md` — plan size/TDD/decision review (inherit, preloads smm-protocol + xp-values)
- `agents/xp-subagent-reviewer.md` — holistic output review (haiku, background: true)

### Removed
- `prompts/navigator.md`, `prompts/quality_reviewer.md`, `prompts/retrospective_analyst.md`, `prompts/customer_proxy.md`, `prompts/plan_reviewer.md`, `prompts/subagent_reviewer.md` — replaced by plugin subagents
- `scripts/plan_review.py` — deterministic checks redundant with plan reviewer subagent

### Design decisions
- **Agent hooks are read-only gates** — confirmed empirically. Only use for ok/not-ok gating (tdd_check.md)
- **Plugin subagents have full tool access** — Bash, Write, Edit, AskUserQuestion all work
- **Nudge for frequent triggers, block for critical ones** — navigator nudges every write, plan reviewer blocks once per plan
- **background: true for async reviewers** — quality reviewer and subagent reviewer always run in background
- **skills preloaded into subagents** — subagents don't inherit parent skills, must list explicitly

## v0.6.0 — Milestone 6: CLAUDE.md & Skills

### Added
- `BEHAVIORAL_GUIDE.md` at plugin root — XP behavioral rules for the main agent, covering the Honesty Principle (7 rules), XP values as concrete behaviors, skills reference library with invocation guidance, session lifecycle protocol, code quality rules, and courage commitments. Loaded at runtime by `session_start.py` via `_load_behavioral_guide()` with `lru_cache` and graceful degradation
- `skills/smm-protocol/SKILL.md` — Event recording reference. All 16 event types with when-to-use, required fields, priority guide, `working_on`/`references` usage, common recording patterns, good vs. bad event examples
- `skills/xp-values/SKILL.md` — XP values as behavioral guide. Communication, Simplicity, Feedback, Courage, Respect as concrete behaviors with practical examples. Value priority when they conflict. Values in practice (design decision and code review examples)
- `skills/pair-programming/SKILL.md` — Pair programming protocol. Driver/navigator dynamic, responding to guidance, quality reviewer severity levels, conflict resolution, debt in pair programming, session flow walkthrough
- 14 new tests (730 total: 228 SMM + 131 engine + 422 hooks + 79 integration)

### Changed
- `scripts/session_start.py` — Behavioral guide injected between enforcement indicator and GUPP in `additionalContext`. Updated `SKILLS_TEXT` descriptions to match actual skill frontmatter and emphasize "invoke these regularly"
- Injection order: SMM → enforcement → behavioral guide → GUPP → skills

### Design decisions
- **Inject via `additionalContext`, not plugin CLAUDE.md** — CLAUDE.md is not an official plugin component per the plugin reference docs. Only `additionalContext` from hooks is reliable for installed plugins
- **BEHAVIORAL_GUIDE.md as data file** — keeps content editable without touching Python. Loaded at runtime by `session_start.py`
- **Skills prominently referenced in guide** — skills are voluntary (not enforced by hooks), so the guide drives regular usage with explicit "invoke when" instructions
- **Complementary, not duplicative** — guide covers main agent behavior gaps; hook prompts cover their specific agents

## v0.5.5 — Milestone 5.5: Security Review Gate

### Added
- Push gate in `pre_tool_use.py` — detects `git push` in Bash commands, blocks until `.security-reviewed-{HEAD-hash}` tracker exists. Writes `security_review_requested` event on block. Strict mode blocks (exit 2), advisory mode warns
- Path 1 detection in `user_prompt_log.py` — scans user prompt for `/security-review`, `security review`, `security audit` patterns. On match, writes HEAD-keyed tracker file
- Path 2 detection in `subagent_stop.py` — scores `last_assistant_message` against 6 security review output signals (security review heading, severity markers, vulnerability mentions). Threshold of 2+ prevents false positives. On match, writes tracker
- Security helpers in `_common.py` — `get_head_hash()`, `security_tracker_path()`, `security_tracker_exists()`, `write_security_tracker()`, `_cleanup_old_security_trackers()`. Hash validation (`^[0-9a-f]{7,40}$`) prevents path traversal
- `security_review_requested` event type in `_append_impl.py` and `schema.json`
- Security lens in `retrospective_analyst.md` — analyzes `security_review_requested` events through Courage value, surfaces gaps as Fix items
- 42 new tests (711 total: 228 SMM + 406 hooks + 77 integration)

### Design decisions
- **Three detection paths** — security reviews detected via user prompt (Path 1), subagent output (Path 2), or push gate request (Path 3). No reliance on agent cooperation
- **Gate on invocation, not outcome** — checks if a review was run, not what it found
- **Commit hash keying** — new commits invalidate tracker, same HEAD passes without re-review
- **No new hook registrations** — all logic fits into existing PreToolUse, UserPromptSubmit, SubagentStop hooks

## v0.5.4 — Milestone 5.4: Auto-Simplify at Loop End

### Added
- `scripts/simplify_gate.py` — Stop command hook. Detects file changes in the current loop (events since last `customer_input` with non-empty `working_on`). Blocks stop (exit 2) with instruction to run `/simplify`. Tracker file (`.simplify-{agent_id}.json`) prevents re-triggering after simplify runs. New loop (new `customer_input`) resets tracker
- `scripts/bash_failure.py` — PostToolUseFailure command hook (Bash). Captures failed test runs that `bash_post_tool.py` never sees (PostToolUse only fires on success). Writes status + concern events for failed test commands
- `hooks/hooks.json` — Added `simplify_gate.py` command hook to Stop section, added `PostToolUseFailure` section with `bash_failure.py` for Bash matcher
- SessionStart matcher updated from `startup|resume|compact` to `startup|resume|compact|clear` — SMM now re-injected when user runs `/clear`
- 31 new tests (653 total)

### Fixed
- `prompts/tdd_check.md` — Changed output format from `{"decision": "block"/"allow"}` to `{"ok": true/false, "reason": "..."}`. Prompt hooks must use the `ok`/`reason` format per the Claude Code hooks API

### Design decisions
- **No prompt hook for simplify** — hooks within the same Stop entry run in parallel, so command hook's `additionalContext` is not visible to a prompt hook. Command hook blocks directly via exit 2
- **Tracker keyed on loop_id** — last `customer_input` event ID. New loop = new ID = fresh trigger. No explicit clearing needed
- **`stop_hook_active` guard** — prevents infinite loops when agent retries after being blocked

## v0.5.3 — Milestone 5.3: Debt & Goal Integration

### Added
- `load_enforcement_mode()` in `_common.py` — reads `enforcement` from `settings.json`, defaults to `"strict"`. Supports `"strict"` and `"advisory"` modes
- `find_debt_for_file()` in `_common.py` — filters debt events by target file with path normalization
- `extract_active_context()` in `materialize.py` — splits materialized view at REFERENCE boundary, returns Active Context section only
- Active Context injection for TIER_BLOCKING (non-commit Bash) in `pre_tool_use.py` — replaces delta with materialized Active Context view
- Debt injection for write tools in `pre_tool_use.py` — looks up debt events for the target file and injects them into `additionalContext`
- Advisory enforcement mode — `pre_tool_use.py` converts `BlockedError` to warning, appends `[enforcement: advisory]` indicator
- `session_start.py` — injects `[enforcement: advisory]` indicator when in advisory mode so agent/prompt hooks see it
- `settings.json` — added `"enforcement": "strict"` default
- 26 new tests (609 total)

### Changed
- `pre_tool_use.py` — TIER_BLOCKING now uses `materialize()` + `extract_active_context()` instead of `read_delta()` for non-commit Bash
- `prompts/customer_proxy.md` — added goal collection (first-run) and intent reconciliation behaviors before question triage
- `prompts/navigator.md` — added Debt Awareness section: nudges driver to address debt when modifying files with known debt
- `prompts/quality_reviewer.md` — can now write `debt` events for acknowledged tradeoffs; checks if file debt was addressed
- `prompts/retrospective_analyst.md` — debt escalation in Fix items (aging markers), plugin health analysis from session stats, can write `debt` events for deferred fixes

## v0.5.2 — Milestone 5.2: SMM Enhancements — Schema & Materializer

### Added
- 3 new event types: `goal` (🎯 prefix), `debt` (requires `files`, with session-based aging), `customer_intent` (requires `intent_status`: open/delivered/superseded)
- Two-tier materialized view: Active Context (goals, conflicts, blocking questions, unacknowledged concerns, customer intent, agent status, navigator guidance) and Reference (decisions, conventions, resolved questions, discoveries, assumptions, technical debt, resolved concerns)
- Debt aging in materializer — counts `session_end` events after debt timestamp using `bisect`. 0–3 normal, 4–6 ⚠️, 7+ 🔴
- Session stats in `.retro-input.json` — pair_guidance_count, status_count, concerns raised/resolved, questions open/answered, decisions total/draft
- `compute_resolutions()` in `_append_impl.py` — shared resolution tracking used by materializer, retrospective, session_end, and detect_conflicts
- `read_with_lock()`, `write_watermark()` centralized in `_append_impl.py`
- `PRIORITY_BLOCKING`, `PRIORITY_ASSUMED`, `PRIORITY_INFO` constants in `_append_impl.py` (replace `PRIORITY_RED`)
- 34 new tests (585 total: 228 SMM + 309 hooks + 50 integration)

### Changed
- `materialize.py` — complete render rewrite to two-tier structure. Navigator guidance scoped to current session. Customer Input section removed
- `read_delta.py` — `format_delta()` handles goal, debt, customer_intent types
- `_append_impl.py` centralized as foundational module — `materialize.py`, `read_delta.py`, `_common.py` import shared functions instead of duplicating (6 functions deduplicated)
- `prompts/customer_proxy.md` — updated section references for two-tier SMM

### Security
- Watermark read uses `O_NOFOLLOW` to reject symlinks
- Watermark write rejects symlink targets before rename
- `normalize_path` resolves symlinks via `realpath` for overlap detection
- `references` and `files` array items validated as strings at write time

## v0.5.0 — Milestone 5: Agent Hooks — Session Lifecycle

### Added
- `scripts/retrospective.py` — SessionStart command hook for retrospective data preparation. Checks for unanalyzed events (≥5), gathers retro history, writes `.retro-input.json` atomically
- `prompts/retrospective_analyst.md` — SessionStart agent hook. Keep/Fix/Try analysis with XP values as lenses. Cross-session trend detection from previous retrospectives
- `prompts/customer_proxy.md` — SessionStart agent hook. Triages open questions via AskUserQuestion, records answers as events
- `prompts/subagent_reviewer.md` — SubagentStop async agent hook. Holistic review of subagent output for conventions, complexity, decision alignment
- `prompts/tdd_check.md` — Stop prompt hook. Single-turn evaluation blocking stop if tests failing, with `stop_hook_active` guard
- `hooks/hooks.json` — Added SessionStart agents (retrospective_analyst, customer_proxy), SubagentStop reviewer (async), Stop section (tdd_check prompt)
- 49 new tests (551 total: 190 SMM + 361 hooks)

### Changed
- `scripts/session_start.py` — Removed retro check logic (moved to `retrospective.py`). Now handles only SMM init + materialization + GUPP + skills

## v0.4.0 — Milestone 4: Agent Hooks — Quality & Navigation

### Added
- `prompts/navigator.md` — PreToolUse agent hook (Write/Edit/MultiEdit). Strategic guidance before code changes. Self-filters trivial changes. Can block on decision contradictions. Writes `pair_guidance` events
- `prompts/quality_reviewer.md` — PostToolUse async agent hook (Write/Edit/MultiEdit). Courage + simplicity review. Flags empty catch blocks, missing error handling, unnecessary complexity, premature abstraction, growing files. Writes `concern` events
- `scripts/plan_review.py` — SubagentStop command hook (Plan matcher). Deterministic plan analysis: step counting, TDD strategy detection, size flags, decision/convention lookup
- `prompts/plan_reviewer.md` — SubagentStop agent hook (Plan matcher). Checks milestone boundaries, TDD ordering, plan size, assumptions, decision conflicts. Extracts `decision` and `assumption` events
- `find_related_decisions()` extracted to `_common.py` for reuse across hooks
- 39 new tests (502 total: 190 SMM + 312 hooks)

## v0.3.4 — Milestone 3.4: Core Hooks — Customer & Subagent Tracking

### Added
- `scripts/user_prompt_log.py` — UserPromptSubmit hook. Logs every user prompt as `customer_input` event with `agent_id="customer"`. Truncates to 10,000 chars
- `scripts/subagent_stop.py` — SubagentStop hook. Records minimal completion status, runs conflict detection (patterns 2-5)
- Desktop notifications for 🔴 blocking questions — inline in `smm/_append_impl.py` at the `append_event()` choke point. macOS `osascript` / Linux `notify-send`
- `detect_conflicts()` and `make_concern()` extracted to `_common.py` with optional `file_path`/`cwd`
- Integration tests for both new scripts (subprocess-based)
- 50 new tests (439 total: 190 SMM + 249 hooks)

## v0.3.3 — Milestone 3.3: Core Hooks — PostToolUse

### Added
- `scripts/post_tool_use.py` — PostToolUse hook (Write/Edit/MultiEdit). Auto-generates `status` events with `working_on` from file paths. Structural conflict detection (all 5 patterns). Semantic context enrichment via references
- `scripts/lint_check.py` — PostToolUse hook (Write/Edit/MultiEdit). Detects project linter config (ruff, eslint, prettier, flake8). Runs linter, appends concern for errors. Warns once if no config
- `scripts/bash_post_tool.py` — PostToolUse hook (Bash). Git commit size check, auto-drafts decisions. Test result parsing (pytest/jest/go test) with status + concern events
- `scripts/_common.py` — Shared helpers extracted: `normalize_path`, `extract_file_path`, conflict detection, event factories
- `settings.json` — `commit_size_threshold: 10`
- 72 new tests (389 total: 190 SMM + 199 hooks)

## v0.3.2 — Milestone 3.2: Core Hooks — PreToolUse

### Added
- `scripts/pre_tool_use.py` — PreToolUse hook (matcher: `*`). Tiered delta injection via `additionalContext`: full delta for Write/Edit/MultiEdit/Bash(git commit), 🔴+pair_guidance for other Bash, 🔴-only for Read/Grep/Glob. `working_on` overlap blocking (exit 2). TDD order tracking

### Security
- Agent ID allowlist regex validation (replaced denylist)
- JSON arg size limits and init script path validation

## v0.3.1 — Milestone 3.1: Core Hooks — Session Lifecycle

### Added
- `.claude-plugin/plugin.json` — Plugin manifest
- `hooks/hooks.json` — Hook registrations with matchers, timeouts, `${CLAUDE_PLUGIN_ROOT}` paths
- `scripts/session_start.py` — SessionStart hook. Inits SMM via `init.sh`, materializes view, injects SMM + GUPP + skills via `additionalContext`
- `scripts/session_end.py` — SessionEnd hook. Computes duration, event count, unresolved items, active working_on, final status flag. Appends `session_end` event
- `scripts/pre_compact.py` — PreCompact hook. Timestamped backup of events.jsonl and SHARED_MENTAL_MODEL.md
- `scripts/subagent_start.py` — SubagentStart hook. Full SMM injection + watermark creation
- `scripts/_common.py` — Initial shared helpers: `resolve_smm_dir`, `read_hook_input`, `hook_output`, `is_xp_agent`

### Security
- SMM directory ownership and permissions validation
- Symlink-safe file opens with `O_NOFOLLOW`
- File permissions hardening: chmod 600 after touch and rename
- Init script path validation before execution

## v0.2.0 — Milestone 2: SMM Engine

### Added
- `smm/materialize.py` — Materializes events.jsonl into SHARED_MENTAL_MODEL.md with 5 structural conflict detection patterns, section-by-section rendering, atomic write via tempfile + rename
- `smm/read_delta.py` — Per-agent watermark-based delta reader with tiered filtering (full, blocking, red-only). Watermark only advances on full reads
- `smm/test_engine.py` — 96 tests covering parsing, index building, all 5 conflict patterns, all 11 rendered sections, watermark management, tier filtering, delta formatting

### Security
- Lock timeout graceful degradation (append without lock after 2s)
- Agent ID path traversal prevention

## v0.1.0 — Milestone 1: SMM Foundation

### Added
- `smm/schema.json` — JSON Schema (draft-07) defining all 12 event types with type-specific validation
- `smm/init.sh` — SMM directory initialization with Python 3.10+ validation and git-based project-id derivation
- `smm/append.sh` — Thin bash wrapper delegating to Python implementation
- `smm/_append_impl.py` — Event construction, validation, and atomic flock-based appending
- `smm/test_smm.py` — Foundation tests for init, append, schema validation, concurrency
- `LICENSE` — MIT license
- `CHANGELOG.md`

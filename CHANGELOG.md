# Changelog

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

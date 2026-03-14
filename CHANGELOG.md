# Changelog

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

# Changelog

## v0.9.67 — Kickoff Reorder + Lightweight Question Detection

### Changed
- **Question triage now runs before goal collection** — answers may inform goals. Kickoff order: retro → questions → goals → housekeeping.
- **Question detection uses grep instead of full JSON parse** — `check_session_needs.sh` greps `events.jsonl` for question events instead of loading and iterating all events. Question triage handles resolution checking itself.

### Fixed
- **Kickoff detects questions from raw events** — questions written directly to `events.jsonl` (like the linter question) were missed because housekeeping hadn't curated them into the SMM Risks pillar yet.

### Stats
- 851 tests (all passing)

## v0.9.66 — Question Detection from Raw Events

### Fixed
- **Kickoff now detects unresolved questions in raw events, not just the curated SMM** — questions written to `events.jsonl` (like the linter question) weren't detected by `check_session_needs.sh` because housekeeping hadn't curated them into the Risks pillar yet. Now checks both the SMM file and raw events for unresolved blocking questions.

### Stats
- 851 tests (all passing)

## v0.9.65 — Xcode and Swift Test Detection

### Added
- **Xcode and Swift test result parsing** — `xcodebuild test` and `swift test` commands now detected and parsed. Matches "Executed N tests, with M failures" output format. Test pass/fail events are recorded to the SMM, enabling TDD stop gate enforcement for iOS/macOS projects.

### Stats
- 851 tests (all passing, +5 new)

## v0.9.64 — Fix load_context.sh SMM Path

### Fixed
- **`load_context.sh` accepts SMM_DIR as argument** — when called by the agent via Bash during housekeeping, the script couldn't resolve `CLAUDE_PLUGIN_DATA` and fell back to the wrong path. Now accepts the preloaded SMM_DIR as `$1`, with init.sh as fallback.
- **Housekeeping SKILL.md updated** — step 8 instructions tell the agent to pass the SMM_DIR from the preload output.

### Stats
- 846 tests (all passing)

## v0.9.63 — Fix Subagent SMM Path Resolution

### Fixed
- **Subagents no longer construct their own SMM paths** — retrospective and plan reviewer agents were told to run `init.sh` themselves, which failed to resolve `CLAUDE_PLUGIN_DATA` and fell back to wrong paths (e.g., `{project}/.smm/`). Preloads now emit `SMM_DIR=<path>` and agent prompts say "use that exact path, do not construct your own."
- **All preloads emit SMM_DIR** — retrospective, plan-reviewer, and quality-review preloads now output the resolved path for agents/skills to use.

### Stats
- 846 tests (all passing)

## v0.9.62 — Lint Check: Blocking Question

### Changed
- **Missing linter config now emits a blocking question** — "No linter configured. Want me to set one up?" as a blocking question instead of a low-severity concern. Coding standards are a core XP practice — the user should consciously decide, not passively ignore.

### Stats
- 846 tests (all passing)

## v0.9.60 — Plugin Data Path Fix for Skill Preloads

### Fixed
- **Skill `!` preloads now use correct SMM path** — `CLAUDE_PLUGIN_DATA` is inline-substituted in skill content but not exported as an env var to `!` preload commands. All 8 skill preloads now pass `CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}"` explicitly so `init.sh` resolves the correct plugin data path instead of falling back to `~/.claude/xp-agents/`.

### Stats
- 846 tests (all passing)

## v0.9.59 — Kickoff Must Complete Before Work Begins

### Fixed
- **Agent no longer starts working on goals before housekeeping completes** — added explicit instruction: "Do NOT start working on the user's goal until ALL steps are done." The agent was collecting goals, then immediately executing on them before running housekeeping.

### Stats
- 846 tests (all passing)

## v0.9.58 — Shell Compatibility Fix

### Fixed
- **Quality review preload works in zsh** — replaced `mapfile` (bash-only) with portable shell in `xp-quality-review/scripts/preload.sh`. The `!` preload mechanism may not honor shebangs, running through the user's default shell instead.

### Stats
- 846 tests (all passing)

## v0.9.57 — Kickoff Sequencing Fix

### Fixed
- **Housekeeping now reliably runs after goal collection** — strengthened `/xp-kickoff` skill instructions. The agent was stopping after goal collection without proceeding to housekeeping (step 4). Instructions now use imperative language: "You MUST complete ALL steps", "Housekeeping MUST always run", "Kickoff is not complete until housekeeping finishes."

### Stats
- 846 tests (all passing)

## v0.9.56 — SMM Path Fix

### Fixed
- **SMM directory now uses `CLAUDE_PLUGIN_DATA`** — `resolve_smm_dir()` in Python was hardcoded to `~/.claude/xp-agents/`, ignoring the `CLAUDE_PLUGIN_DATA` environment variable that the plugin platform provides. `init.sh` already used it correctly. Now both are in sync, placing the SMM at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` when installed via marketplace.

### Stats
- 846 tests (all passing)

## v0.9.55 — Kickoff Gate Fix

### Fixed
- **Kickoff gate no longer blocks AskUserQuestion during kickoff sub-skills** — the `.needs-kickoff` marker is now cleared when `/xp-kickoff` starts, not when housekeeping finishes. Previously, goal collection's `AskUserQuestion` triggered `UserPromptSubmit` which hit the gate mid-kickoff.

### Added
- **Agent Teams design doc** (`docs/AGENT_TEAMS_DESIGN.md`) — maps XP sprint practices to Claude Code Agent Teams. Documents sprint lifecycle, role separation (lead as coach, teammates as developers), hook compatibility analysis, and required changes for teammate awareness.

### Stats
- 848 tests (all passing)

## v0.9.54 — Question Pipeline, Effort Tuning, Legacy Cleanup

### Added
- **Plan reviewer emits `question` events** — new section 6 in the agent prompt distinguishes assumptions (can proceed with reasonable default) from questions (need user input, significant rework risk). Questions surface first in the subagent's output so the main agent sees them immediately.
- **`/xp-question-triage` wired into kickoff** — step 3 (between goals and housekeeping), conditional on open questions/assumptions in the Risks pillar.
- **`smm_has_section()` and `smm_section()` utilities** — shared functions in `_preload_base.sh` for extracting markdown sections from the SMM. Replaced 12 duplicate `grep -A N | sed` patterns across 4 preload scripts.
- **Effort frontmatter on all skills** — `effort: high` for analytical skills (retrospective, housekeeping, quality-review, plan-reviewer, security-triage), `effort: low` for mechanical skills (goal-collection, question-triage, smm-protocol). Kickoff left at default.

### Removed
- **All navigator references** — stale docs, negative tests, and test fixtures. Navigator was removed as a functional component in v0.9.47 but references lingered.
- **Legacy SMM format fallbacks** — `Project Goals`, `Blocking Questions`, `Customer Intent`, `Unacknowledged Concerns`, `Technical Debt` section patterns removed from all preload scripts. Four-pillar format (Intent, Constraints, Risks, Wisdom) is the only supported format.
- **4 dead navigator negative tests** — `TestPreToolWriteNoNavigatorNudge` class, integration navigator nudge test.

### Changed
- **`check_open_items.sh` uses four-pillar headings** — Intent, Constraints, Risks instead of legacy section names.
- **Question detection keywords tightened** — `question|assumption|blocking` instead of `question|unknown|assumed|blocking` to reduce false positives.
- **Docs updated** — ARCHITECTURE.md (kickoff flow, plan reviewer events, question triage step), PLUGIN_TOOLS.md (subagent examples), SMM_DESIGN.md (retro example), CLAUDE.md (removed navigator decision).

### Stats
- 844 tests (all passing)

## v0.9.53 — Replace Push Gate with Commit-Time Security Triage

### Changed
- **Security gate moved from `git push` to `git commit`** — earlier feedback (XP Feedback value). Blocks commit without triage instead of blocking push without review.
- **New `/xp-security-triage` inline skill** — reads `git diff --cached`, classifies changes as trivial (auto-clear) or security-relevant (requires `/security-review`).
- **Simple marker replaces hash-based tracker** — `.security-triaged` marker written by triage skill or `/security-review`, consumed after each successful commit. No more commit-hash tracking or carry-forward logic.
- **`is_git_commit` deduplicated** — single definition in `security.py`, imported by both `pre_tool_bash.py` and `bash_post_tool.py`.

### Removed
- **`/security-clear` skill** — no more bypass. Triage skill replaces it with proper classification.
- **`security_review_requested` event type** — removed from schema, `_append_impl.py`, and `_common.py`. Push gate no longer writes events.
- **Security detection in `user_prompt_log.py` and `subagent_stop.py`** — pattern-matching heuristics for security review output removed. Triage is now explicit via skill invocation.
- **Hash-based tracker functions** — `get_head_hash`, `security_tracker_path`, `write_security_tracker`, `find_last_reviewed_hash`, `diff_has_code_changes` all removed from `security.py`.

### Stats
- 848 tests (all passing)

## v0.9.52 — Remove xp-values Skill, Absorb into Behavioral Guide

### Changed
- **Behavioral guide absorbs xp-values content** — added "answer open questions promptly" (Communication), "if you can remove something, remove it" (Simplicity), and value conflict priority: Courage > Simplicity > Feedback > Communication > Respect.

### Removed
- **`/xp-values` skill** — 80% redundant with the behavioral guide. Unique content (conflict priority, concise additions) absorbed into the guide. Saves ~125 lines of skill description budget.
- **`xp-values` preload** from plan reviewer and retrospective subagents — XP values now delivered via behavioral guide at SubagentStart.
- **`/xp-values` reference** from session start skills list.

### Stats
- 869 tests (all passing)

## v0.9.51 — Lint Feedback, Async Hooks, Plugin Data Storage

### Changed
- **Lint errors inject additionalContext** — `lint_check.py` now returns lint errors as `additionalContext` so the agent sees them immediately after writing the file, not deferred to the next prompt via nuggets. Synchronous (was async) since context injection must complete before the agent continues.
- **Removed lint debounce** — the 1-second mtime debounce skipped files the agent just wrote, which is every file. Now always lints immediately after write.
- **4 hooks now async** — `bash_post_tool.py`, `bash_failure.py`, `security_review_done.py`, and `session_end.py` run with `async: true` (fire-and-forget, no context injection).
- **SMM storage uses `CLAUDE_PLUGIN_DATA`** — respects plugin ecosystem conventions and sandbox customization.
- **Both user and project scope supported** for installation.

### Stats
- 869 tests (all passing)

## v0.9.50 — Async Hooks, CLAUDE_PLUGIN_DATA Storage

### Changed
- **5 hooks now async** — `lint_check.py`, `bash_post_tool.py`, `bash_failure.py`, `security_review_done.py`, and `session_end.py` run with `async: true`. These fire-and-forget hooks record data to the event log but don't inject context or block. Biggest win: agent no longer waits up to 5s for lint on every Write/Edit.
- **SMM storage uses `CLAUDE_PLUGIN_DATA`** — SMM now lives at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` instead of `~/.claude/xp-agents/`. Respects plugin ecosystem conventions and sandbox customization. Falls back for `--plugin-dir` dev mode.
- **Both user and project scope supported** — project scope installs share the plugin with the team via `.claude/settings.json`.

### Stats
- 869 tests (all passing)

## v0.9.49 — Use CLAUDE_PLUGIN_DATA for SMM Storage

### Changed
- **SMM storage uses `CLAUDE_PLUGIN_DATA`** — SMM now lives at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` instead of `~/.claude/xp-agents/{project-id}/smm/`. Falls back to the old path when `CLAUDE_PLUGIN_DATA` is not set (e.g., `--plugin-dir` development mode). Respects custom paths for sandbox and enterprise environments. Cleaned up automatically on `plugin uninstall`.
- **Both user and project scope supported** — project scope installs (`--scope project`) now work correctly for teams. SMM is shared across worktrees via the git-common-dir hash regardless of install scope.
- Install docs updated to show both scope options.

### Stats
- 869 tests (all passing)

## v0.9.48 — Kickoff Rename, Tiered Injection, Behavioral Guide Rewrite

### Changed
- **`/xp-session-review` → `/xp-kickoff`** — renamed skill, gate script (`kickoff_gate.py`), done script (`kickoff_done.py`), marker file (`.needs-kickoff`), all references.
- **Tiered SubagentStart injection** — Explore agents get Intent + Constraints only (~200 tokens). Plan, general-purpose, and background agents get full SMM + behavioral guide (~1000 tokens). xp-* agents skipped (use own preloads). Prevention over inspection.
- **BEHAVIORAL_GUIDE.md rewritten** — declarative, ~260 tokens. XP values underscored by Honesty. Five honesty rules for judgment calls. Each value is a focused paragraph. Added `append.sh` reference so agents know how to record events.

### Removed
- **xp-subagent-reviewer** agent and skill — dead since v0.9.29 (SubagentStop silently drops nudges). Replaced by upfront behavioral guide injection at SubagentStart.
- **Reviewer nudge from subagent_stop.py** — no longer returns anything for non-Plan subagents.

### Stats
- 869 tests (all passing)

## v0.9.47 — Tiered Subagent Context, Remove Dead Reviewer

### Changed
- **Tiered SubagentStart injection** — Explore agents get only Intent + Constraints pillars (~200 tokens). Plan, general-purpose, and background agents get full SMM + behavioral guide (~1000 tokens). xp-* agents skipped (use own preloads). Prevention over inspection — subagents get quality expectations upfront.

### Removed
- **xp-subagent-reviewer** agent and skill — dead since v0.9.29. SubagentStop silently drops `decision:"approve"` with `reason`, so the nudge never reached the agent. The tiered context injection replaces its purpose.
- **Reviewer nudge from subagent_stop.py** — `subagent_stop.py` no longer returns anything for non-Plan subagents.

### Stats
- 869 tests (all passing)

## v0.9.46 — Rename /xp-session-review to /xp-kickoff

### Changed
- **`/xp-session-review` → `/xp-kickoff`** — the skill orchestrates session start (retro → goals → housekeeping), not just review. All references updated: skill directory, gate script (`kickoff_gate.py`), done script (`kickoff_done.py`), marker file (`.needs-kickoff`), docs, tests.

### Stats
- 865 tests (all passing)

## v0.9.45 — Remove Advisory Mode, Doc Refresh

### Removed
- **Advisory enforcement mode** — `load_enforcement_mode()`, `ENFORCEMENT_STRICT`, `ENFORCEMENT_ADVISORY` constants, and all advisory/strict branching removed from `pre_tool_write.py`, `pre_tool_bash.py`, `session_review_gate.py`, `session_start.py`. The `enforcement` key removed from `settings.json`. If a gate is annoying, fix the gate — don't make it optional.
- **`_override_settings()` test helper** — no longer needed without enforcement mode.

### Docs
- **README.md rewritten** — session startup sequence, quality review as skill, PreToolUse split, simplify threshold, configuration section updated.
- **ARCHITECTURE.md updated** — hook map, injection model, plugin structure, session flows, enforcement section all updated for current implementation.
- **SMM_DESIGN.md updated** — injection model, mid-session context, watermarks, conflict detection sections corrected.

### Stats
- 865 tests (all passing)

## v0.9.44 — Token Optimization: File Splits, Hook Targeting, Review Trimming

### Changed
- **PreToolUse split from `*` to targeted matchers** — `pre_tool_write.py` (Write|Edit|MultiEdit) handles conflict detection, TDD order, and plan review gate. `pre_tool_bash.py` (Bash) handles push security gate and file-modification heuristic. Read/Grep/Glob/Agent/Skill no longer trigger PreToolUse at all.
- **Plan review gate uses marker file** — `.plan-awaiting-review` file instead of backward event log scan. Cleared in plan reviewer preload. O(1) check, zero event reads.
- **Simplify gate threshold** — skips `/simplify` when fewer than 3 distinct code files changed. Consolidated duplicate `is_code_file` from simplify_gate into `security.py`.
- **Quality review trimmed** — dropped redundant Clean Code checklist (already covered by /simplify's 3 agents). Focused on courage accountability, drift management, and debt awareness.
- **Quality review preload** — no longer re-injects SMM (inline skill, already in context). Now injects only diff + debt for changed files.
- **session_review_done hook** — no longer re-injects SMM (housekeeping already has agent Read it). Now injects only behavioral guide.
- **Test files split to match code** — `test_pre_tool.py` split into `test_pre_tool_write.py` and `test_pre_tool_bash.py`.

### Added
- **`pre_tool_write.py`** — PreToolUse for Write|Edit|MultiEdit: conflict detection via `.coordination.json`, TDD order tracking, marker-file plan review gate. Zero event log reads.
- **`pre_tool_bash.py`** — PreToolUse for Bash: push security gate, file-modification heuristic (detects `>`, `tee`, `sed -i`, `mv`, `cp` targets and checks against coordination). Advisory only for heuristic, blocks for push gate.
- **`debt_for_files.py`** — quality review preload script that surfaces existing debt events for changed files.
- **Simplify early-exit** — `count_distinct_code_files()` stops scanning at threshold.

### Removed
- **`pre_tool_use.py`** — replaced by `pre_tool_write.py` and `pre_tool_bash.py`.
- **Debt injection from PreToolUse** — moved to quality reviewer preload.
- **Dead `hook_output` code** in `post_tool_use.py`.
- **Redundant SMM injection** from quality review preload and session_review_done hook.

### Stats
- 881 tests (all passing)

## v0.9.43 — Assumption Resolution, Session UX, Quality Courage

### Fixed
- **Assumption accumulation bug** — `compute_resolutions()` lacked a `case "assumption"` branch, so assumptions from plan reviews were never resolvable via `metadata.resolves`. Compaction unconditionally retained them, and `prepare_curation_data()` only filtered via contradictions. This caused 39 stale assumptions to accumulate across 4 sessions. Added resolution mechanism to all three files.

### Added
- **`is_task_notification()` helper** in `_common.py` — shared check for background agent task-notifications, used by both `session_review_gate.py` and `user_prompt_log.py`.
- **Session review gate nudge on `/clear`** — marker content distinguishes "startup" (block) from "clear" (nudge). Mid-session resets no longer hard-block work in progress.
- **Task-notification skip in session review gate** — background agent completions no longer trigger the session review block.
- 8 new tests (887 total)

### Changed
- **Goal collection always runs** — `/xp-goal-collection` now shows existing goals and asks "Any goals for this session?" at every session start, not just when zero goals exist. Supports short-term session goals alongside long-term north star.
- **Quality review emphasizes courage** — Step 1 now defaults to applying simplify recommendations; "low severity" and "it's fine as-is" are explicitly invalid skip reasons.
- **`check_session_needs.sh`** — outputs `GOALS_REVIEW` (always) instead of binary `GOALS_NEEDED`/`Goals: PRESENT`. Added legacy `## Project Goals` fallback for goal display.

### Stats
- 887 tests (all passing)

## v0.9.42 — Tech Debt Cleanup (5 fixes + simplify)

### Fixed
- **Compaction race condition** — `compact_after_curation()` now uses `read_with_lock()` instead of unlocked `read_text()`, preventing data loss when events are appended during compaction.
- **Stale team watermarks** — All `.curation-watermark-*` files are now adjusted by `archived_count` after compaction, not just the primary one. Uses `write_json_atomic()` for crash safety.
- **Conflict nugget missing** — `pre_tool_use.py` now appends a high-severity concern event when a file conflict is detected, for team awareness alongside blocking.
- **Lint false positives** — `run_linter()` now skips files modified less than 1 second ago (mtime debounce), preventing false-positive concern events during rapid edits.
- **repair.py double-parse** — Replaced `parse_jsonl()` + second `json.loads()` loop with single-pass local loop that tracks malformed vs invalid directly. Removed unused `parse_jsonl` import.

### Changed
- **Conflict concern content** — Uses `check_working_on_overlap()` return value directly instead of wrapping with redundant "File conflict:" prefix (found by /simplify).

### Tech Debt Resolved
- Compaction race condition [5887e4db] — closed
- Stale team watermarks [0d8c4376] — closed
- Conflict nugget missing [dbdf1ea0] — closed
- Lint debounce [f7be28f8] — closed
- Repair double-parse [1bb8be5c] — closed

### Remaining
- Quality review stop gate fires too early with background agents [e72d72cd] — needs investigation

### Stats
- 879 tests (all passing)

## v0.9.41 — Event Log Compaction (M6), Prompt Nugget Rewrite, Doc Alignment

### Added
- **M6: Event log compaction** — New `compact_after_curation()` uses curation watermark as the compaction boundary instead of session count. Retains post-watermark events, last 3 session_ends, and SMM-referenced events. Resolved permanent events before the watermark are now archivable (the curated SMM is the durable record). Team safety via min(watermark) across agents.
- **`compact_log.py`** — Housekeeping script (step 9 in SKILL.md) that runs compaction after curation.
- **`_collect_smm_referenced_ids()`** — Collects IDs of active SMM items (unresolved goals, decisions, concerns, etc.) for retention during compaction.
- **`_read_all_curation_watermarks()`** — Supports team mode by reading all `.curation-watermark-*` files and using the oldest as the safe boundary.
- 12 new compaction tests in `TestCompactAfterCuration` (969 total)

### Changed
- **Prompt nugget rewrite** — `prompt_nugget.py` now uses `read_delta` with a dedicated watermark to show only new signal events (concerns, decisions, goals, debt, questions) since last prompt, instead of parsing `SHARED_MENTAL_MODEL.md` directly.
- **Quality review gate** — No longer blocks while simplify subagents are pending. Lets stops through until all subagents complete, then blocks for quality review on the next stop.
- **`compact()` delegates** — Legacy `compact()` function now delegates to `compact_after_curation()`. `PERMANENT_TYPES` constant and `--keep-sessions` CLI arg removed (dead code after policy change).
- **Watermark management** — Compaction resets `.watermark-prompt-nugget` to post-compaction count, updates `.curation-watermark`, and removes orphaned `.watermark-*` files.

### Docs
- **SMM_DESIGN.md** — Updated nugget model: "stop nuggets" replaced with "prompt nuggets (UserPromptSubmit)" throughout. Injection model table, mid-session nuggets section, and layer 3 description all updated.
- **SMM_REFACTOR_MILESTONES.md** — M5 title and body updated for prompt nuggets. Migration safety table updated.
- **README.md** — Token cost model updated: PreToolUse delta rows replaced with single prompt nugget row.
- **xp-subagent-reviewer.md** — Updated delivery mechanism reference from PreToolUse delta to prompt nugget.

### Tech Debt Recorded
- TOCTOU race in `compact_after_curation()` — unlocked read before locked replace
- Stale team watermarks not updated after compaction (solo mode only for now)
- JSONL parsing duplicated in 5 places (M7 cleanup scope)
- Conflict nugget missing from PreToolUse (design spec calls for informational nugget alongside blocking)

## v0.9.40 — Fix Retrospective Preload Overflow, Move Prompt Nugget to UserPromptSubmit

### Fixed
- **Retrospective preload overflow** — `preload.sh` was dumping the entire `.retro-input.json` (100KB+) via `cat`, exceeding Claude Code's output limits. Now strips `events_since_last_retro` array before output, keeping only the structured `digest` (~5KB). The agent prompt already says "Use `digest` for analysis."

### Changed
- **Stop nugget → prompt nugget** — Renamed `stop_nugget.py` to `prompt_nugget.py` and moved from Stop hook to UserPromptSubmit hook. Stop hooks don't support `additionalContext` (caused JSON validation errors); UserPromptSubmit does. Context injection on prompt submission is a better fit — reminds Claude about open intents/risks when starting new work.
- **Prompt nugget reads SMM file directly** — Instead of calling `prepare_curation_data()` (full event log parse, O(n)), now reads `SHARED_MENTAL_MODEL.md` directly (single file read, O(1)). Critical for UserPromptSubmit which fires on every prompt (~5-20x/session vs ~1x for Stop).
- **Stop hooks** — Now 3 hooks (was 4): simplify gate, quality review gate, TDD gate.
- 956 tests (was 957 — removed 2 event-based tests, added 1 SMM-based test + 2 integration tests)

## v0.9.39 — Four-Pillar SMM, Coordination File, Stop Nuggets (M3-M5)

### Added
- **M3: Skill Alignment** — All skills, subagent definitions, and behavioral guide updated to reference four-pillar SMM format (Intent, Constraints, Risks, Wisdom). Preload scripts use anchored dual-format grep (`^## X$`) to work before and after first curation.
- **M4: Coordination file** — `.coordination.json` for O(1) real-time agent conflict detection, replacing O(all_events) event log scanning. PostToolUse updates on every write, PreToolUse reads for overlap checks, SessionEnd clears entries. Stale entries (>30min) filtered automatically. Flock-protected.
- **M5: Stop nugget** — `stop_nugget.py` injects lightweight session checkpoint (~50-80 tokens) at Stop time via `additionalContext`. Uses `prepare_curation_data()` to extract current open intents and unresolved risks.
- **M5: SubagentStart reads from disk** — Prefers curated four-pillar `SHARED_MENTAL_MODEL.md` (written by housekeeping), falls back to `materialize()` for first session.
- `update_coordination()`, `read_coordination()`, `clear_coordination_agent()` helpers in `_common.py`
- 20 new coordination + stop nugget tests (955 total)

### Removed
- **PreToolUse delta injection** — No longer reads event log or injects `<smm-context>`/`<smm-delta>` on every tool call. Context delivered via session start (housekeeping), subagent start (disk read), and stop nuggets.
- **Tier classification system** — `classify_tier()`, `TIER_FULL`, `TIER_BLOCKING`, `TIER_RED_ONLY` removed from `pre_tool_use.py`. No longer needed without delta injection.
- **`materialize` and `read_delta` imports** from `pre_tool_use.py`

### Changed
- **Conflict detection** — `check_working_on_overlap()` now reads `.coordination.json` instead of scanning events. Signature changed from `(events, agent_id, ...)` to `(smm_dir, agent_id, ...)`.
- **Debt injection** — Still in PreToolUse for write tools, but no longer tied to tier system.
- **Stop hooks** — Now 4 hooks (was 3): simplify gate, quality review gate, TDD gate, stop nugget.
- **Simplify gate message** — Removed specific "30 seconds" wait time, encourages patience instead.

### Fixed
- **`save_retrospective.py` missing `sys.path` setup** — Script failed with `ModuleNotFoundError` for `_append_impl`. Added standard `sys.path.insert` calls matching all sibling scripts.
- **`check_questions.sh` substring collision** — `grep "## Intent"` matched `## Customer Intent` as substring. Fixed with anchored patterns (`^## Intent$`).
- **TOCTOU in `clear_coordination_agent`** — Removed premature `exists()` check before locking.

## v0.9.38 — Retrospective Helper & Navigator Cleanup

### Added
- **`save_retrospective.py` helper script** — encapsulates retrospective write-side plumbing (event append, file write, materialize) into a single script that accepts K/F/T JSON on stdin. Reduces retrospective agent tool calls from ~17 to ~3.
- 5 new tests for `save_retrospective.py` (907 total)

### Removed
- **`pair_guidance` event type** — removed from schema, validation, formatting, and stats. The navigator was deleted in v0.9.37 (SubagentStop limitation); this completes the cleanup.
- **`pair-programming` skill** — dead code since navigator removal. Quality review functionality already covered by `/xp-quality-review`.
- **Navigator health check in retrospective** — stopped false "CRITICAL: 0 navigator guidance" alarm that fired in 4 consecutive retrospectives.

### Changed
- **Retrospective agent prompt** — Actions section simplified from 3 manual steps (append.sh + Write + materialize) to a single `save_retrospective.py` pipe command.
- **Session start SKILLS_TEXT** — removed `/pair-programming` reference (2 skills remain: `/smm-protocol`, `/xp-values`).

### Fixed
- **Stale lint concerns** — recorded as technical debt. Lint hook fires on intermediate file states during rapid edits, producing false positives that auto-resolve but clutter the SMM.

## v0.9.37 — Hook UX & Materializer Bug Fix

### Added
- **statusMessage for all hooks** — every hook in `hooks.json` now shows descriptive spinner text while running (e.g., "Checking shared mental model...", "Running lint check...")
- **systemMessage support** — hooks can now show user-facing notifications separate from agent-only `additionalContext`. New `block_output()` helper in `_common.py` encapsulates the block+systemMessage pattern.
- **PLUGIN_TOOLS.md documentation** — documents `statusMessage` (config), `systemMessage` (output), and `additionalContext` fields with examples and audience table.
- 2 new tests for resolved decision filtering (910 total)

### Fixed
- **Resolved decisions still rendered in materializer** — `render_markdown()` listed all decisions including resolved ones in the Architecture Decisions section. Now filters through `decision_resolutions` index, consistent with how concerns, goals, and debt are already filtered.
- **Unused `json` import in tdd_stop_gate.py** — removed (flagged by lint last session).

### Changed
- **Stop gates use `block_output()`** — `quality_review_gate.py`, `simplify_gate.py`, and `tdd_stop_gate.py` now use the shared helper instead of inline JSON construction, adding user-facing messages.
- **`BlockedError` supports `system_message`** — optional parameter for user-facing notifications on blocked tool calls.

## v0.9.36 — Direct SMM Loading & Simplify Gate Timing

### Added
- **Direct SMM + Behavioral Guide loading in housekeeping skill** — new `load_context.sh` script materializes the SMM after triage and outputs file paths. Step 5 in SKILL.md instructs the skill to Read both files, ensuring they are first-class conversation content rather than relying on `additionalContext` injection.
- 3 new integration tests for `load_context.sh` (908 total)

### Changed
- **Simplify gate message includes wait instruction** — tells the agent to wait 30 seconds for background review agents to complete before checking results, reducing premature TaskOutput failures.

## v0.9.35 — Session Review Gate Fix for /clear

### Fixed
- **Session review gate not firing after `/clear`** — `session_start.py` previously returned `None` immediately for `source="clear"`, skipping marker creation and context injection. After `/clear`, the session review gate never blocked, allowing retrospectives to be silently skipped. Now treats "clear" as a fresh start like "startup": sets `.needs-session-review` marker and injects GUPP + skills context.

### Changed
- **Module docstring updated** — reflects all handled SessionStart sources (startup, resume, compact, clear)
- 4 new tests (903 total)

## v0.9.34 — Decision Resolution & Stop Message Cleanup

### Fixed
- **Resolved decisions still flagged as stale drift** — `compute_resolutions()` now tracks `decision_resolutions` alongside concern/goal/debt resolutions. `detect_drift_signals()` skips topics where all decisions are resolved. Eliminates false "stale decision" drift signals for completed work.

### Changed
- **Quality gate stop messages simplified** — pending-agents message now just says count and to wait. Quality review message shortened to "Run the /xp-quality-review skill before stopping."
- 2 new tests (900 total)

## v0.9.33 — Auto-Resolve Lint Concerns

### Added
- **Auto-resolve lint concerns** — `lint_check.py` now resolves unresolved lint concerns when lint passes for a file. Matches by file path so only concerns for the specific file are resolved. Mirrors the existing test concern auto-resolve pattern.
- **`LINT_CONCERN_PREFIX`** constant in `_common.py` — shared prefix for lint concern content matching.
- **`resolve_concerns()` shared helper** in `_common.py` — parameterized concern resolution accepting a matcher function, agent ID, and label. Eliminates duplication between test and lint resolution.
- 4 new tests (898 total)

### Changed
- **`_resolve_test_concerns`** in `bash_post_tool.py` — now delegates to `_common.resolve_concerns()` instead of duplicating the resolution logic.
- **Resolved Concerns section** in materializer — shows summary count instead of per-item listing to reduce SMM bloat.

### Removed (via /simplify)
- **`_make_event()` / `_append_safe()` wrappers** in `bash_post_tool.py` — redundant pass-through wrappers replaced with direct `_common.*` calls.

## v0.9.32 — Async Agent Timing Fix

### Fixed
- **Quality review gate fires too early** — when `/simplify` spawns background agents, the Stop hook no longer triggers quality review before those agents complete. The gate now detects pending subagents (started but not completed) and blocks with agent IDs and actionable guidance until they finish.
- **`stop_hook_active` bypass removed from quality gate** — the early-return on `stop_hook_active=True` prevented the gate from re-checking after pending subagents completed. Removed since the tracker-based idempotency check already prevents infinite loops.

### Added
- **SubagentStart event recording** — `subagent_start.py` now appends a `STATUS` event (`"Subagent {id} started"`) after writing the watermark. Pairs with existing `"Subagent {id} completed"` from SubagentStop for lifecycle tracking.
- **`_pending_subagent_ids()` helper** in `quality_review_gate.py` — scans events since loop boundary for started-but-not-completed subagents.
- **`subagent_started_content()` / `subagent_completed_content()`** in `_common.py` — canonical format helpers eliminating magic string coupling across `subagent_start.py`, `subagent_stop.py`, and `quality_review_gate.py`.
- 8 new unit tests, 1 integration test (895 total)

### Assumption
- SubagentStart hooks fire for background Agent tool calls (`run_in_background=true`). Load-bearing for the entire approach. Needs empirical verification after deploy.

### Stats
- 895 tests (894 + 1 new integration)

## v0.9.31 — Speed Up Session Review

### Added
- **`bulk_append()`** — multi-event atomic writes with single lock acquisition. Validates all events before acquiring lock (fail-fast, no partial writes). `bulk_append_safe()` wrapper filters invalid events and swallows lock errors for hook safety.
- **`resolve_prefix()`** — short-ID prefix resolution in `compute_resolutions()`. Supports 8-char prefixes from materialized output.
- **Auto-resolve test concerns** — `bash_post_tool.py` now resolves unresolved test-failure concerns when tests pass (`failed == 0`). Fixes stale concern accumulation at the source rather than in housekeeping.
- **Retro digest** — structured summary in `.retro-input.json` replaces raw event dump: `signal_events` (full dicts for decisions/concerns/etc.), `status_summary` (counts + samples), `concern_groups` (deduplicated by normalized content). ~2-5KB vs 88KB.
- **`TEST_CONCERN_RE`** shared constant in `_common.py` — used by both `tdd_stop_gate.py` and `bash_post_tool.py`.
- 21 new tests (887 total)

### Changed
- **Retrospective agent prompt** — updated to consume digest format, preferring `digest` over raw `events_since_last_retro`.
- **`tdd_stop_gate.py`** — imports `TEST_CONCERN_RE` from `_common` instead of defining locally.

### Fixed (via /simplify)
- **Input mutation** — `bulk_append` no longer mutates caller's event dicts (shallow copy when ANSI stripping needed).
- **Hot-path cost** — `_resolve_test_concerns` does early-exit scan for test concerns before expensive `compute_resolutions`.
- **Redundant import** — `_normalize_concern_content` uses module-level `re` instead of re-importing.

## v0.9.30 — Plan Review Gate via PreToolUse + Documentation Update

### Changed
- **Plan review mechanism** — SubagentStop writes `plan_awaiting_review` marker event instead of blocking. PreToolUse detects unreviewed plans and injects `additionalContext` nudge before writes. Two-step mechanism replaces the exit-2 block that caused planning loops.
- **Documentation updated** — ARCHITECTURE.md and README.md updated to reflect v0.9.29 changes: navigator removal, TaskCompleted removal, plan review gate, concern deduplication, quality review drift management, SMM injection trigger change, platform findings.

## v0.9.29 — Remove Navigator & TaskCompleted, Fix Planning Loop

### Fixed
- **Planning loop** — SubagentStop was blocking Plan agent output (`decision:"block"`), preventing the plan from reaching the main agent and causing infinite re-planning loops (ran 8 hours, 6.1MB events.jsonl, ~60,000 duplicate concerns). Changed to nudge (`decision:"approve"` with reason). Note: platform silently drops nudge reasons on SubagentStop, but the plan output now reaches the agent.
- **Duplicate concerns** — `detect_conflicts()` now deduplicates against existing unresolved concerns before generating new ones. Resolved concerns excluded from dedup so recurring conflicts are re-detected.
- **TaskCompleted hook blocking** — Removed entirely. Was blocking the first task in every group because no `pair_guidance` event existed yet.
- **Quality review preload permission** — Added missing `Bash(*/skills/*/scripts/*)` to xp-quality-review skill allowed-tools.
- **SMM injection trigger** — Changed from `/xp-session-review` to `/xp-housekeeping` because the orchestrator skill returns immediately while sub-skills do the work.

### Removed
- **Navigator subagent** — `agents/xp-navigator.md` and `skills/xp-navigator/` deleted. SubagentStop only supports `decision:"block"` (caused loop) or silence; nudges via `decision:"approve"` are silently dropped by the platform. Concerns already visible via SMM delta for writes.
- **TaskCompleted hook** — `scripts/task_completed.py` deleted, hook entry removed from `hooks.json`. Too granular (per-task not per-conversation-turn) for useful enforcement.
- **Navigator Guidance materializer section** — A7 section removed from `materialize.py`. pair_guidance events still valid in logs but no longer rendered.
- **Navigator nudge in PreToolUse** — "Run /xp-navigator" no longer injected before writes.

### Added
- **Drift management in quality review** — New Step 3 in `/xp-quality-review` skill checks code changes against recorded decisions and conventions. Records concerns for drift. Replaces the strategic alignment review the navigator was doing.
- **Concern deduplication with resolution awareness** — `detect_conflicts()` uses `compute_resolutions()` to exclude resolved concerns from dedup set, allowing recurring conflicts to be re-detected after resolution.

### Changed
- **BEHAVIORAL_GUIDE.md** — Navigator references replaced with reviewer references.
- **`subagent_stop.py`** — Dead `BlockedError` handler removed from `__main__`.
- **Stale question concern content** — Changed from dynamic event count to stable string for reliable deduplication.

### Platform Findings
- **SubagentStop only supports block or silence** — `decision:"approve"` with `reason` is silently dropped. No `additionalContext` support. This limits enforcement options for plan review.
- **TaskCompleted fires per-task** — Not per-conversation-turn. Too granular for hooks that need conversation-level state (like "has navigator run?").

### Stats
- 858 tests (down from 872 — removed navigator and TaskCompleted tests, added dedup and concern injection tests)

## v0.9.26 — Deterministic SMM + Behavioral Guide Injection

### Added
- **`session_review_done.py`** — PostToolUse:Skill hook that fires after `/xp-session-review` completes. Materializes SMM and injects both the fresh SMM and BEHAVIORAL_GUIDE.md as `additionalContext` in a single deterministic step.
- 6 new tests for session_review_done (867 total)

### Changed
- **Behavioral guide moved out of SessionStart** — `session_start.py` no longer injects BEHAVIORAL_GUIDE.md. It's now injected by `session_review_done.py` after session review, together with the fresh SMM. This ensures the two are loaded together, in order: SMM first, then behavioral guide.
- **`xp-session-review` skill simplified** — removed manual materialize step (step 4). The PostToolUse:Skill hook handles it deterministically.

### Fixed
- **Test marker leak** — `test_graceful_no_smm_dir` passed a nonexistent `smm_dir` with `source="startup"`, causing `session_start.run()` to fall through to `init.sh` which resolved to the real project's SMM dir and created `.needs-session-review` there. This happened on every test suite run (including lefthook pre-commit), causing the session review gate to block mid-session. Fixed by mocking `resolve_plugin_root` in the test.

### Tech Debt Recorded
- `bash_failure.py` records false "Test command failed" concerns for compound Bash commands where a non-test command (e.g. `ls`) exits non-zero but the test itself passed. The TDD stop gate then sees the stale failure concern and blocks.

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

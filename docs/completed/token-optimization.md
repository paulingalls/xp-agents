# Token Optimization Plan

## Context

The xp-agents plugin injects context into agent conversations through multiple channels: skill preloads, SubagentStart hooks, PostToolUse hooks, PreToolUse hooks, SessionStart hooks, UserPromptSubmit hooks, and Stop hooks. Each injection point was built independently, leading to redundancy and excessive token usage.

The biggest offender: all 5 forked xp-* agents (plus Explore) are in the SubagentStart dispatch table, receiving full SMM + XP values + sprint.md (~2,500-4,000 tokens each) on top of whatever their preload already provides. Additionally, all 7 agents load xp-smm-protocol as a skill (~1,900 tokens each) despite having their own append.sh examples.

## What's Already Done

The **kickoff redesign** (see `docs/kickoff-redesign.md`) completed significant token optimization:
- **Housekeeping forked** — ~12K tokens of curation JSON moved out of main context
- **xp-work-selection** replaces xp-question-triage + xp-goal-collection (2 skills → 1)
- **kickoff_done.py** now injects SMM + process guide (main agent gets both after forked housekeeping)
- **Kickoff preload** simplified from ~105 to ~54 lines
- **~436 lines of obsolete code deleted**

The **behavioral guide split** separated BEHAVIORAL_GUIDE.md into two files:
- **XP_VALUES.md** (~400 tokens) — universal XP values, injected at session start for all agents
- **PROCESS_GUIDE.md** (~500 tokens) — plugin-specific process rules, injected only for main agent
- SubagentStart default tier (Plan, general-purpose) now gets XP values only (not process guide)
- Teammates get XP values + TEAMMATE_GUIDE.md
- Forked agent preloads (retro, housekeeping) use `dump_values` (not `dump_guide`)

**Estimated savings already realized: ~10K tokens from kickoff redesign + ~900 tokens per non-main agent invocation from guide split.**

## Strategy

- **Preload is canonical** for forked skills — SubagentStart should not duplicate what preload provides
- **Each injection point gets its own milestone** — the complexity of how events, skills, tools, and hooks interact demands individual attention
- **Necessary but sufficient** — every token injected must serve a purpose the agent actually needs

## How Forked Skills Work

Understanding the injection stack is critical for this work:

```
Subagent sees (in order):
┌─────────────────────────────────────────────┐
│ 1. agent .md              (system prompt)   │
├─────────────────────────────────────────────┤
│ 2. SKILL.md body + preload output  (prompt) │
├─────────────────────────────────────────────┤
│ 3. SubagentStart additionalContext (on top) │
└─────────────────────────────────────────────┘
```

- Preload output goes **directly to the subagent** as part of its prompt — not relayed by main agent
- SubagentStart fires for forked skills and its additionalContext is added **on top** of everything
- PostToolUse fires once for the Skill tool completion (no Agent tool matcher in hooks.json)
- PreToolUse:Write and PreToolUse:Bash fire **inside** subagents when they use those tools (xp-* agents skip via recursion guard)

## Per-Milestone Rules

1. **TDD for implementation milestones:** Write/update test → run red → implement → run green → commit
2. **Audits don't produce commits.** An audit that concludes "confirmed optimal" is a finding, not a code change. If an audit discovers changes needed, create a mini red-green-commit cycle for the implementation — that's a separate step within the milestone.
3. **Commit after each green implementation** — don't batch across milestones
4. **Verify agent .md references** before removing any injection source — if the agent prompt says "the full curated SMM is preloaded above," the preload must actually provide it or the prompt must be updated
5. **Acceptance criteria for audits:** Each audit milestone produces either "confirmed optimal — no changes" or a concrete follow-up implementation with specific code changes and estimated savings

## Critical Files

- `scripts/subagent_start.py` — SubagentStart dispatch
- `scripts/*.py` — all hook scripts
- `skills/*/SKILL.md` — all skill definitions
- `skills/*/scripts/*.sh` — all preload scripts
- `agents/*.md` — all agent definitions (7 agents: xp-retrospective, xp-security-reviewer, xp-plan-reviewer, xp-sprint-reviewer, xp-sprint-retro, xp-spawn-team, xp-housekeeper)
- `skills/_preload_base.sh` — shared preload helpers
- `hooks/hooks.json` — hook registrations
- `tests/hooks/test_subagent_tiers.py` — SubagentStart tier tests

---

## Phase 1: Forked Skill Preloads + SubagentStart Dispatch

Ensure each preload provides what its agent needs, then remove xp-* agents from SubagentStart dispatch.

### M1: xp-run-retrospective / xp-retrospective

**Current preload:** SMM_DIR, RETRO_INPUT path, XP values via `dump_values` (~1K tokens)
**Current SubagentStart:** full SMM + XP values + sprint.md (~2,500-4,000 tokens)
**Overlap:** XP values duplicated. Full SMM and sprint.md unnecessary.

**Agent needs:** SMM_DIR, retro-input.json path, XP values (for analysis lenses). Does NOT need full SMM or sprint.md — retro-input.json has the event digest.

**Verification checklist:**
- [ ] Read `agents/xp-retrospective.md` — confirm it does NOT reference "full curated SMM" or sprint.md as being preloaded
- [ ] Confirm preload provides everything the agent .md says is available
- [ ] If agent .md references data that won't be injected, update the agent .md

**Action:** No preload changes needed — already sufficient. Update agent .md if needed.
**Test:** Assert `subagent_start.run()` returns `None` for agent_type "xp-retrospective"
**Files:** `scripts/subagent_start.py`, `agents/xp-retrospective.md`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] `agents/xp-retrospective.md` verified — no references to "full curated SMM" or sprint.md as preloaded content
- [x] Preload output matches everything agent .md says is available (SMM_DIR, RETRO_INPUT, XP values)
- [x] `subagent_start.run()` returns `None` for agent_type "xp-retrospective"
- [x] Full test suite passes (1366 tests)

### M2: xp-security-triage / xp-security-reviewer

**Current preload:** SMM_DIR, full git diffs (~2K-50K variable)
**Current SubagentStart:** Nothing (not in dispatch — already clean)
**Agent needs:** SMM_DIR, diffs

**Audit:** Verify this is already optimal. Check if diff output could be trimmed for large changesets (e.g., stat-only when diff exceeds a threshold, full diff for small ones).
**Files:** `skills/xp-security-triage/scripts/preload_diff.sh`, `agents/xp-security-reviewer.md`

**Acceptance criteria:**
- [x] Preload confirmed optimal — added `dump_values` for XP values (Courage)
- [x] No SubagentStart injection for "xp-security-reviewer" (confirmed clean)
- [x] `agents/xp-security-reviewer.md` rewritten — removed `skills: [xp-smm-protocol]` (M8 early), removed SMM Content Trust (irrelevant), strengthened MUST-run instructions, added explicit report-back step
- [x] Full test suite passes (1367 tests)

### M3: xp-review-plan / xp-plan-reviewer

**Current preload:** SMM_DIR, plan file content (~3K-10K). No SMM, no sprint. Preload comment says "SMM, sprint, and guide are injected by SubagentStart."
**Current SubagentStart:** full SMM + XP values + sprint.md (~2,500-4,000 tokens)

**Agent .md issue:** Lines 18-21 claim "The full curated SMM" and "sprint.md" are preloaded, but they actually come from SubagentStart additionalContext, not the preload. When moving data to preload, the prompt text becomes accurate — but must be updated to match exactly what preload provides (selective pillars vs full SMM).

**Agent needs:** SMM_DIR, plan content, SMM pillars for conflict checking, sprint.md for scope alignment. Does NOT need XP values or process guide.

**Verification checklist:**
- [ ] Read `agents/xp-plan-reviewer.md` — identify every reference to SMM pillars, sprint.md, XP values
- [ ] Decide: full SMM (simpler, ~500 extra tokens) or selective pillars (saves ~200 tokens but risks incomplete review)
- [ ] Update agent .md to accurately describe what's available

**Action:** Add SMM extraction and sprint.md to preload via `_preload_base.sh` helpers. Update agent .md.
**Test:** Assert `subagent_start.run()` returns `None` for agent_type "xp-plan-reviewer". Verify preload outputs expected sections.
**Files:** `skills/xp-review-plan/scripts/preload.sh`, `agents/xp-plan-reviewer.md`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] Preload provides full SMM + sprint.md + XP values via `_preload_base.sh` helpers
- [x] `agents/xp-plan-reviewer.md` accurately describes what preload provides (not SubagentStart)
- [x] Decision: full SMM (all 4 pillars needed — Intent for scope, Constraints for conflicts, Risks for awareness, Wisdom for behavioral rules)
- [x] Removed `skills: [xp-smm-protocol]` (M8 early)
- [x] `subagent_start.run()` returns `None` for agent_type "xp-plan-reviewer"
- [x] Full test suite passes (1367 tests)

### M4: xp-sprint-review / xp-sprint-reviewer

**Current preload:** SMM_DIR, REVIEW_INPUT path only (~200 tokens). review-input.json contains sprint_md + product_spec_md.
**Current SubagentStart:** full SMM + XP values + sprint.md (~2,500-4,000 tokens)
**Overlap:** sprint.md in both input JSON and SubagentStart. XP values unnecessary for review.

**Agent needs:** SMM_DIR, review-input.json path. Maybe Intent + Constraints pillars for context.

**Action:** Optionally add selective SMM pillars to preload. Update agent .md.
**Test:** Assert `subagent_start.run()` returns `None` for agent_type "xp-sprint-reviewer"
**Files:** `skills/xp-sprint-review/scripts/preload.sh`, `agents/xp-sprint-reviewer.md`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] Preload confirmed minimal — SMM_DIR + REVIEW_INPUT path only (no SMM, no values, no sprint content)
- [x] `prepare_review_data.py` outputs paths (sprint_md_path, product_spec_md_path) instead of embedded content
- [x] `agents/xp-sprint-reviewer.md` rewritten — agent Reads files directly, removed `skills: [xp-smm-protocol]`
- [x] `subagent_start.run()` returns `None` for agent_type "xp-sprint-reviewer"
- [x] Simplified `allowed-tools` in SKILL.md (forked skill cleanup)
- [x] Full test suite passes (1367 tests)

### M5: xp-run-sprint-retro / xp-sprint-retro

**Current preload:** SMM_DIR, RETRO_INPUT path only (~200 tokens). retro-input.json contains sprint_md + session_retros.
**Current SubagentStart:** full SMM + XP values + sprint.md (~2,500-4,000 tokens)
**Overlap:** sprint.md duplicated. Full SMM unnecessary.

**Agent needs:** SMM_DIR, retro-input.json path, XP values (for analysis lenses — same as session retro).

**Action:** Add `dump_values` to preload (following xp-run-retrospective pattern). Update agent .md.
**Test:** Assert `subagent_start.run()` returns `None` for agent_type "xp-sprint-retro"
**Files:** `skills/xp-run-sprint-retro/scripts/preload.sh`, `agents/xp-sprint-retro.md`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] Preload includes XP values (`dump_values`) + Constraints/Wisdom pillars (`smm_section`)
- [x] `prepare_sprint_retro_data.py` outputs `sprint_md_path` instead of embedded `sprint_md`
- [x] `agents/xp-sprint-retro.md` rewritten — step-by-step, removed `skills: [xp-smm-protocol]`, added constraint/wisdom compliance analysis
- [x] `subagent_start.run()` returns `None` for agent_type "xp-sprint-retro"
- [x] Simplified `allowed-tools` in SKILL.md (forked skill cleanup)
- [x] Full test suite passes (1367 tests)

### M6: xp-spawn-team / xp-spawn-team

**Current preload:** SMM_DIR, plan file content (~3K-10K). No SMM, no sprint. Preload comment says "SMM, sprint, and guide are injected by SubagentStart."
**Current SubagentStart:** full SMM + XP values + sprint.md (~2,500-4,000 tokens)

**Agent .md issue:** Lines 18-25 claim SMM, sprint data, plan are all preloaded with "Do NOT re-read these files." But the preload only provides SMM_DIR + plan content. SMM comes from SubagentStart. Prompt must be updated to match what preload actually provides.

**Agent needs:** SMM_DIR, plan content, SMM context for team planning, sprint.md for story decomposition. Does NOT need XP values or process guide.

**Action:** Add SMM extraction and sprint.md to preload. Update agent .md.
**Test:** Assert `subagent_start.run()` returns `None` for agent_type "xp-spawn-team"
**Files:** `skills/xp-spawn-team/scripts/preload.sh`, `agents/xp-spawn-team.md`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] Preload provides Constraints/Wisdom pillars + sprint.md + plan content
- [x] `agents/xp-spawn-team.md` updated — removed `skills: [xp-smm-protocol]`, accurate "What You Already Have"
- [x] `subagent_start.run()` returns `None` for agent_type "xp-spawn-team"
- [x] Simplified `allowed-tools` in SKILL.md (forked skill cleanup)
- [x] Full test suite passes (1367 tests)

### M7: Remove xp-* agents from SubagentStart dispatch + cleanup

**Depends on:** M1-M6 (all preloads verified and updated)

**Current:** 5 xp-* agents in `_DISPATCH` using `_inject_with_sprint()` → full SMM + XP values + sprint.md
**Target:** Remove all 5 entries. `_DISPATCH` contains only `"Explore"`. Remove `_inject_with_sprint()`, `sprint_state` import.

**Note:** xp-housekeeper (added in kickoff redesign M2) already returns None via the xp-* guard — no dispatch entry needed.

**Savings:** ~12,000-20,000 tokens per session

**Test:** Update all 5 xp-* agent tests to assert `result is None`. Consolidate into parameterized test. Run full test suite.
**Files:** `scripts/subagent_start.py`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] `_DISPATCH` contains only `"Explore"` — all xp-* entries removed (M1-M6)
- [x] `_inject_with_sprint()` function removed
- [x] `sprint_state` import removed from `subagent_start.py`
- [x] All xp-* agent tests assert `result is None` (M1-M6)
- [x] Full test suite passes (1367 tests)
- [x] Docstring updated to reflect simplified dispatch

---

## Phase 2: Agent System Prompt Optimization

### M8: Remove xp-smm-protocol from all agent skills entries

**Current:** All 7 agents have `skills: [xp-smm-protocol]` loading ~1,900 tokens of reference docs. All agents have their own append.sh examples inline.
**Savings:** ~1,900 x 7 = ~13,300 tokens per session

**Open question:** Does the `skills:` entry auto-load into context or just make it available on demand? Verify before implementing — if on-demand only, savings are smaller.

**Pre-audit:** Before removing, verify each agent only records event types covered by its inline examples. Agents that need diverse event types may need a minimal inline reference added to their .md.

**Action:** Remove `skills:` block from all 7 agent .md frontmatter. Keep xp-smm-protocol as inline skill for main agent.
**Test:** Update plugin integrity test (`test_skills_include_smm_protocol`) — either remove the test or invert it.
**Files:** All 7 `agents/*.md` files, `tests/hooks/test_plugin_integrity.py`

**Acceptance criteria:**
- [x] Investigation complete: `skills:` auto-loads full skill content into subagent context (not on-demand)
- [x] All 7 agents: `skills: [xp-smm-protocol]` removed (5 during M1-M6, 2 in M8)
- [x] Each agent has inline append.sh examples in their .md
- [x] Plugin integrity test inverted — asserts NO agent has xp-smm-protocol
- [x] Full test suite passes (1366 tests)
- [x] Token savings: ~13,300 tokens (1,900 x 7) per session removed from agent context

### M9: Optimize non-plugin agent tiers (Explore, Plan, teammates, default)

**Current (after behavioral guide split):**
- Explore: Intent + Constraints only (~200 tokens) — already lean
- Plan: full SMM + XP values (~900 tokens) — ✅ reduced from ~2,700 (guide split)
- Teammates: SMM + XP values + teammate guide (~1,300 tokens) — ✅ values added (guide split)
- Default (general-purpose): full SMM + XP values (~900 tokens) — ✅ reduced from ~2,700 (guide split)

**Files:** `scripts/subagent_start.py`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] Explore tier: confirmed lean — Intent + Constraints only, no values needed (pure search agent)
- [x] Plan tier: full SMM + XP values — needs all pillars for varied work (guide split)
- [x] Teammates tier: full SMM + XP values + teammate guide (guide split)
- [x] Default tier: full SMM + XP values — needs all pillars for varied work (guide split)
- [x] SMM pillar audit: full SMM appropriate for Plan/teammates/default (they do varied work); selective pillars only for Explore (search-focused)
- [x] Full test suite passes (1366 tests)

---

## Phase 3: Inline Skill Preloads (One Per Skill)

Each milestone: audit what the preload injects into main agent context, whether it's necessary, and if it can be trimmed. Produce either "confirmed optimal" or a concrete implementation.

**Note:** M10-M13 from the original plan were superseded by the kickoff redesign. The milestones below cover the remaining inline skills.

### M10: xp-kickoff ✅ (DONE — kickoff redesign)

Preload simplified from ~105 to ~54 lines. GOALS_REVIEW, QUESTIONS_CHECK, HOUSEKEEPING sections removed. Body simplified to 6-step flow referencing xp-work-selection and xp-housekeeping skills.

### M11: xp-work-selection ✅ (confirmed optimal)

**Current preload:** `preload.sh` → Try items from retro, open questions from SMM Risks, sprint status, customer intent (~200-500 tokens variable)
**Body:** ~600 tokens — 3-step flow (Try items, questions, sprint/work selection)
**Assessment:** Already optimized during kickoff redesign. Lean preload using shared helpers from `_preload_base.sh`. Runs before housekeeping so no SMM or process guide in context — XP values from SessionStart are sufficient. All preload data is bounded by SMM caps (Risks ~10 items, Intent ~10 items).

**Acceptance criteria:**
- [x] Preload confirmed lean (<500 tokens variable output)
- [x] No redundant data between preload and SKILL.md body
- [x] Full test suite passes (1366 tests)

### M12: xp-housekeeping ✅ (confirmed optimal — kickoff redesign)

Forked to xp-housekeeper subagent. Curation JSON (~12K tokens) no longer enters main context. Preload writes `.curation-input.json` to disk; agent reads it via Read tool. kickoff_done.py injects SMM + process guide (~800 tokens) after completion. XP values injected via preload `dump_values` — needed for curation judgment calls (Simplicity guides pruning, Courage guides keeping uncomfortable risks visible).

### M13: xp-quality-review

**Current preload:** diff stat of uncommitted changes + new untracked files + technical debt for changed files + open plan concerns
**Body:** ~1,300 tokens
**Audit:** Diff uses `--stat` only (lightweight). Agent reads individual files via Read tool when needed. Bug found: preload used `HEAD~1` (previous commit) instead of `HEAD` (uncommitted changes). Fixed `dump_diff` and `changed_files` to use `git diff HEAD` + `git ls-files --others --exclude-standard` for new files.

**Acceptance criteria:**
- [x] Diff injection strategy audited — `--stat` only (file names + line counts), agent reads files individually. Fixed to show uncommitted changes (`HEAD`) instead of previous commit (`HEAD~1`). New untracked files now included.
- [x] Debt entry filtering verified efficient — per-file lookup via `find_debt_for_file`, output truncated at 120 chars
- [x] Body size verified appropriate (~1,300 tokens, 122 lines, 7-step review)
- [x] Full test suite passes (1370 tests — 4 new preload tests added)

### M14: xp-product-spec

**Current preload:** feature counts + `PRODUCT_SPEC=<path>` or "create mode" message
**Body:** ~1,400 tokens
**Audit:** Previously injected full product_spec.md content. Changed to path-based — agent reads via Read tool when needed. Preload now outputs ~3 lines (SMM_DIR, counts, path) regardless of spec size.

**Acceptance criteria:**
- [x] Large product spec handling audited — path-based alternative implemented, agent reads on demand
- [x] Token size: preload is now O(1) — fixed ~50 tokens regardless of spec size. Body ~1,400 tokens unchanged.
- [x] Full test suite passes (1370 tests)

### M15: xp-sprint-start

**Current preload:** feature counts + `PRODUCT_SPEC=<path>`, deferred stories, NEXT_SPRINT_ID
**Body:** ~1,500 tokens
**Audit:** Previously injected full product_spec.md content. Changed to path-based — agent reads via Read tool. Deferred story detection is efficient (grep-based, shows only headers). SMM context for sprint-start and product-spec handled by kickoff reading SMM before steps 2-3 (not in preloads — they're inline skills sharing main agent context).

**Acceptance criteria:**
- [x] Product spec handling: path-based (`PRODUCT_SPEC=<path>`) instead of full content injection
- [x] Deferred story filtering verified efficient — grep-based, shows only deferred story headers
- [x] SMM context: kickoff reads SMM before invoking product-spec/sprint-start (inline skills)
- [x] Full test suite passes (1370 tests)

### M16: xp-accept

**Current preload:** in-progress count + `SPRINT_FILE=<path>` or ERROR/NO_IN_PROGRESS flag
**Body:** ~600 tokens
**Audit:** Previously dumped full sprint.md content. Changed to path-based — agent reads via Read tool in Step 1. Preload now outputs ~3 lines regardless of sprint size.

**Acceptance criteria:**
- [x] Changed from full sprint content to path-based (`SPRINT_FILE=<path>`) — agent reads on demand
- [x] Token size: preload is now O(1) — fixed ~50 tokens. Body ~600 tokens unchanged.
- [x] Full test suite passes (1374 tests — 4 new preload tests added)

### M17: xp-smm-protocol ✅ (confirmed optimal)

**Current:** No preload. ~1,200 tokens of reference documentation. On-demand only — invoked via `/xp-smm-protocol`, not auto-loaded.
**Audit:** Since M8 removed it from all agent `skills:` entries, token cost is zero unless explicitly invoked. Content is well-structured: event types table, question priority guide, working_on/references fields, good vs bad examples, 4 common recording patterns. All sections serve a purpose — patterns teach syntax that the behavioral guide doesn't cover.

**Acceptance criteria:**
- [x] Reference doc size measured — 142 lines, ~1,200 tokens as expected
- [x] Content verified necessary — all sections serve distinct purposes, no redundancy
- [x] Confirmed minimal — on-demand invocation means zero cost unless called. No trim needed.
- [x] Full test suite passes (1374 tests)

---

## Phase 4: Hook Injection Audits (One Per Hook Event)

Each milestone: audit what the hook injects as additionalContext, how often it fires, and whether the injection is necessary and appropriately sized.

### M18: SessionStart hooks (`session_start.py` + `retrospective.py`)

**session_start.py injections:**
- GUPP text (~30 tokens) — startup: "Run /xp-kickoff", resume: "Check SMM, resume"
- XP values (~400 tokens) — always
- On compact: SMM + process guide re-injection (~1,500 tokens). Sprint.md removed — agent reads on demand.

**retrospective.py injections:**
- Kickoff prep summary (~200-300 tokens) — event counts + health signals only, if 5+ unanalyzed events. Full data goes to .retro-input.json on disk for subagent.

**Audit:** Skills list (SKILLS_TEXT) removed in xp-smm-protocol merge. Sprint.md removed from compact re-injection — SMM Sprint pillar summary is sufficient, agent reads full sprint on demand. Compact re-injection of SMM + process guide is necessary (context lost during compaction).

**Acceptance criteria:**
- [x] GUPP text verified minimal (~30 tokens)
- [x] Skills list removed — merged into PROCESS_GUIDE.md (xp-smm-protocol merge)
- [x] Compact re-injection: SMM + process guide necessary (context lost). Sprint.md removed — saves ~700-1,700 tokens per compact.
- [x] retrospective.py: lean (~200-300 tokens counts only, heavy data on disk)
- [x] Full test suite passes (1373 tests)

### M19: UserPromptSubmit hooks (`user_prompt_log.py` + `kickoff_gate.py` + `prompt_nugget.py`)

**user_prompt_log.py:** No injection (records only)
**kickoff_gate.py:** ~100-300 tokens when `.needs-kickoff` marker exists (one-time)
**prompt_nugget.py:** ~100 tokens max (3 events via watermark, one-time per batch)

**Audit:** Already well-deduped via markers and watermarks. Verify token sizes are minimal.

**Acceptance criteria:**
- [x] kickoff_gate.py: one-time block/nudge (~100-200 tokens), consumed when kickoff runs
- [x] prompt_nugget.py: watermark-deduped, top 3 events, 120 chars each (~100 tokens max)
- [x] user_prompt_log.py: record-only, returns None always, truncates at 10K chars
- [x] Deduplication verified — marker-based (kickoff gate) and watermark-based (prompt nugget)
- [x] Full test suite passes (1373 tests)

### M20: SubagentStop hook (`subagent_stop.py`)

**Audit:** Verify this is record-only with no context injection overhead.

**Acceptance criteria:**
- [x] Confirmed record-only — `run()` returns `None` always. No `hook_output()` call.
- [x] Processing is minimal: status event, coordination clear, conflict detection, plan review gate
- [x] Full test suite passes (1376 tests)

### M21: PostToolUse:Write hooks (`post_tool_use.py` + `lint_check.py`)

**post_tool_use.py:** Records file changes, detects conflicts. Returns None (no injection).
**lint_check.py:** Lint error output (~100-300 tokens if linter fails). No-linter nudge (~100 tokens, once per session via `.lint-warned` marker).

**Acceptance criteria:**
- [x] post_tool_use.py confirmed no injection — returns None always
- [x] lint_check.py: lint errors ~100-300 tokens (linter output). Auto-resolves lint concerns when file is clean.
- [x] No-linter nudge: one-time per session via atomic `.lint-warned` flag. Only for code files.
- [x] Full test suite passes (1376 tests)

### M22: PostToolUse:Bash hook (`bash_post_tool.py`)

**Current:** Fires on every Bash command but well-filtered — only injects for commits (None), pushes (session-end checklist ~50 tokens), and test runs (commit nudge ~50 tokens when green). All other commands return None.

**Acceptance criteria:**
- [x] No "advisory on every command" — plan description was wrong. Hook returns None for non-commit/push/test commands.
- [x] Git commit: record-only (None). Records status, checks commit size, resolves lint, resets review cycle.
- [x] Git push: session-end checklist nudge (~50-100 tokens). Appropriate — reminds about unresolved concerns.
- [x] Test runs: commit nudge (~50-100 tokens) only when green + uncommitted files. Otherwise None.
- [x] Full test suite passes (1376 tests)

### M23: PostToolUse:Skill hooks (`review_cycle_done.py` + `kickoff_done.py` + `accept_done.py` + `sprint_review_done.py`)

**review_cycle_done.py:** Text nudges (~50-150 tokens)
**kickoff_done.py:** SMM (~300-600 tokens) + PROCESS_GUIDE.md (~500 tokens) + optional sprint nudge. One-time after housekeeping. XP values already in context from session start.
**accept_done.py:** Text nudge (~30 tokens) — conditional
**sprint_review_done.py:** Text nudge (~30 tokens) + sprint end event

**Audit:** kickoff_done is the biggest but already trimmed (process guide only, ~500 tokens — values injected at session start). All 4 hooks fire on EVERY Skill completion — verify each checks skill name before injecting.

**Acceptance criteria:**
- [x] All 4 hooks gate on skill name — no spurious injection on unrelated skills
- [x] kickoff_done.py: SMM (~300-600) + process guide (~1,500 tokens after merge). One-time after housekeeping.
- [x] review_cycle_done.py: ~30 token nudges per step. Plan review: ~50 token task creation nudge.
- [x] accept_done.py: ~30 token sprint-complete nudge (conditional). Records iteration_complete.
- [x] sprint_review_done.py: ~30 token retro nudge. Records sprint end event with velocity.
- [x] Full test suite passes (1376 tests)

### M24: PostToolUse:ExitPlanMode hook (`post_tool_exit_plan.py`)

**Audit:** Verify injection size. Fires once per plan exit.

**Acceptance criteria:**
- [x] Injection size: ~50 tokens ("IMPORTANT: Run /xp-review-plan NOW..."). Confirmed minimal.
- [x] Fires once per plan exit. Writes `.plan-awaiting-review` marker with plan path.
- [x] Full test suite passes (1376 tests)

### M25: PreToolUse:Write hook (`pre_tool_write.py`)

**Current:** TDD reminder (~100 tokens, conditional). Plan review gate (blocks). Conflict check. Accept marker.
**Audit:** TDD reminder fires on non-code files (DEBT — fix in M31). Verify other injections are minimal.

**Acceptance criteria:**
- [x] TDD reminder: ~50 tokens, conditional (2+ impl files without test). Only injection in this hook.
- [x] Plan review gate: blocks via exit 2, no injection. Plan files exempt.
- [x] Conflict check: blocks via exit 2, no injection. Uses coordination.json (O(1), no event log scan).
- [x] Accept marker: writes marker only, no injection.
- [x] False positive on non-code files: known debt (M31). Not addressed here.
- [x] Full test suite passes (1376 tests)

### M26: PreToolUse:Bash hook (`pre_tool_bash.py`)

**Current:** File modification advisory (~80 tokens). Commit gate (blocks, no injection).
**Audit:** How often does the advisory fire? Is it useful or noise?

**Acceptance criteria:**
- [x] File modification advisory: conditional (~50 tokens), only fires when bash command modifies a file claimed by another agent in coordination.json. Rare in practice.
- [x] Advisory confirmed useful — necessary for agent team file coordination on bash commands (Write/Edit has its own check)
- [x] Commit gate: blocks via exit 2 only, no injection. Enforces review cycle or security triage.
- [x] Full test suite passes (1380 tests)

### M27: Stop hooks (`tdd_stop_gate.py` + `accept_gate.py` + `session_end_warning.py`)

**tdd_stop_gate.py:** Blocks via exit 2 + stderr. No additionalContext.
**accept_gate.py:** Blocks via exit 2 + stderr. No additionalContext.
**session_end_warning.py:** Session-end checklist (~100 tokens). Every stop attempt.

**Audit:** Verify exit 2 + stderr pattern (no JSON overhead). session_end_warning may inject unnecessarily.

**Acceptance criteria:**
- [x] tdd_stop_gate.py: blocks via exit 2 + stderr (~50 tokens). No additionalContext.
- [x] accept_gate.py: blocks via exit 2 + stderr (~50 tokens). Defers if review cycle active or teammates running.
- [x] session_end_warning.py: soft warning via `{"reason": "..."}` (~50-100 tokens). Unresolved concern count + summarize reminder. Stop hooks don't support additionalContext.
- [x] Full test suite passes (1380 tests)

### M28: Teammate hooks (`teammate_idle.py` + `task_completed.py`)

**Audit:** What do these inject? How often do they fire during agent team work?

**Acceptance criteria:**
- [x] teammate_idle.py: blocks via exit 2 + stderr (~50 tokens) when tests failing. Teammate-scoped.
- [x] task_completed.py: identical pattern — blocks when tests failing. Teammate-scoped.
- [x] Both use shared `tdd_check.find_last_test_signal()` — consistent with tdd_stop_gate.py
- [x] Firing frequency: only during agent team work (teammate idle/task complete events). Not hot path.
- [x] Full test suite passes (1380 tests)

### M29: Other hooks (`bash_failure.py`, `session_end.py`, `pre_compact.py`)

**Audit:** Primarily record-only. Verify no context injection.

**Acceptance criteria:**
- [x] bash_failure.py: record-only — test failure status + concern. Returns None. Skips non-test commands early.
- [x] session_end.py: record-only — session_end event with summary. Clears coordination + session flags. Returns None.
- [x] pre_compact.py: record-only — backs up events.jsonl + SMM. Rotates to 10 max. Returns None.
- [x] Full test suite passes (1380 tests)

---

## Phase 5: Data Optimization

### M30: Sprint input JSON optimization

**Current:** `prepare_review_data.py` and `prepare_sprint_retro_data.py` embed full `sprint_md` content in JSON.
**Target:** Replace with `sprint_md_path` reference. Agents can Read if needed — structured fields already contain key data.
**Savings:** ~700-1,700 tokens per invocation
**Files:** Both prep scripts, both agent .md files, test files

**Acceptance criteria:**
- [x] `prepare_review_data.py` uses `sprint_md_path` reference (done in M4)
- [x] `prepare_sprint_retro_data.py` uses `sprint_md_path` reference (done in M5)
- [x] Both agent .md files updated — `sprint_md_path` documented, agents Read from path
- [x] Tests updated for path-based JSON schema (M4/M5)
- [x] Token savings: ~700-1,700 tokens per invocation (sprint content stays on disk)
- [x] Full test suite passes (1380 tests)

### M31: Fix TDD tracker false positives (debt item) ✅

**Fixed:** `check_tdd_order()` now calls `security.is_code_file()` — non-code files skip TDD tracking. Also fixed `is_code_file()` dotfile bug (`.gitignore`, `.env`, etc. were misclassified as code because `Path(".gitignore").suffix == ""`). Moved dotfiles from `_NON_CODE_SUFFIXES` to `_NON_CODE_NAMES`.

**Acceptance criteria:**
- [x] `security.is_code_file()` used in `pre_tool_write.py` (not reimplemented)
- [x] Markdown (.md) writes do not trigger TDD nudge
- [x] Python (.py) writes without preceding test still trigger TDD nudge
- [x] product_spec.md, sprint.md confirmed excluded
- [x] Tests written first (TDD): 3 new TDD tests + expanded is_code_file coverage (all supported languages)
- [x] Dotfile classification bug fixed — `.gitignore`, `.env`, etc. now correctly excluded
- [x] Full test suite passes (1380 tests)

---

## Implementation Order

### Sprint 1: SubagentStart dispatch (M1-M7)
1. **M1-M6** — Verify and update each forked skill preload (one commit per milestone)
2. **M7** — Remove xp-* from SubagentStart dispatch + cleanup dead code

### Sprint 2: Agent optimization + inline skill audits (M8-M17)
- **M8** — Remove xp-smm-protocol from agent skills (pending investigation of auto-load vs on-demand)
- **M9** — Optimize non-plugin agent tiers
- **M10-M12** — Already done (kickoff redesign)
- **M13-M17** — One milestone per remaining inline skill

### Sprint 3: Hook audits (M18-M29)
- One milestone per hook event, each produces "confirmed optimal" or follow-up implementation

### Sprint 4: Data optimization + debt (M30-M31)
- Sprint JSON optimization + TDD tracker fix

## Verification

After each sprint:
- Run full test suite: `python3 -m unittest discover -s plugins/xp-agents/tests -p "test_*.py" -v`
- After Sprint 1: test full session flow (kickoff → plan → implement → review cycle → sprint review → sprint retro) to verify agents still get needed context

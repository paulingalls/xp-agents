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
- [ ] Preload provides SMM + sprint.md via `_preload_base.sh` helpers
- [ ] `agents/xp-spawn-team.md` lines 18-25 updated to match what preload actually provides
- [ ] `subagent_start.run()` returns `None` for agent_type "xp-spawn-team"
- [ ] Full test suite passes

### M7: Remove xp-* agents from SubagentStart dispatch + cleanup

**Depends on:** M1-M6 (all preloads verified and updated)

**Current:** 5 xp-* agents in `_DISPATCH` using `_inject_with_sprint()` → full SMM + XP values + sprint.md
**Target:** Remove all 5 entries. `_DISPATCH` contains only `"Explore"`. Remove `_inject_with_sprint()`, `sprint_state` import.

**Note:** xp-housekeeper (added in kickoff redesign M2) already returns None via the xp-* guard — no dispatch entry needed.

**Savings:** ~12,000-20,000 tokens per session

**Test:** Update all 5 xp-* agent tests to assert `result is None`. Consolidate into parameterized test. Run full test suite.
**Files:** `scripts/subagent_start.py`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [ ] `_DISPATCH` contains only `"Explore"` — all 5 xp-* entries removed
- [ ] `_inject_with_sprint()` function removed (if it exists)
- [ ] `sprint_state` import removed from `subagent_start.py` (if no longer needed)
- [ ] All xp-* agent tests assert `result is None` (parameterized)
- [ ] Full test suite passes
- [ ] Token savings verified: ~12,000-20,000 tokens per session removed from subagent injection

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
- [ ] Investigation complete: confirmed whether `skills:` auto-loads into context or is on-demand only
- [ ] Pre-audit: each agent's event types cataloged vs. xp-smm-protocol coverage
- [ ] All 7 agents: `skills: [xp-smm-protocol]` removed from frontmatter
- [ ] Each agent has inline append.sh examples covering all event types it records
- [ ] Plugin integrity test updated (removed or inverted)
- [ ] Full test suite passes
- [ ] Token savings verified: ~13,300 tokens (1,900 x 7) per session

### M9: Optimize non-plugin agent tiers (Explore, Plan, teammates, default)

**Current (after behavioral guide split):**
- Explore: Intent + Constraints only (~200 tokens) — already lean
- Plan: full SMM + XP values (~900 tokens) — ✅ reduced from ~2,700 (guide split)
- Teammates: SMM + XP values + teammate guide (~1,300 tokens) — ✅ values added (guide split)
- Default (general-purpose): full SMM + XP values (~900 tokens) — ✅ reduced from ~2,700 (guide split)

**Remaining audit per tier:**
- Does Plan need full SMM or only selective pillars?
- Does default need full SMM?
- Are teammates getting the right SMM content?

**Files:** `scripts/subagent_start.py`, `tests/hooks/test_subagent_tiers.py`

**Acceptance criteria:**
- [x] Explore tier: confirmed lean (Intent + Constraints only)
- [x] Plan tier: XP values only, no process guide (guide split)
- [x] Teammates tier: SMM + XP values + teammate guide (guide split)
- [x] Default tier: XP values only, no process guide (guide split)
- [ ] Remaining: evaluate whether full SMM is needed per tier or if selective pillars suffice
- [ ] Full test suite passes

---

## Phase 3: Inline Skill Preloads (One Per Skill)

Each milestone: audit what the preload injects into main agent context, whether it's necessary, and if it can be trimmed. Produce either "confirmed optimal" or a concrete implementation.

**Note:** M10-M13 from the original plan were superseded by the kickoff redesign. The milestones below cover the remaining inline skills.

### M10: xp-kickoff ✅ (DONE — kickoff redesign)

Preload simplified from ~105 to ~54 lines. GOALS_REVIEW, QUESTIONS_CHECK, HOUSEKEEPING sections removed. Body simplified to 6-step flow referencing xp-work-selection and xp-housekeeping skills.

### M11: xp-work-selection (NEW — replaces xp-question-triage + xp-goal-collection)

**Current preload:** `preload.sh` → Try items from retro, open questions from SMM Risks, sprint status, customer intent (~200-500 tokens variable)
**Body:** ~600 tokens — 3-step flow (Try items, questions, sprint/work selection)
**Assessment:** Already optimized during kickoff redesign. Lean preload using shared helpers from `_preload_base.sh`.

**Acceptance criteria:**
- [ ] Preload confirmed lean (<500 tokens variable output)
- [ ] No redundant data between preload and SKILL.md body
- [ ] Full test suite passes

### M12: xp-housekeeping ✅ (DONE — kickoff redesign)

Forked to xp-housekeeper subagent. Curation JSON (~12K tokens) no longer enters main context. Preload writes `.curation-input.json` to disk; agent reads it. kickoff_done.py injects SMM + process guide (~800 tokens) after completion. XP values injected at session start.

### M13: xp-quality-review

**Current preload:** diff of changed files + technical debt for changed files + open plan concerns
**Body:** ~1,300 tokens
**Audit:** Diff size is variable. Is full diff necessary or would stat-only + selective diff work? Are debt entries filtered efficiently?

**Acceptance criteria:**
- [ ] Diff injection strategy audited — full diff confirmed necessary or size-limited alternative implemented
- [ ] Debt entry filtering verified efficient (no stale/irrelevant debt injected)
- [ ] Body size verified appropriate (~1,300 tokens)
- [ ] Full test suite passes

### M14: xp-product-spec

**Current preload:** existing product_spec.md content or "No product spec found", feature counts
**Body:** ~1,400 tokens
**Audit:** For large product specs, this could be very large. Should it inject a summary/path instead of full content?

**Acceptance criteria:**
- [ ] Large product spec handling audited — full content confirmed appropriate or summary/path alternative implemented
- [ ] Token size measured for typical and worst-case product specs
- [ ] Full test suite passes

### M15: xp-sprint-start

**Current preload:** existing sprint.md or create mode, deferred stories, NEXT_SPRINT_ID
**Body:** ~1,500 tokens
**Audit:** Sprint.md content could be large. Are deferred stories filtered efficiently?

**Acceptance criteria:**
- [ ] Sprint.md size handling audited — confirmed bounded or size-limiting implemented
- [ ] Deferred story filtering verified efficient
- [ ] Full test suite passes

### M16: xp-accept

**Current preload:** sprint.md with in-progress stories or ERROR/NO_IN_PROGRESS flag
**Body:** ~600 tokens
**Audit:** Already lightweight. Verify only in-progress stories are loaded, not full sprint.

**Acceptance criteria:**
- [ ] Confirmed only in-progress stories loaded (not full sprint.md)
- [ ] Token size verified lightweight (~600 tokens body + preload)
- [ ] Full test suite passes

### M17: xp-smm-protocol (reference only)

**Current:** No preload. ~1,200 tokens of reference documentation.
**Audit:** Related to M8 (agent skills removal). As inline skill for main agent, verify size is appropriate. Could it be trimmed?

**Acceptance criteria:**
- [ ] Reference doc size measured (~1,200 tokens expected)
- [ ] Content verified necessary — no redundant or rarely-used sections
- [ ] Trimmed if possible, or confirmed minimal
- [ ] Full test suite passes

---

## Phase 4: Hook Injection Audits (One Per Hook Event)

Each milestone: audit what the hook injects as additionalContext, how often it fires, and whether the injection is necessary and appropriately sized.

### M18: SessionStart hooks (`session_start.py` + `retrospective.py`)

**session_start.py injections:**
- GUPP text (~40 tokens) — startup/resume/clear
- Skills list (~120 tokens) — always
- XP values (~400 tokens) — always (injected at session start for all sources)
- On compact: full SMM + sprint.md + process guide re-injection (~2,500 tokens)

**retrospective.py injections:**
- Retro summary (~200-300 tokens) — if 5+ unanalyzed events

**Audit:** Is compact re-injection of full SMM necessary? Could it inject a reference instead? Is the skills list text necessary on every session start?

**Acceptance criteria:**
- [ ] GUPP text size verified (~40 tokens) — confirmed minimal
- [ ] Skills list injection necessity evaluated — keep or remove with rationale
- [ ] Compact re-injection of full SMM evaluated — necessary (context lost) or replaceable with reference
- [ ] retrospective.py injection size verified (~200-300 tokens)
- [ ] Any changes have tests; full test suite passes

### M19: UserPromptSubmit hooks (`user_prompt_log.py` + `kickoff_gate.py` + `prompt_nugget.py`)

**user_prompt_log.py:** No injection (records only)
**kickoff_gate.py:** ~100-300 tokens when `.needs-kickoff` marker exists (one-time)
**prompt_nugget.py:** ~100 tokens max (3 events via watermark, one-time per batch)

**Audit:** Already well-deduped via markers and watermarks. Verify token sizes are minimal.

**Acceptance criteria:**
- [ ] kickoff_gate.py injection size verified (~100-300 tokens, one-time)
- [ ] prompt_nugget.py injection size verified (~100 tokens max, watermark-deduped)
- [ ] user_prompt_log.py confirmed record-only (no injection)
- [ ] Deduplication verified working (no repeat injections across prompts)
- [ ] Full test suite passes

### M20: SubagentStop hook (`subagent_stop.py`)

**Audit:** Verify this is record-only with no context injection overhead.

**Acceptance criteria:**
- [ ] Confirmed record-only — no additionalContext returned
- [ ] No unnecessary processing that could be deferred
- [ ] Full test suite passes

### M21: PostToolUse:Write hooks (`post_tool_use.py` + `lint_check.py`)

**post_tool_use.py:** Records file changes, detects conflicts. Returns None (no injection).
**lint_check.py:** Lint error output (~100-300 tokens if linter fails). No-linter nudge (~100 tokens, once per session).

**Audit:** Verify post_tool_use.py has no injection. Verify lint_check.py output sizes.

**Acceptance criteria:**
- [ ] post_tool_use.py confirmed no injection (returns None)
- [ ] lint_check.py error output size verified (~100-300 tokens when linter fails)
- [ ] No-linter nudge verified one-time per session (~100 tokens)
- [ ] Full test suite passes

### M22: PostToolUse:Bash hook (`bash_post_tool.py`)

**Current:** Advisory about other agents editing same files (~80 tokens). Test result parsing/nudges (variable).
**Audit:** How often does the advisory fire? Is the test result output sized appropriately? Fires on EVERY Bash command.

**Acceptance criteria:**
- [ ] Advisory frequency measured — how often does "other agents editing same files" fire?
- [ ] Advisory confirmed useful or removed/suppressed if noise
- [ ] Test result parsing output size verified appropriate
- [ ] Full test suite passes

### M23: PostToolUse:Skill hooks (`review_cycle_done.py` + `kickoff_done.py` + `accept_done.py` + `sprint_review_done.py`)

**review_cycle_done.py:** Text nudges (~50-150 tokens)
**kickoff_done.py:** SMM (~300-600 tokens) + PROCESS_GUIDE.md (~500 tokens) + optional sprint nudge. One-time after housekeeping. XP values already in context from session start.
**accept_done.py:** Text nudge (~30 tokens) — conditional
**sprint_review_done.py:** Text nudge (~30 tokens) + sprint end event

**Audit:** kickoff_done is the biggest but already trimmed (process guide only, ~500 tokens — values injected at session start). All 4 hooks fire on EVERY Skill completion — verify each checks skill name before injecting.

**Acceptance criteria:**
- [ ] Each PostToolUse:Skill hook verified — checks skill name before injecting (no spurious injection on unrelated skills)
- [ ] kickoff_done.py injection size measured (SMM ~300-600 + process guide ~500 tokens)
- [ ] review_cycle_done.py, accept_done.py, sprint_review_done.py injection sizes verified minimal
- [ ] Full test suite passes

### M24: PostToolUse:ExitPlanMode hook (`post_tool_exit_plan.py`)

**Audit:** Verify injection size. Fires once per plan exit.

**Acceptance criteria:**
- [ ] Injection size measured — confirmed minimal
- [ ] Verified fires only once per plan exit (not repeated)
- [ ] Full test suite passes

### M25: PreToolUse:Write hook (`pre_tool_write.py`)

**Current:** TDD reminder (~100 tokens, conditional). Plan review gate (blocks). Conflict check. Accept marker.
**Audit:** TDD reminder fires on non-code files (DEBT — fix in M31). Verify other injections are minimal.

**Acceptance criteria:**
- [ ] TDD reminder injection size verified (~100 tokens conditional)
- [ ] Plan review gate verified — blocks only, no large injection
- [ ] Conflict check verified minimal overhead
- [ ] False positive on non-code files documented (deferred to M31)
- [ ] Full test suite passes

### M26: PreToolUse:Bash hook (`pre_tool_bash.py`)

**Current:** File modification advisory (~80 tokens). Commit gate (blocks, no injection).
**Audit:** How often does the advisory fire? Is it useful or noise?

**Acceptance criteria:**
- [ ] File modification advisory frequency measured
- [ ] Advisory confirmed useful or removed/suppressed
- [ ] Commit gate verified — blocks only, no injection overhead
- [ ] Full test suite passes

### M27: Stop hooks (`tdd_stop_gate.py` + `accept_gate.py` + `session_end_warning.py`)

**tdd_stop_gate.py:** Blocks via exit 2 + stderr. No additionalContext.
**accept_gate.py:** Blocks via exit 2 + stderr. No additionalContext.
**session_end_warning.py:** Session-end checklist (~100 tokens). Every stop attempt.

**Audit:** Verify exit 2 + stderr pattern (no JSON overhead). session_end_warning may inject unnecessarily.

**Acceptance criteria:**
- [ ] tdd_stop_gate.py and accept_gate.py confirmed exit 2 + stderr (no additionalContext)
- [ ] session_end_warning.py injection evaluated — always necessary or conditional?
- [ ] Session-end checklist size verified (~100 tokens)
- [ ] Full test suite passes

### M28: Teammate hooks (`teammate_idle.py` + `task_completed.py`)

**Audit:** What do these inject? How often do they fire during agent team work?

**Acceptance criteria:**
- [ ] teammate_idle.py injection content and size documented
- [ ] task_completed.py injection content and size documented
- [ ] Firing frequency during agent team work estimated
- [ ] Confirmed appropriate or trimmed
- [ ] Full test suite passes

### M29: Other hooks (`bash_failure.py`, `session_end.py`, `pre_compact.py`)

**Audit:** Primarily record-only. Verify no context injection.

**Acceptance criteria:**
- [ ] bash_failure.py confirmed record-only (no injection)
- [ ] session_end.py confirmed record-only (no injection)
- [ ] pre_compact.py confirmed record-only (no injection)
- [ ] Full test suite passes

---

## Phase 5: Data Optimization

### M30: Sprint input JSON optimization

**Current:** `prepare_review_data.py` and `prepare_sprint_retro_data.py` embed full `sprint_md` content in JSON.
**Target:** Replace with `sprint_md_path` reference. Agents can Read if needed — structured fields already contain key data.
**Savings:** ~700-1,700 tokens per invocation
**Files:** Both prep scripts, both agent .md files, test files

**Acceptance criteria:**
- [ ] `prepare_review_data.py` uses `sprint_md_path` reference instead of embedded `sprint_md` content
- [ ] `prepare_sprint_retro_data.py` uses `sprint_md_path` reference instead of embedded `sprint_md` content
- [ ] Both agent .md files updated to Read sprint.md from path when needed
- [ ] Tests updated for new JSON schema (path instead of content)
- [ ] Token savings verified: ~700-1,700 tokens per invocation
- [ ] Full test suite passes

### M31: Fix TDD tracker false positives (debt item)

**Current:** `check_tdd_order()` treats any non-test file as implementation code. Editing product_spec.md, sprint.md, plan files triggers false nudges.
**Target:** Add `is_code_file()` check — skip TDD tracking for non-code files.
**Test (TDD):** Write failing test first — markdown write without test = no nudge; .py write without test = nudge.
**Files:** `scripts/pre_tool_write.py`, `tests/hooks/test_pre_tool_write.py`

**Acceptance criteria:**
- [ ] `is_code_file()` function implemented in `pre_tool_write.py`
- [ ] Markdown (.md) writes do not trigger TDD nudge
- [ ] Python (.py) writes without preceding test still trigger TDD nudge
- [ ] product_spec.md, sprint.md, plan files confirmed excluded
- [ ] Test written first (TDD): markdown write without test = no nudge
- [ ] Full test suite passes

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

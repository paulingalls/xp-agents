# Kickoff Redesign Plan

## Context

The xp-kickoff skill runs at session start and currently orchestrates 4-6 separate inline skills sequentially. The biggest problem: xp-housekeeping dumps ~12K+ tokens of curation JSON into the main agent context for analysis that's mostly mechanical. Additionally, question-triage, goal-collection, and story selection are separate skills that overlap in purpose and each add their own preload tokens.

**Goals:**
1. Fork housekeeping to a subagent — move ~12K tokens of curation data out of main context
2. Merge question-triage + goal-collection + story selection into one inline "work selection" skill
3. Gather ALL user interaction before housekeeping (subagents can't use AskUserQuestion)
4. Sprint-first opinionated flow — sprint IS the session goal, ad-hoc stories replace "pausing"

**New flow:**
```
1. Retrospective           (forked — if RETRO_NEEDED, unchanged)
2. Product Spec gate       (inline — if NEEDS_PRODUCT_SPEC, first time only)
3. Sprint Start gate       (inline — if NEEDS_SPRINT)
4. Work Selection          (NEW inline — all user interaction)
5. Housekeeping            (forked — zero user interaction, pure analysis)
6. kickoff_done hook       (injects SMM + behavioral guide to main agent)
```

**Estimated savings:** ~10K tokens per session from main agent context.

## Critical Files

- `skills/xp-kickoff/SKILL.md` + `scripts/check_session_needs.sh` — orchestrator
- `skills/xp-housekeeping/SKILL.md` + `scripts/` — becomes forked
- `skills/xp-question-triage/` — absorbed, then removed
- `skills/xp-goal-collection/` — absorbed, then removed
- `scripts/kickoff_done.py` — must inject SMM + guide
- `agents/xp-housekeeper.md` — new agent file
- `skills/_preload_base.sh` — shared preload helpers
- `smm/materialize.py` — `prepare_curation_data()` reused by new prep script
- `tests/hooks/test_plugin_integrity.py` — skill/agent name tuples

---

## M1: Create xp-work-selection skill

Replaces xp-question-triage + xp-goal-collection + kickoff story selection.

**Test first:** Create `tests/hooks/test_work_selection.py`
- Preload outputs SMM_DIR
- Preload outputs Try items from latest retrospective JSON
- Preload outputs open questions from events.jsonl (unanswered, not assumed)
- Preload outputs sprint status + ready story titles when sprint.md exists
- Preload outputs Intent section from SMM
- Empty state: no retro, no questions, no sprint → minimal output

**Create:** `skills/xp-work-selection/scripts/preload.sh` (~60 lines)
- Sources `_preload_base.sh`
- Section 1 — Try Items: latest retro JSON `try[]` items
- Section 2 — Open Questions: from Risks pillar in SMM
- Section 3 — Sprint Status: ready/in-progress counts + ready story titles
- Section 4 — Current Intent: Intent pillar from SMM

**Create:** `skills/xp-work-selection/SKILL.md`
- Frontmatter: `name: xp-work-selection`, `allowed-tools: [Bash(*/append.sh *), Bash(*/init.sh), Bash(*/skills/*/scripts/*), Read, AskUserQuestion]`
- Body (~600 words): three sections:
  1. **Try Item Review** — present items, ask adopt/defer/drop via AskUserQuestion, record decisions with `retro-try-<slug>` topics
  2. **Open Questions** — present questions, ask user, record answer events
  3. **Sprint / Work Selection** — if sprint active: show stories, ask which to work on, support ad-hoc story creation. If no sprint: ask "what should we work on?", record as goal event
- If nothing needs doing, report briefly and complete

**Files:** 3 created (preload.sh, SKILL.md, test file) = 3 files

---

## M2: Fork xp-housekeeping to subagent

Move from inline (~12K tokens in main context) to forked (subagent, zero user interaction).

**Test first:** Create `tests/hooks/test_housekeeping.py`
- `prepare_curation_input.py` writes `.curation-input.json` atomically
- JSON contains expected keys: current_smm, new_since_last_curation, retro_history, aging, health
- New `preload.sh` outputs `SMM_DIR=` and `CURATION_INPUT=`
- New `preload.sh` outputs behavioral guide via `dump_guide`
- SubagentStart returns None for agent_type "xp-housekeeper" (xp-* guard)

**Create:** `skills/xp-housekeeping/scripts/prepare_curation_input.py` (~40 lines)
- `--smm-dir` argument
- Calls `materialize.prepare_curation_data(smm_dir)`
- Writes to `.curation-input.json` via `_common.write_json_atomic()`
- Prints `CURATION_INPUT=<path>` to stdout

**Create:** `skills/xp-housekeeping/scripts/preload.sh` (NEW, ~15 lines)
- Sources `_preload_base.sh`
- Runs `prepare_curation_input.py --smm-dir ${SMM_DIR}`
- Outputs `SMM_DIR=`, `CURATION_INPUT=` path
- Calls `dump_guide` (behavioral guide for XP values context)

**Create:** `agents/xp-housekeeper.md` (~180 lines)
- Frontmatter: `name: xp-housekeeper`, `tools: Read, Bash`, `model: inherit`, `skills: [xp-smm-protocol]`, `color: green`
- Body: curate all five pillars — Intent, Constraints, Risks, Wisdom, Sprint (moved from current SKILL.md body)
- All "ask user" instructions replaced with: make autonomous judgment, record `question` event if uncertain
- Must include: SMM Content Trust section, append.sh reference, save_smm.py usage via `cat <<'SMMEOF' | python3 ...`

**Modify:** `skills/xp-housekeeping/SKILL.md` — convert to fork
```yaml
---
name: xp-housekeeping
description: >-
  Five-pillar SMM curation. Reads structured curation data and existing SMM,
  applies LLM judgment to curate Intent, Constraints, Risks, Wisdom, and Sprint pillars.
  Writes curated SMM and updates curation watermark.
effort: high
context: fork
agent: xp-agents:xp-housekeeper
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(cat *| python3 */save_smm.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Curate the five-pillar SMM using the preloaded curation data. Read .curation-input.json, apply judgment to curate all pillars (Intent, Constraints, Risks, Wisdom, Sprint), record resolutions, and write the updated SMM via save_smm.py.
```

**Files:** 1 test + 3 created + 1 modified = 5 files

---

## M3: Update kickoff_done.py to inject SMM + guide

Since housekeeping is now forked, the main agent never sees the curated SMM. kickoff_done.py must inject it.

**Test first:** Update `tests/hooks/test_kickoff.py`
- Existing guide injection tests: update assertions to expect SMM content prepended
- New test: write SMM file to disk, run kickoff_done, verify output contains SMM content
- New test: no SMM file → still returns behavioral guide (graceful degradation)

**Modify:** `scripts/kickoff_done.py`
- After loading `guide`, also read `smm_dir / "SHARED_MENTAL_MODEL.md"`
- If SMM exists, prepend it to the result (SMM first, then guide, then sprint nudge)
- Update comment: "Housekeeping is now forked — inject both SMM and behavioral guide"

**Files:** 1 test updated + 1 script modified = 2 files

---

## M4: Rewrite kickoff SKILL.md + check_session_needs.sh

New flow wiring: retro → gates → work-selection → housekeeping.

**Test first:** Update `tests/hooks/test_plugin_integrity.py`
- Add `"xp-work-selection"` to `_ALL_SKILL_NAMES`
- Add `"xp-housekeeper"` to `_SUBAGENT_NAMES`
- Update `test_kickoff_skill_has_sprint_steps`: check for "Work Selection" and "Housekeeping" steps
- Update/remove `test_kickoff_skill_backward_compat` (no longer references xp-goal-collection)

**Modify:** `skills/xp-kickoff/scripts/check_session_needs.sh`
- Keep: RETRO_NEEDED, NEEDS_PRODUCT_SPEC, NEEDS_SPRINT, SPRINT_ACTIVE checks
- Remove: GOALS_REVIEW section, QUESTIONS_CHECK section, HOUSEKEEPING section
- Result: ~50 lines instead of ~105

**Modify:** `skills/xp-kickoff/SKILL.md` — new 5-step flow:
1. Retrospective (if RETRO_NEEDED — forked, unchanged)
2. Product Spec (if NEEDS_PRODUCT_SPEC — inline, unchanged)
3. Sprint Start (if NEEDS_SPRINT — inline, unchanged)
4. Work Selection — invoke `/xp-work-selection` (all user interaction)
5. Housekeeping — invoke `/xp-housekeeping` (forked, no user interaction)
6. Complete — if stories selected, plan mode. Otherwise begin working.

Remove ToolSearch instruction (no longer needed). Remove the "If no SPRINT_ACTIVE" branch.

**Files:** 1 test updated + 2 production modified = 3 files

---

## M5: Remove obsolete skills + cleanup

**Test first:** Update `tests/hooks/test_plugin_integrity.py`
- Remove `"xp-question-triage"` and `"xp-goal-collection"` from `_ALL_SKILL_NAMES`

**Remove:**
- `skills/xp-question-triage/` — entire directory
- `skills/xp-goal-collection/` — entire directory
- `skills/xp-housekeeping/scripts/prepare_curation_preload.sh` — replaced by new preload.sh
- `skills/xp-housekeeping/scripts/check_open_items.sh` — legacy, unused

**Files:** 1 test updated + deletions

---

## Implementation Order

```
M1 (work-selection) ───────┐
                            ├── M4 (kickoff rewrite) ── M5 (cleanup)
M2 (fork housekeeping) ────┤
                            │
M3 (kickoff_done SMM) ─────┘
         (depends on M2)
```

- M1 and M2 are independent — do M1 first (simpler, validates the merged skill pattern)
- M3 depends on M2 (needs forked housekeeping to exist)
- M4 depends on M1 + M3 (wires everything together)
- M5 depends on M4 (safe to remove only after new flow works)

## Verification

After all milestones:
1. Run full test suite: `python3 -m unittest discover -s plugins/xp-agents/tests -p "test_*.py" -v`
2. Test a full session: start claude with `--plugin-dir`, run `/xp-kickoff`, verify:
   - Retrospective runs if retro data exists
   - Work selection presents Try items + questions + stories
   - Housekeeping runs as forked agent (check for subagent spawn in output)
   - Main agent receives SMM + behavioral guide after completion
   - No curation JSON visible in main agent context

## Notes

- **SubagentStart for xp-housekeeper:** No dispatch entry needed. The `is_xp_agent()` guard returns None for all xp-* agents not in `_DISPATCH`. The preload provides everything.
- **Token optimization plan:** M10-M13 and parts of M25 in `docs/token-optimization.md` are superseded by this redesign. Add a note there after implementation.
- **xp-smm-protocol in agents:** The new xp-housekeeping agent should include `skills: [xp-smm-protocol]` per the existing agent integrity test pattern. This will be removed later by token optimization M8.

# Sprint-062 candidate: workflow plumbing fixes

**Plugin:** `xp-agents`
**Origin:** sprint-061 retrospective discussion (2026-05-04). Four friction points surfaced during the parallel-teammate close cycle.
**Status:** Draft — feed into next `/xp-sprint-start` planning.

## Why this sprint

Sprint-061 shipped 6/6 stories via 5 parallel teammates, but the close cycle had measurable friction:

1. **Worktree commit pattern broke `Resolves-Event:` auto-link.** The `cd $WT && git commit ... && cd -` shape caused the trailer-extract hook to read the orchestrator's HEAD (cd'd back) instead of the worktree's HEAD where the commit landed. Every concern that should have been auto-resolved by trailer had to be manually `triage-drop`'d. Memory `feedback_cd_persists_in_bash.md` documented this trap previously and the agent still hit it — the doctrine isn't enforced anywhere.

2. **Story-004 reported "0 bare RHS" but had missed 40 sites.** AC1 was "grep returns zero matches" but the teammate didn't actually run the grep. The orchestrator's `acceptance_execution.command` was `pytest` only, so the gate passed pytest while AC1 was unverified. The close-reviewer caught it via independent grep, costing a full fix-cycle.

3. **`/xp-accept`'s preload only sees `in-progress` stories,** but teammates self-promote to `reviewing` before exiting. After the first /xp-accept, the preload listed only the still-running teammates, silently excluding the reviewing-batch ready for the orchestrator. Workaround: manually process reviewing stories outside the preload's scope.

4. **`.accept` marker re-arm whack-a-mole.** Multiple times `pre_tool_bash` blocked `update-story done` with "Run /xp-accept first" even mid-flow. Re-invoking /xp-accept against `NO_IN_PROGRESS` just to satisfy the marker gate was clunky.

The 4 stories below address the underlying causes, not the symptoms. All dep-free, parallelizable.

---

## Story-001 — Multi-command `acceptance_execution` schema + teammate `verify-my-acs` CLI

**Mode:** TDD (schema validation + new CLI)
**Dependencies:** none
**Why:** Story-004 of sprint-061 lied about AC1 because the gate command (pytest) didn't cover the AC's grep. Schema currently allows only `acceptance_execution.command: str` — one verification per story. Real stories have multiple ACs with different verification commands.

### File domain

- `plugins/xp-agents/smm/sprint_cli.py` — extend schema validation to accept `acceptance_execution.commands: list[str]` (keep `command: str` as back-compat alias)
- `plugins/xp-agents/smm/sprint_store.py` — schema definition update if separate from CLI
- `plugins/xp-agents/scripts/verify_acceptance.py` — NEW CLI that reads a story, runs all acceptance commands, exits non-zero on first red
- `plugins/xp-agents/TEAMMATE_GUIDE.md` — add "Before flipping to `reviewing`, run `verify_acceptance.py --story <id>`" section
- `plugins/xp-agents/tests/smm/test_sprint_schema_acceptance.py` — NEW (schema validation tests)
- `plugins/xp-agents/tests/hooks/test_verify_acceptance.py` — NEW (CLI tests)

### Acceptance criteria

- Given a sprint.json story with `acceptance_execution.commands: [cmd1, cmd2, cmd3]`, when `sprint_cli.py validate` runs, then it accepts the schema; back-compat: `command: str` continues to validate
- Given a story with multiple commands and one returns non-zero, when `verify_acceptance.py --story X` runs, then it exits non-zero AND names the failing command in stderr
- Given a story with all green commands, when `verify_acceptance.py --story X` runs, then it exits 0
- Given TEAMMATE_GUIDE.md, when grep'd, then it mentions `verify_acceptance.py` and the "before flipping to reviewing" timing
- E2E: Given a synthetic sprint with a 3-command story (one grep + pytest + bash), when verify_acceptance runs against it, then exit code matches the union of the three commands' results

### Acceptance execution (uses the new schema!)

```json
{"commands": [
  "pytest -n auto plugins/xp-agents/tests/smm/test_sprint_schema_acceptance.py plugins/xp-agents/tests/hooks/test_verify_acceptance.py",
  "grep -q 'verify_acceptance.py' plugins/xp-agents/TEAMMATE_GUIDE.md"
]}
```

---

## Story-002 — PreToolUse:Bash warning for `cd <worktree> && git` pattern

**Mode:** TDD (extend existing hook)
**Dependencies:** none
**Why:** Catches the `cd && commit && cd -` pattern at the moment the agent uses it, not after-the-fact in retro. The agent has explicit memory feedback flagging this trap and still hit it ~10 times in sprint-061. Fail-fast hook beats memory for this kind of muscle-memory mistake.

### File domain

- `plugins/xp-agents/scripts/pre_tool_bash.py` — add regex detection for `cd .*\.claude/worktrees/.*\s*&&\s*git\s+(commit|add|merge|push)` and emit an `additionalContext` warning suggesting `git -C <path>`
- `plugins/xp-agents/tests/hooks/test_pre_tool_bash_worktree_warn.py` — NEW (test the matcher + warning text)

### Acceptance criteria

- Given a Bash tool input `cd .claude/worktrees/worktree-story-001 && git commit ...`, when pre_tool_bash runs, then stdout includes `hookSpecificOutput.additionalContext` with text mentioning `git -C` and naming the trailer-extract impact
- Given a Bash tool input `git -C .claude/worktrees/worktree-story-001 commit ...`, when pre_tool_bash runs, then NO warning is emitted
- Given a Bash tool input `cd /tmp/something && git commit ...` (non-worktree path), when pre_tool_bash runs, then NO warning is emitted (only the worktree path triggers)
- Given the warning fires, when the agent reads the additionalContext, then it can see why and what to do instead
- E2E: Given full hook pipeline run with the offending pattern, when the bash command would execute, then the warning appears in additionalContext and the command is NOT blocked (warn-only, not gate)

### Acceptance execution

```json
{"command": "pytest -n auto plugins/xp-agents/tests/hooks/test_pre_tool_bash_worktree_warn.py"}
```

---

## Story-003 — Trailer-extract hook becomes worktree-aware

**Mode:** TDD (modify existing hook)
**Dependencies:** none
**Why:** Even with story-002's warning, agents will sometimes commit in worktrees via subprocess flows that don't match the simple `cd && git` pattern. The underlying hook should resolve HEAD from the right git directory regardless of how the bash command was structured. Fixes the bug at the source.

### File domain

- `plugins/xp-agents/scripts/<trailer-extract-hook-name>.py` — find the script that handles `Resolves-Event:` extraction (likely `bash_commit.py` or related — investigation is part of this story); modify it to parse the bash command text for `cd <path>` / `git -C <path>` segments and use that path as the working dir for `git rev-parse HEAD` instead of the orchestrator's cwd
- `plugins/xp-agents/tests/hooks/test_<that-test>.py` — NEW or extend existing tests covering three patterns: bare `git commit`, `cd <path> && git commit`, `git -C <path> commit`

### Acceptance criteria

- Given a bash command `cd .claude/worktrees/worktree-X && git commit -m "msg with Resolves-Event: abc123def456"` followed by cd-back, when the trailer hook runs, then it extracts `abc123def456` AND records the resolution event with the correct commit SHA from the worktree
- Given a bash command `git -C .claude/worktrees/worktree-X commit -m "...Resolves-Event: abc123def456"`, when the trailer hook runs, then it correctly resolves HEAD from the `-C` path and records the resolution
- Given a bare `git commit -m "...Resolves-Event: abc123def456"` (no worktree), when the trailer hook runs, then existing behavior preserved (uses cwd HEAD)
- E2E: Given a fresh git worktree + a commit there with a Resolves-Event trailer that references an existing concern, when the bash command runs end-to-end through the hook, then the concern's resolution event appears in events.jsonl with the correct commit SHA in metadata

### Acceptance execution

```json
{"command": "pytest -n auto plugins/xp-agents/tests/hooks/test_<trailer-extract>.py"}
```

---

## Story-004 — Doctrine: `git -C` guidance in close-skill + TEAMMATE_GUIDE

**Mode:** doc edit (no TDD; pin tests verify presence)
**Dependencies:** none
**Why:** Belt-and-suspenders for stories 002 and 003. Even with the warning hook and worktree-aware extractor, the doctrine should explicitly tell agents the right pattern. This is the cheapest of the four — bundle into another story's commit if you'd rather keep the sprint at 3.

### File domain

- `plugins/xp-agents/skills/xp-story-close/SKILL.md` — add to Step 5c (fix-cycle classify): "When fixing in a teammate worktree, use `git -C ${TEAMMATE_CWD} commit ...` — never `cd ${TEAMMATE_CWD} && commit && cd -` (breaks Resolves-Event auto-link by losing cwd context before hook fires)"
- `plugins/xp-agents/skills/xp-accept/SKILL.md` — same note, in the manual debug-and-rerun branch
- `plugins/xp-agents/TEAMMATE_GUIDE.md` — short bullet under "Workflow" or similar
- `plugins/xp-agents/tests/hooks/test_plugin_integrity.py` — extend existing token-budget test or add `test_close_skills_mention_git_dash_C` pin test

### Acceptance criteria

- Given xp-story-close SKILL.md, when grep'd, then `git -C` appears with cwd-context rationale
- Given xp-accept SKILL.md, when grep'd, then `git -C` appears in the debug-and-rerun branch
- Given TEAMMATE_GUIDE.md, when grep'd, then `git -C` appears once
- Given test_plugin_integrity.py, when pytest runs it, then a new `test_close_skills_have_git_dash_C_guidance` test passes asserting the three documents include the directive
- Token budgets: PROCESS_GUIDE/TEAMMATE_GUIDE token-budget tests still pass after the additions (TEAMMATE_GUIDE has 1500-token cap currently — verify headroom)
- E2E: Given pytest runs the integrity tests, then all assertions pass

### Acceptance execution

```json
{"command": "pytest -n auto plugins/xp-agents/tests/hooks/test_plugin_integrity.py"}
```

---

## Sequencing notes

- All 4 are dep-free (no story blocks another). Parallelizable across 4 teammates.
- Story-001 is the conceptual anchor — once `commands: []` lands, every future sprint can write more rigorous ACs. Other 3 stories don't need to wait.
- Story-004 (doctrine) is XS — could fold into another story's commit if you'd rather keep the sprint at 3 stories.
- Story-001 + Story-003 are both M; together they're the bulk of the sprint. Story-002 + 004 are S/XS.

## Out of scope (deferred to follow-up)

These came up during sprint-061 but don't fit this sprint's "workflow plumbing" theme:

- **Sprint-061 deferred Try:** Audit close-skill probe nudge ergonomics (sprint-060 had 2/2 escapes; sprint-061 dynamics still being measured).
- **Security-review nudge architecture** (concern `ecc527295e8a`): Stop-gate marker design discussion still open. User wanted to think more before committing to a design.
- **Existing technical debt from sprint-061** (5 items): `_assert_not_none` helper, `_LintTmpDirMixin` typed base, `check_tdd_order` signature widen, pyrightconfig drift-guard, `INTENT_TYPE_*` constants, `_events_of_type` helper. Pure refactor work — fits a separate "test-suite ergonomics" sprint.

## Provenance

- Discussion captured in session 2026-05-04, after sprint-061 close.
- All 4 stories drafted by main agent; user requested save to `docs/ideas/` for next planning cycle.
- Reuses sprint-061's Story-006 pattern of bundling small doc + test edits + CLI work in one story when scope allows.

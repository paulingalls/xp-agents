# v2 Manual Test Plan — Sprint Lifecycle + Agent Teams

## Prerequisites

1. Have a **separate git repo** (not the xp-agents repo) to use as the test project
2. Launch Claude Code with the plugin loaded:
   ```bash
   cd /path/to/test-project
   claude --plugin-dir /path/to/xp-agents/plugins/xp-agents
   ```
3. For Agent Teams tests (Tests 10-13), set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`

---

## Phase 1: Solo Enforcement (v1.5 baseline)

### Test 1: Session Start + Kickoff Gate

**Verify:** fresh session creates markers and blocks until kickoff runs.

1. Launch `claude` in the test project
2. **Expect:** GUPP nudge — "Run /xp-kickoff before doing anything else"
3. Try typing a regular prompt (e.g., "create a hello world script")
4. **Expect:** blocked by `kickoff_gate.py` — "Run /xp-kickoff first"
5. Run `/xp-kickoff` and complete it
6. **Expect:** `.needs-kickoff` marker consumed, BEHAVIORAL_GUIDE injected
7. **Verify:** you can now work normally

### Test 2: Small Commit — Security-Only Gate (< 3 code files)

**Verify:** below-threshold commits only require security triage.

1. Create a single source file (e.g., `hello.py`) and `git add` it
2. Try to commit
3. **Expect:** blocked — "Run /xp-security-triage before committing"
4. Run `/xp-security-triage`
5. Commit succeeds

### Test 3: Large Commit — Full Review Cycle (3+ code files)

**Verify:** sequential gate chain: simplify → quality review → security triage.

1. Create or modify 3+ code files, `git add` them
2. Try to commit — **Expect:** blocked for `/simplify`
3. Run `/simplify` — Try commit — **Expect:** blocked for `/xp-quality-review`
4. Run `/xp-quality-review` — Try commit — **Expect:** blocked for `/xp-security-triage`
5. Run `/xp-security-triage` — Commit succeeds

### Test 4: Plan Mode + Plan Review Gate

**Verify:** plan review blocks writes after plan mode.

1. Enter plan mode (`EnterPlanMode`)
2. Create a plan, exit plan mode
3. Try to write a file — **Expect:** blocked — "Run /xp-review-plan first"
4. Run `/xp-review-plan`
5. File writes now work

### Test 5: TDD Stop Gate

**Verify:** can't stop with failing tests.

1. Write a test that fails, run it
2. Try to stop (Ctrl+C or let Claude finish) — **Expect:** blocked — "Tests are failing"
3. Fix the test, run it green
4. Stop succeeds

---

## Phase 2: Sprint Lifecycle (v2 new)

### Test 6: Product Spec Creation

**Verify:** `/xp-product-spec` creates `product_spec.md` in SMM directory.

1. Run `/xp-product-spec`
2. Describe a small project (e.g., "REST API for todo items with CRUD endpoints")
3. **Expect:** interactive decomposition into features with acceptance criteria
4. **Verify:** `product_spec.md` exists in SMM directory with features listed

### Test 7: Sprint Start

**Verify:** `/xp-sprint-start` creates `sprint.md` from product spec stories.

1. Run `/xp-sprint-start`
2. Select stories for the sprint, assign T-shirt sizes
3. **Expect:** `sprint.md` created in SMM directory with stories, sizes, statuses
4. **Verify:** stories have status `ready`, sprint has an ID

### Test 8: Sprint Review

**Verify:** `/xp-sprint-review` records velocity and updates product spec.

1. Complete some stories (mark as `done` in sprint.md) and leave one as `deferred`
2. Run `/xp-sprint-review`
3. **Expect:** subagent analyzes what shipped vs planned
4. **Verify:** sprint end event recorded with velocity (stories_planned, delivered, carried)
5. **Verify:** product_spec.md updated with delivery markers

### Test 9: Sprint Retrospective

**Verify:** `/xp-sprint-retro` analyzes patterns across session retros.

1. Ensure at least one session retrospective exists in `retrospectives/`
2. Run `/xp-sprint-retro`
3. **Expect:** subagent produces sprint-level Keep/Fix/Try
4. **Verify:** retrospective saved to `retrospectives/` directory

---

## Phase 3: Agent Teams (v2 new)

### Test 10: Teammate Detection + Guide Injection

**Verify:** SubagentStart detects teammates and injects TEAMMATE_GUIDE.md.

1. Create a plan with parallelizable work
2. Run `/xp-spawn-team`
3. **Expect:** subagent analyzes plan, produces spawn instructions with:
   - Team size recommendation
   - Task descriptions with file domains
   - Worktree decision
   - Spawn prompt template
4. Spawn a teammate using the instructions (use a custom agent_type name)
5. **Verify:** teammate receives TEAMMATE_GUIDE.md (DO/DON'T/SKIP/KEEP), NOT BEHAVIORAL_GUIDE.md
6. **Verify:** teammate receives curated SMM

### Test 11: Teammate TDD Gates

**Verify:** TeammateIdle and TaskCompleted enforce TDD.

1. With a running teammate, have it write a failing test
2. Try to go idle — **Expect:** blocked — "Tests are failing"
3. Try to complete a task — **Expect:** blocked — "Tests are failing"
4. Fix the test, run it green
5. Idle and task completion now succeed

### Test 12: Non-Teammate Tiers Unaffected

**Verify:** built-in agent types still get solo behavioral guide.

1. Spawn an Explore agent — **Verify:** gets Intent+Constraints only (no guide)
2. Spawn a Plan agent — **Verify:** gets full SMM + BEHAVIORAL_GUIDE.md (not teammate guide)
3. Spawn a general-purpose agent — **Verify:** gets full SMM + BEHAVIORAL_GUIDE.md

### Test 13: Spawn Team Analysis

**Verify:** `/xp-spawn-team` handles edge cases.

1. Run `/xp-spawn-team` with no sprint — **Expect:** error — "No sprint data available"
2. Run `/xp-spawn-team` with no plan — **Expect:** error — "No plan available"
3. Run `/xp-spawn-team` with all stories done — **Expect:** "Nothing to spawn a team for"
4. Run `/xp-spawn-team` with a single story — **Expect:** "Solo execution is more efficient"
5. Run `/xp-spawn-team` with a plan that has parallelizable work — **Expect:** structured spawn instructions

---

## Phase 4: Cross-Cutting Concerns

### Test 14: Context Injection Tiers

**Verify:** tiered SubagentStart injection is correct for all agent types.

| Agent Type | Expected Injection |
|---|---|
| `Explore` | Intent + Constraints only (~200 tokens) |
| `Plan` | Full SMM + BEHAVIORAL_GUIDE.md |
| `general-purpose` | Full SMM + BEHAVIORAL_GUIDE.md |
| `xp-plan-reviewer` | Full SMM + BEHAVIORAL_GUIDE.md + sprint.md |
| `xp-retrospective` | Full SMM + BEHAVIORAL_GUIDE.md + sprint.md |
| Custom type (teammate) | SMM + TEAMMATE_GUIDE.md (no sprint stories) |
| `xp-security-reviewer` | Skipped (uses own preload) |

### Test 15: Retrospective at Session Start

**Verify:** retro runs at start of next session after work.

1. Complete a work session with commits
2. Start a new session, run `/xp-kickoff`
3. **Expect:** retrospective runs with Keep/Fix/Try analysis
4. **Verify:** retrospective saved to `retrospectives/`

### Test 16: Housekeeping Curation

**Verify:** four-pillar SMM is curated correctly.

1. During kickoff, complete housekeeping step
2. **Verify:** `SHARED_MENTAL_MODEL.md` has all four pillars (Intent, Constraints, Risks, Wisdom)
3. **Verify:** completed goals removed (except most recent with ✅ prefix)
4. **Verify:** resolved concerns removed from Risks
5. **Verify:** new decisions appear in Constraints (if they're architectural boundaries)

### Test 17: Session End Warning

**Verify:** Stop hook warns about unresolved concerns.

1. Create an unresolved concern during the session
2. Try to stop — **Expect:** soft warning mentioning unresolved concern count
3. **Verify:** warning is advisory (not a hard block)

---

## Automated Test Coverage

All features above have automated unit and integration tests:

```bash
# Run everything (1334 tests):
python3 -m unittest discover -s plugins/xp-agents/tests -p "test_*.py" -v

# By suite:
python3 -m unittest discover -s plugins/xp-agents/tests/hooks -p "test_*.py" -v       # 881 tests
python3 -m unittest discover -s plugins/xp-agents/tests/integration -p "test_*.py" -v  # 103 tests
python3 -m unittest discover -s plugins/xp-agents/tests/engine -p "test_*.py" -v       # 211 tests
python3 -m unittest discover -s plugins/xp-agents/tests/smm -p "test_*.py" -v          # 139 tests
```

The manual tests above validate end-to-end behavior that automated tests can't cover: actual LLM responses, user interaction flows, and multi-session state.

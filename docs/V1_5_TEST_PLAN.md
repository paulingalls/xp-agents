# v1.5 Manual Test Plan — Fresh Project

## Prerequisites

1. Have a **separate git repo** (not the xp-agents repo) to use as the test project
2. Launch Claude Code in that project with the plugin loaded locally:
   ```bash
   cd /path/to/test-project
   claude --plugin-dir /path/to/xp-agents/plugins/xp-agents
   ```
   This loads the plugin for that session only — no global installation needed. Use `/reload-plugins` inside the session if you make changes to the plugin source.

---

## Test 1: Session Start + Kickoff Gate

**Verify:** fresh session creates markers and blocks until kickoff runs.

1. Launch `claude` in the test project
2. **Expect:** the GUPP nudge — "Run /xp-kickoff before doing anything else"
3. Try typing a regular prompt (e.g., "create a hello world script")
4. **Expect:** blocked by `kickoff_gate.py` — "Run /xp-kickoff first"
5. Run `/xp-kickoff` and complete it
6. **Expect:** `.needs-kickoff` marker consumed, BEHAVIORAL_GUIDE injected, you can now work normally
7. **Verify marker:** `ls .claude/smm/.needs-kickoff` should not exist after kickoff

---

## Test 2: Small Commit — Security-Only Gate (< 3 code files)

**Verify:** below-threshold commits only require security triage.

1. Create a single source file (e.g., `hello.py`) and `git add` it
2. Try to commit: `git commit -m "add hello"`
3. **Expect:** blocked — "Run /xp-security-triage before committing"
4. Run `/xp-security-triage`
5. Try the commit again
6. **Expect:** commit succeeds
7. **Verify:** after the commit, the review cycle marker resets (all flags back to false)

---

## Test 3: Large Commit — Full Review Cycle (3+ code files)

**Verify:** the sequential gate chain: simplify → quality review → security triage.

1. Create or modify 3+ code files, `git add` them
2. Try to commit
3. **Expect:** blocked — "Run /simplify before committing — N code files changed"
4. Run `/simplify`
5. Try to commit again
6. **Expect:** blocked — "Run /xp-quality-review before committing"
7. Run `/xp-quality-review`
8. Try to commit again
9. **Expect:** blocked — "Run /xp-security-triage before committing"
10. Run `/xp-security-triage`
11. Try to commit again
12. **Expect:** commit succeeds

---

## Test 4: Non-Code Commit Bypass

**Verify:** test-only or docs-only commits skip the gate.

1. Create/modify only a test file or a `.md` file
2. `git add` and commit
3. **Expect:** commit goes through without any review cycle blocks (the `is_code_file()` heuristic classifies these as non-production code)

---

## Test 5: Review Cycle Reset After Commit

**Verify:** the cycle resets so the next commit requires reviews again.

1. After a successful commit from Test 2 or 3, modify another code file
2. `git add` and try to commit
3. **Expect:** blocked again (flags were reset by `bash_post_tool.py` post-commit)

---

## Test 6: TDD Stop Gate Still Works

**Verify:** M3 kept the TDD stop gate even though simplify/quality gates were removed from Stop.

1. Write a test that fails, run it
2. Try to stop the session (Ctrl+C or `/stop`)
3. **Expect:** blocked — "Tests are failing, fix before stopping"
4. Fix the test, run it green
5. Stop should now be allowed

---

## Test 7: Verify Removed Gates

**Verify:** M3 removals — no Stop-time simplify/quality blocks.

1. Work normally, make code changes, do NOT run `/simplify`
2. Try to stop the session
3. **Expect:** NOT blocked for missing simplify/quality review (only TDD matters at Stop now)
4. The simplify/quality enforcement only happens at commit time (Test 3)

---

## Quick Smoke Check (if short on time)

Run Tests 1, 3, and 5 — they cover the critical path: kickoff gate → full review cycle → reset.

---

## What to Watch For

- **Marker files** live in the SMM dir (check with `ls .claude/smm/.review-cycle-*.json`)
- **Events** are appended to `.claude/smm/events.jsonl` — you can `tail` this to see status/concern events being recorded after commits
- If the commit gate doesn't fire, check that `git commit` is being run through the Bash tool (not a direct terminal command outside Claude)

---

## Results Log

| Test | Date | Pass/Fail | Notes |
|------|------|-----------|-------|
| 1    |      |           |       |
| 2    |      |           |       |
| 3    |      |           |       |
| 4    |      |           |       |
| 5    |      |           |       |
| 6    |      |           |       |
| 7    |      |           |       |

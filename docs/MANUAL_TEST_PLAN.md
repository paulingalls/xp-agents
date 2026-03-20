# Manual Test Plan (v0.9.54)

Hands-on acceptance tests for the xp-agents plugin. Organized by workflow. Each test has **Do** and **Verify** steps.

## Prerequisites

- Python 3.10+ on PATH
- Claude Code CLI installed
- macOS or Linux
- A test git repository (can be empty)

## Setup

Install the plugin:

```bash
cd /path/to/test-project
git init && git commit --allow-empty -m "init"
claude plugin add /path/to/plugins/xp-agents --scope user
```

---

## Part 1: New Project (Cold Start)

### 1.1 Installation

**Do:** Verify the plugin installed correctly.

```bash
claude plugin list
```

**Verify:**
- `xp-agents` appears with version `0.9.54`
- No errors during installation

---

### 1.2 First Session — SMM Init + Kickoff Gate

**Do:** Start a new session:

```bash
claude
```

Then type any prompt (e.g., "hello").

**Verify:**
- SMM directory created at `${CLAUDE_PLUGIN_DATA}/xp-agents-xp-agents/{project-id}/smm/`
- `events.jsonl` and `events.lock` exist
- `retrospectives/` directory exists
- Your prompt is **blocked** with a message to run `/xp-kickoff`

---

### 1.3 Kickoff — Goal Collection

**Do:** Run `/xp-kickoff`. When asked for goals, respond with:

```
Build a simple TODO app with a REST API
```

**Verify:**
- Kickoff sequences through: goals (no retro on first session)
- `events.jsonl` contains a `goal` event with the project description
- `events.jsonl` contains `customer_input` events from your prompts
- Housekeeping runs and writes `SHARED_MENTAL_MODEL.md`
- After housekeeping, the behavioral guide is injected (check context for XP values)
- Subsequent prompts are no longer blocked

---

### 1.4 User Prompt Logging

**Do:** Type a prompt:

```
Let's start by creating the data models
```

**Verify:**
- `events.jsonl` contains a `customer_input` event with `agent_id: "customer"` and your prompt text

---

### 1.5 File Write — Auto Status + Lint

**Do:** Ask Claude to create a file:

```
Create a file called todo.py with a Todo dataclass that has id, title, and done fields
```

**Verify after the write completes:**
- `events.jsonl` contains a `status` event with `working_on` including `todo.py`
- If the project has a linter config (e.g., `ruff.toml`), a lint check runs and errors appear as context

---

### 1.6 TDD Order Check

**Do:** Ask Claude to write implementation code without tests first:

```
Add a function to todo.py that filters todos by completion status
```

**Verify:**
- PreToolUse fires for the Write — check if TDD ordering context is injected
- The agent should write tests before or alongside implementation

---

### 1.7 Test Writing and Execution

**Do:** Ask Claude to write and run tests:

```
Write tests for the Todo dataclass and the filter function, then run them
```

**Verify:**
- Test file created (e.g., `test_todo.py`)
- Tests execute via Bash
- `events.jsonl` contains status events reflecting test results
- If tests pass: status event with pass count
- If tests fail: concern event with failure details

---

### 1.8 Git Commit — Security Triage Gate

**Do:** Stage and try to commit:

```
Stage and commit the todo.py and test_todo.py files
```

**Verify:**
- The `git commit` command is **blocked** with a message to run `/xp-security-triage`
- After Claude runs `/xp-security-triage`:
  - For trivial changes (dataclass + tests): auto-cleared, `.security-triaged` marker written
  - Commit proceeds on retry
- `events.jsonl` may contain a draft `decision` event from the commit message
- If commit has >10 files: a concern event warns about commit size

---

### 1.9 Plan Review

**Do:** Ask Claude to plan a larger feature:

```
Plan the REST API endpoints for CRUD operations on the TODO list
```

**Verify:**
- Claude creates a plan (Plan subagent)
- `SubagentStop` fires → `.plan-awaiting-review` marker written
- On next Write/Edit: PreToolUse nudges "Run /xp-review-plan"
- Plan reviewer checks: plan size, TDD ordering, decision conflicts
- Plan reviewer may write `assumption`, `question`, and/or `decision` events
- If questions recorded: they appear first in the reviewer's output

---

### 1.10 Simplify Gate

**Do:** Make changes to 3+ code files, then try to stop the session.

**Verify:**
- Stop is **blocked** with "Run `/simplify`..."
- After running `/simplify`: three review agents launch (reuse, quality, efficiency)
- On next stop attempt: simplify gate clears
- `.simplify-main.json` tracker file exists with the current loop ID

---

### 1.11 Quality Review Gate

**Do:** After `/simplify` completes and its subagents finish, try to stop again.

**Verify:**
- Stop is **blocked** with "Run `/xp-quality-review`..."
- After running `/xp-quality-review`: gate clears
- Review covers courage accountability, drift management, debt awareness

---

### 1.12 TDD Stop Gate

**Do:** Introduce a test failure, then try to stop:

```
Break one of the test assertions, run the tests, then try to stop
```

**Verify:**
- Tests fail → concern event recorded
- Stop is **blocked** with "Fix failing tests..."
- Fix the test, run again → pass status recorded
- Stop is now allowed

---

### 1.13 Session End

**Do:** End the session (Ctrl+C or `/exit`).

**Verify:**
- `events.jsonl` contains a `session_end` event with duration, event count, and unresolved items

---

### 1.14 Desktop Notifications

**Do:** Record a blocking question:

```bash
# From another terminal, append directly for testing:
plugins/xp-agents/smm/append.sh \
  --type "question" \
  --agent "test" \
  --content "Which database should we use?" \
  --priority "🔴"
```

**Verify (macOS):**
- A desktop notification appears for the blocking question
- The notification mentions "xp-agents"

---

## Part 2: Existing Project (Multi-Session)

### 2.1 Install into Existing Project

**Do:** Install the plugin into an existing project with code and git history.

**Verify:**
- SMM initializes without affecting existing project files
- SMM directory created at plugin data level, not inside the project
- Claude asks for project goals (via `/xp-kickoff` → `/xp-goal-collection`)
- No interference with existing git state

---

### 2.2 Lint Integration

**Do:** Modify a file in a project that has a linter configured (ruff, eslint, flake8, etc.).

**Verify:**
- After the write, `lint_check.py` detects the linter config
- Lint errors appear immediately as context (additionalContext)
- Concern events are appended for lint violations
- If no linter configured: a one-time note, no errors

---

### 2.3 Working-On Conflict Detection

**Do:** Simulate two agents working on the same file. In the SMM directory:

```bash
# Manually create overlapping coordination entries
python3 -c "
import json
coord = {'agent-1': {'working_on': ['src/app.py']}, 'agent-2': {'working_on': ['src/app.py']}}
with open('.coordination.json', 'w') as f: json.dump(coord, f)
"
```

Then have Claude try to write to `src/app.py`.

**Verify:**
- PreToolUse detects the conflict
- Write is blocked with a conflict message
- A concern event is appended to the log

---

### 2.4 Retrospective (Second Session)

**Do:** End the first session, then start a new one:

```bash
claude  # starts new session
```

**Verify:**
- `retrospective.py` detects unanalyzed events and writes `.retro-input.json`
- `/xp-kickoff` sequences retrospective first (if enough events)
- Retrospective output includes:
  - **Keep**: things that went well, with event references
  - **Fix**: issues identified, tagged with XP values
  - **Try**: actionable experiments for next session
- A retrospective file is written to `$SMM_DIR/retrospectives/`
- `events.jsonl` contains a `retrospective` event

---

### 2.5 Question Triage (Kickoff)

**Do:** Before starting a new session, seed some questions:

```bash
plugins/xp-agents/smm/append.sh \
  --type "question" \
  --agent "xp-plan-reviewer" \
  --content "Should we use PostgreSQL or SQLite? Assuming PostgreSQL." \
  --priority "🟡"
```

Then start a session and run `/xp-kickoff`.

**Verify:**
- `check_session_needs.sh` detects "QUESTIONS_NEEDED" in the Risks pillar
- `/xp-question-triage` runs as step 3 of kickoff (between goals and housekeeping)
- Open questions are presented to the user via `AskUserQuestion`
- Answers are recorded as events

---

### 2.6 Technical Debt Aging

**Do:** Create a debt event, then simulate multiple sessions:

```bash
plugins/xp-agents/smm/append.sh \
  --type "debt" \
  --agent "main" \
  --content "Legacy string error matching in auth module" \
  --files '["src/auth/legacy.ts"]'
```

Simulate session ends:

```bash
for i in $(seq 1 7); do
  plugins/xp-agents/smm/append.sh \
    --type "session_end" \
    --agent "main" \
    --content "Session $i ended" \
    --working-on '[]'
done
```

Then start a new session and check the materialized view.

**Verify:**
- Debt at 0-3 sessions appears normally
- Debt at 4-6 sessions appears with a warning indicator
- Debt at 7+ sessions appears with a critical indicator
- The retrospective escalates aging debt in Fix items

---

### 2.7 Subagent Context Injection

**Do:** Ask Claude to use a subagent (e.g., create a Plan, or search with Explore).

**Verify for Explore subagent:**
- `subagent_start.py` fires
- Context includes Intent + Constraints pillars only (~200 tokens)
- Does NOT include full SMM or behavioral guide

**Verify for Plan/general-purpose subagent:**
- Context includes full curated SMM + behavioral guide (~1000 tokens)

**Verify for xp-* subagent:**
- `subagent_start.py` skips injection (recursion prevention)

---

### 2.8 Prompt Nuggets

**Do:** Record a new decision event from a separate terminal while a session is active:

```bash
plugins/xp-agents/smm/append.sh \
  --type "decision" \
  --agent "main" \
  --content "Using PostgreSQL for user data" \
  --topic "database"
```

Then type a new prompt in the active session.

**Verify:**
- `prompt_nugget.py` injects the new decision as context
- The nugget appears only once (watermark prevents duplicates)
- Subsequent prompts do not re-inject the same decision

---

### 2.9 Event Log Compaction

**Do:** Generate many events (50+), run housekeeping, then trigger compaction.

**Verify:**
- `compact.py` retains: post-watermark events, recent session_ends, SMM-referenced events
- Resolved events before the watermark are archived
- Watermarks are adjusted correctly
- `events.jsonl` is smaller after compaction
- No data corruption — events still parse correctly

---

### 2.10 Security-Relevant Triage

**Do:** Stage changes that touch authentication or security-sensitive code, then try to commit.

**Verify:**
- `/xp-security-triage` classifies changes as security-relevant
- Triage does NOT write the marker (instructs to run `/security-review` instead)
- After `/security-review` completes: `security_review_done.py` writes `.security-triaged` marker
- Commit succeeds on retry

---

### 2.11 Skills Availability

**Do:** In a session, check that the plugin's skills are available:

```
/xp-smm-protocol
/xp-kickoff
/xp-housekeeping
```

**Verify:**
- Each skill loads and provides reference content
- `xp-smm-protocol` covers event types, `working_on`, recording patterns
- `/xp-kickoff` orchestrates session start (retro → goals → question triage → housekeeping)
- `/xp-housekeeping` curates the four-pillar SMM

---

### 2.12 Concurrent Access (Worktrees / Agent Teams)

**Do:** Open two Claude sessions pointing at the same git repo (or use worktrees).

**Verify:**
- Both sessions share the same SMM directory
- Events from both sessions appear in the same `events.jsonl`
- `flock` prevents corruption on concurrent appends
- Prompt nuggets in one session surface events from the other
- Conflict detection catches overlapping `working_on` across sessions

---

### 2.13 Graceful Degradation

**Do:** Delete the SMM directory mid-session, then trigger hooks (write a file, type a prompt).

**Verify:**
- No crashes or error output
- Hooks pass through silently (exit 0 with no output)
- Next `SessionStart` recreates the SMM directory

---

## Test Results Checklist

| # | Test | Status |
|---|------|--------|
| 1.1 | Installation | |
| 1.2 | SMM init + kickoff gate | |
| 1.3 | Kickoff + goal collection | |
| 1.4 | User prompt logging | |
| 1.5 | File write + auto status + lint | |
| 1.6 | TDD order check | |
| 1.7 | Test writing and execution | |
| 1.8 | Commit + security triage gate | |
| 1.9 | Plan review | |
| 1.10 | Simplify gate | |
| 1.11 | Quality review gate | |
| 1.12 | TDD stop gate | |
| 1.13 | Session end event | |
| 1.14 | Desktop notifications | |
| 2.1 | Install into existing project | |
| 2.2 | Lint integration | |
| 2.3 | Conflict detection | |
| 2.4 | Retrospective | |
| 2.5 | Question triage | |
| 2.6 | Debt aging | |
| 2.7 | Subagent context injection | |
| 2.8 | Prompt nuggets | |
| 2.9 | Event log compaction | |
| 2.10 | Security-relevant triage | |
| 2.11 | Skills availability | |
| 2.12 | Concurrent access | |
| 2.13 | Graceful degradation | |

# Manual Test Plan

This document covers manual acceptance testing of the xp-agents plugin. It is organized into two parts: testing with a new project (cold start) and testing with an existing project. Each test has a **Do** step and a **Verify** step.

## Prerequisites

- Python 3.10+ on PATH
- Claude Code CLI installed
- macOS or Linux

### Finding the SMM Directory

Many verifications require inspecting the SMM directory. After the plugin initializes, find it with:

```bash
# From inside the test project:
GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
[[ "$GIT_COMMON_DIR" != /* ]] && GIT_COMMON_DIR=$(cd -- "$GIT_COMMON_DIR" && pwd -P)
PROJECT_ID=$(printf '%s' "$GIT_COMMON_DIR" | python3 -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest()[:12])")
SMM_DIR=~/.claude/xp-agents/${PROJECT_ID}/smm
echo $SMM_DIR
```

Useful inspection commands:

```bash
# View all events:
cat $SMM_DIR/events.jsonl | python3 -m json.tool --no-ensure-ascii

# Count events by type:
cat $SMM_DIR/events.jsonl | python3 -c "
import json, sys, collections
c = collections.Counter(json.loads(l)['type'] for l in sys.stdin if l.strip())
for t, n in c.most_common(): print(f'{n:3d} {t}')
"

# View materialized SMM:
cat $SMM_DIR/SHARED_MENTAL_MODEL.md

# View watermarks:
ls -la $SMM_DIR/.watermark-*

# View retrospective files:
ls $SMM_DIR/retrospectives/
```

### Cleanup Between Tests

To reset the SMM for a project without reinstalling:

```bash
rm -rf $SMM_DIR
```

To fully uninstall:

```bash
claude plugin uninstall xp-agents --scope user
```

---

## Part 1: New Project (Cold Start)

Create a fresh project for these tests:

```bash
mkdir /tmp/xp-test-new && cd /tmp/xp-test-new
git init && git commit --allow-empty -m "init"
```

### 1.1 Installation

**Do:** Add the marketplace and install the plugin at user scope.

```bash
# Add the local repo as a marketplace
claude plugin marketplace add /path/to/xp-agents

# Install at user scope
claude plugin install xp-agents@xp-agents --scope user
```

**Verify:**
- Command completes without error
- `claude plugin list --scope user` shows `xp-agents`

---

### 1.2 First Session Start — SMM Initialization

**Do:** Start a new Claude Code session in the test project.

```bash
cd /tmp/xp-test-new
claude
```

**Verify:**
- SMM directory created at `~/.claude/xp-agents/{project-id}/smm/`
- `events.jsonl` exists (may be empty or have initial events)
- `events.lock` exists
- `retrospectives/` directory exists
- Claude's first response includes project goal questions (customer proxy nudge)
- No errors in Claude's output about missing files or failed hooks

---

### 1.3 Goal Collection (Customer Proxy)

**Do:** When Claude asks about the project, respond with a goal:

```
Build a simple TODO app with a REST API
```

**Verify:**
- `events.jsonl` contains a `customer_input` event with your prompt text
- `events.jsonl` contains a `goal` event with the project description
- `SHARED_MENTAL_MODEL.md` shows the goal under Active Context with a target emoji prefix

---

### 1.4 User Prompt Logging

**Do:** Send any prompt to Claude:

```
Let's start by creating the data model
```

**Verify:**
- `events.jsonl` contains a new `customer_input` event with `agent_id: "customer"` and your prompt text

---

### 1.5 File Write — Navigator Nudge + Auto Status

**Do:** Ask Claude to create a file:

```
Create a file called todo.py with a Todo dataclass that has id, title, and done fields
```

**Verify after the write completes:**
- `events.jsonl` contains a `status` event with `working_on` including `todo.py`
- Claude's context shows evidence of navigator guidance (strategic direction before the write)
- If the project has a linter config (e.g., `ruff.toml`), a lint check runs after the write

---

### 1.6 TDD Order Check

**Do:** Ask Claude to write implementation code without tests first:

```
Add a function to todo.py that filters todos by completion status
```

**Verify:**
- Claude's context includes a TDD order warning (implementation before test detected)
- The warning appears as `additionalContext` noting that tests should come first

---

### 1.7 Test Writing and Execution

**Do:** Ask Claude to write and run tests:

```
Write tests for the Todo dataclass and the filter function, then run them
```

**Verify:**
- After the test file is written: `status` event with `working_on` including the test file
- After tests run successfully: `status` event recording test results (pass count)
- `events.jsonl` contains events from `bash_post_tool.py` parsing test output

---

### 1.8 Quality Reviewer (Background)

**Do:** Ask Claude to write a function with a potential quality issue:

```
Add an endpoint handler that catches all exceptions and silently passes
```

**Verify:**
- After the write, the quality reviewer subagent fires in the background
- `events.jsonl` may contain a `concern` event about the empty exception handler
- The concern references the file and describes the issue

---

### 1.9 Git Commit — Size Check and Auto Decision

**Do:** Ask Claude to commit the work:

```
Commit what we have so far
```

**Verify:**
- If more than 10 files are staged (the `commit_size_threshold`), a warning appears
- `events.jsonl` contains a `decision` event with `draft: true` auto-generated from the commit
- The decision content summarizes what was committed

---

### 1.10 Plan Review — SubagentStop Block

**Do:** Ask Claude to create a multi-step plan:

```
Plan the implementation of REST API endpoints for CRUD operations on todos
```

**Verify:**
- When the Plan subagent completes, `subagent_stop.py` blocks (exit 2) with instructions to invoke the plan reviewer
- Claude invokes `xp-plan-reviewer` subagent
- The plan reviewer checks: step count, TDD ordering, decision conflicts
- `events.jsonl` may contain `assumption` or `decision` events extracted by the reviewer

---

### 1.11 Security Review Gate (Strict Mode)

**Do:** Ask Claude to push to a remote (set up a bare remote first if needed, or just observe the block):

```
Push this to the remote
```

**Verify:**
- The push is blocked (exit 2) because no security review has been run for the current HEAD
- `events.jsonl` contains a `security_review_requested` event
- Claude is instructed to run `/security-review` first

**Do:** Run the security review, then try pushing again:

```
/security-review
```

**Verify:**
- A `.security-reviewed-{hash}` tracker file appears in the SMM directory
- The subsequent push attempt is no longer blocked

---

### 1.12 Simplify Gate at Stop

**Do:** After Claude has written files in the current loop, tell it you're done:

```
That's all for now
```

**Verify:**
- If files were changed, the simplify gate blocks and instructs Claude to run `/simplify`
- After `/simplify` runs, the gate allows stop
- A `.simplify-{agent_id}.json` tracker file exists in the SMM directory

---

### 1.13 TDD Stop Gate

**Do:** Introduce a failing test, then try to end the session:

```
Add a test that asserts 1 == 2, run it, then stop
```

**Verify:**
- The TDD prompt hook (`tdd_check.md`) blocks the stop because tests are failing
- Claude is told to fix the failing test before stopping
- After fixing the test and re-running, the stop is allowed

---

### 1.14 Session End

**Do:** Let the session end normally (Ctrl+C or Claude completes).

**Verify:**
- `events.jsonl` contains a `session_end` event
- The event includes: duration, event count, unresolved items count, active `working_on` files
- If the agent didn't write a final status summary, the event flags `missing_final_status: true`

---

### 1.15 Desktop Notifications

**Do:** In a session, ask Claude to raise a blocking question:

```
I have a blocking question: should we use SQLite or PostgreSQL for storage?
```

**Verify (macOS):**
- A desktop notification appears for the blocking question
- The notification comes from `osascript` and mentions "xp-agents"

---

### 1.16 Enforcement Mode — Advisory

**Do:** Change enforcement to advisory mode. Edit `settings.json` in the installed plugin (or temporarily modify the source before reinstalling):

```json
{
  "commit_size_threshold": 10,
  "enforcement": "advisory"
}
```

Then trigger a situation that would normally block (e.g., `working_on` conflict, push without security review).

**Verify:**
- The hook fires and logs the same events as strict mode
- Instead of blocking (exit 2), the issue appears as a warning in `additionalContext`
- Claude sees `[enforcement: advisory]` indicator
- The session is not interrupted — warnings only

---

## Part 2: Existing Project

Use a project with existing code and git history but without the xp-agents plugin previously installed (no existing SMM). Ideally the project has a linter config (e.g., `ruff.toml` or `.eslintrc`) for test 2.2.

### 2.1 Installation into Existing Project

**Do:** Install the plugin and start a session in the existing project.

```bash
cd /path/to/existing-project
claude
```

**Verify:**
- SMM initializes without affecting existing project files
- SMM directory is created at user level (`~/.claude/xp-agents/...`), not inside the project
- Claude asks for project goals on first session (customer proxy)
- No interference with existing git state

---

### 2.2 Lint Integration

**Do:** Ask Claude to modify an existing file in a project that has a linter configured.

**Verify:**
- After the write, `lint_check.py` detects the linter config (ruff, eslint, prettier, or flake8)
- The linter runs on the modified file
- If lint errors are found, a `concern` event is appended to `events.jsonl`
- If no lint config exists, a one-time warning appears (not repeated)

---

### 2.3 Working On Conflict Detection

**Do:** This requires two concurrent agents (Agent Teams) or simulating concurrent access. Seed a `status` event with `working_on` for a file, then ask Claude to modify that same file.

```bash
# Seed a conflicting status event:
$SMM_DIR/../../plugins/xp-agents/smm/append.sh \
  --type status \
  --agent teammate-1 \
  --content "Working on auth module" \
  --working-on '["src/auth.py"]'
```

Then ask Claude to edit `src/auth.py`.

**Verify (strict mode):**
- `pre_tool_use.py` detects the `working_on` overlap
- The write is blocked (exit 2) with an explanation of the conflict
- The conflict identifies which agent holds the overlapping file

---

### 2.4 Second Session — Retrospective

**Do:** After a first session with meaningful activity (5+ events), start a new session.

```bash
claude
```

**Verify:**
- `retrospective.py` detects unanalyzed events and writes `.retro-input.json`
- Claude invokes the `xp-retrospective` subagent
- The retrospective output includes:
  - **Keep**: specific things that went well, with event references
  - **Fix**: issues identified, tagged with XP values (Communication, Simplicity, Courage, Feedback, Respect)
  - **Try**: actionable experiments for this session
- Session stats are reported: navigator guidance count, concern resolution rate, decision recording rate
- A retrospective file is written to `$SMM_DIR/retrospectives/`
- `events.jsonl` contains a `retrospective` event

---

### 2.5 Customer Intent Reconciliation

**Do:** In a first session, request multiple features. In the second session, complete some of them.

Session 1:
```
Add user authentication
Add pagination to the list endpoint
```

Session 2 (after completing pagination):
```
claude  # starts new session
```

**Verify:**
- `customer_intent` events exist for each request
- The customer proxy reviews open intents against completed work
- Delivered intents are marked with `intent_status: "delivered"`
- Undelivered intents appear in the materialized SMM under Active Context

---

### 2.6 Technical Debt Aging

**Do:** Create a debt event, then simulate multiple sessions ending:

```bash
# Append a debt event:
${PLUGIN_ROOT}/smm/append.sh \
  --type debt \
  --agent main \
  --content "Auth middleware uses placeholder secret" \
  --files '["src/auth.py"]'

# Append several session_end events to age the debt:
for i in $(seq 1 7); do
  ${PLUGIN_ROOT}/smm/append.sh \
    --type session_end \
    --agent main \
    --content "Session $i complete"
done
```

Then start a new session and check the materialized view.

**Verify:**
- Debt at 0-3 sessions appears normally in the Reference section
- Debt at 4-6 sessions appears with a warning emoji
- Debt at 7+ sessions appears with a red circle emoji
- The retrospective escalates aging debt in Fix items
- Navigator nudges when modifying files with associated debt

---

### 2.7 Subagent SMM Injection

**Do:** Ask Claude to use a subagent (e.g., create a Plan, or any action that spawns a subagent).

**Verify:**
- `subagent_start.py` fires and injects the full materialized SMM into the subagent's context
- A watermark file (`.watermark-{agent_id}`) is created in the SMM directory
- `subagent_stop.py` fires when the subagent completes and records a `status` event

---

### 2.8 PreCompact Backup

**Do:** Trigger context compaction (fill the context window or use `/compact`).

**Verify:**
- `pre_compact.py` creates timestamped backups in the SMM directory:
  - `events.jsonl.backup-{timestamp}`
  - `SHARED_MENTAL_MODEL.md.backup-{timestamp}`
- After compaction, `session_start.py` re-injects the full SMM (the `compact` matcher fires)

---

### 2.9 PostCompact Log Compaction

**Do:** Trigger compaction after accumulating many events across multiple sessions.

**Verify:**
- `compact.py` (PostCompact hook) runs after Claude's built-in compaction
- Old events are archived to `$SMM_DIR/backups/archive-{timestamp}.jsonl`
- Permanent event types are retained: `decision`, `convention`, `goal`, `debt`, `assumption`, `retrospective`
- Unresolved questions and concerns are retained regardless of age
- Events from the last 3 sessions (configurable `keep_sessions`) are retained
- All watermarks are removed (agents will re-read from the beginning)

---

### 2.10 SMM Repair

**Do:** Corrupt the event log, then run the repair tool:

```bash
# Add some corrupt lines:
echo "not json" >> $SMM_DIR/events.jsonl
echo '{"partial": true}' >> $SMM_DIR/events.jsonl

# Run repair:
python3 /path/to/plugins/xp-agents/smm/repair.py $SMM_DIR
```

**Verify:**
- Original file backed up to `$SMM_DIR/backups/pre-repair-{timestamp}.jsonl`
- Malformed JSON lines are removed
- Lines missing required fields (`id`, `type`) are removed
- Duplicate event IDs are deduplicated
- Events are sorted by timestamp
- A `.repair-report.json` file summarizes what was fixed
- `--dry-run` flag shows what would change without modifying anything

---

### 2.11 Schema Migration

**Do:** Check that migration handles version differences:

```bash
python3 /path/to/plugins/xp-agents/smm/migrate.py $SMM_DIR
```

**Verify:**
- Events without `schema_version` are treated as v1
- v1 events get timestamps normalized to include timezone (v2 migration)
- Events already at the current version are unchanged
- Running migration again is idempotent (no changes on second run)
- Events with a future `schema_version` pass through unchanged (forward-compatible)

---

### 2.12 Drift Signals

**Do:** Create conditions for drift detection:

```bash
# Stale decision (no activity on topic for 5+ sessions):
${PLUGIN_ROOT}/smm/append.sh \
  --type decision \
  --agent main \
  --content "Use REST, not GraphQL" \
  --topic "api-style"

# Add 5+ session_end events without any activity on that topic
for i in $(seq 1 6); do
  ${PLUGIN_ROOT}/smm/append.sh \
    --type session_end \
    --agent main \
    --content "Session $i"
done
```

Then materialize the SMM.

**Verify:**
- `SHARED_MENTAL_MODEL.md` contains a "Drift Signals" section under Active Context
- The stale decision appears as a drift signal
- Ignored conventions (3+ unresolved concerns referencing a convention) also surface

---

### 2.13 Velocity Signal

**Do:** Run a session with meaningful activity, then check the materialized SMM.

**Verify:**
- `SHARED_MENTAL_MODEL.md` contains a "Velocity" section under Active Context
- Metrics include: events this session, total sessions, decisions made/revisited
- If the same topic has 3+ decisions, it appears as a churn topic
- Concern resolution ratio is reported

---

### 2.14 Worktree Sharing (Agent Teams)

**Do:** Create a git worktree and verify SMM sharing:

```bash
cd /path/to/existing-project
git worktree add ../project-worktree some-branch
cd ../project-worktree
```

Start a Claude session in the worktree.

**Verify:**
- The worktree derives the same SMM directory as the main repo (same `project-id` from `git rev-parse --git-common-dir`)
- Events written from the worktree are visible in the main repo's SMM
- Events written from the main repo are visible in the worktree's SMM
- Watermarks are independent per agent

---

### 2.15 Skills Availability

**Do:** In a session, check that the plugin's skills are available:

```
/smm-protocol
/xp-values
/pair-programming
```

**Verify:**
- Each skill loads and provides reference content
- `smm-protocol` covers event types, `working_on`, recording patterns
- `xp-values` covers the five XP values as behaviors
- `pair-programming` covers navigator/driver protocol

---

## Test Results Checklist

| # | Test | New | Existing | Pass |
|---|------|-----|----------|------|
| 1.1 | Installation | x | | |
| 1.2 | SMM initialization | x | | |
| 1.3 | Goal collection | x | | |
| 1.4 | User prompt logging | x | | |
| 1.5 | File write + navigator + auto status | x | | |
| 1.6 | TDD order check | x | | |
| 1.7 | Test writing and execution | x | | |
| 1.8 | Quality reviewer | x | | |
| 1.9 | Git commit — size check + auto decision | x | | |
| 1.10 | Plan review block | x | | |
| 1.11 | Security review gate | x | | |
| 1.12 | Simplify gate | x | | |
| 1.13 | TDD stop gate | x | | |
| 1.14 | Session end event | x | | |
| 1.15 | Desktop notifications | x | | |
| 1.16 | Advisory enforcement mode | x | | |
| 2.1 | Install into existing project | | x | |
| 2.2 | Lint integration | | x | |
| 2.3 | Working on conflict detection | | x | |
| 2.4 | Retrospective | | x | |
| 2.5 | Customer intent reconciliation | | x | |
| 2.6 | Technical debt aging | | x | |
| 2.7 | Subagent SMM injection | | x | |
| 2.8 | PreCompact backup | | x | |
| 2.9 | PostCompact log compaction | | x | |
| 2.10 | SMM repair | | x | |
| 2.11 | Schema migration | | x | |
| 2.12 | Drift signals | | x | |
| 2.13 | Velocity signal | | x | |
| 2.14 | Worktree sharing | | x | |
| 2.15 | Skills availability | | x | |

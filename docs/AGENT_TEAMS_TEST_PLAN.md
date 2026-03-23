# Agent Teams Empirical Test Plan

## Purpose

Determine which hook events fire for Agent Team teammates, what input fields they receive, and whether our existing hooks work correctly in a team context. This resolves the central design question: do teammates behave like full sessions (Model A) or something else?

## Questions to Answer

| # | Question | Impact |
|---|---|---|
| Q1 | Does **Stop** fire for teammates? | Determines if our Stop gates (simplify, quality review, TDD) work or need TeammateIdle equivalents |
| Q2 | Does **SessionStart** fire for teammates? What `source`? | Determines if session_start.py, retrospective.py need `is_teammate()` guards |
| Q3 | Does **UserPromptSubmit** fire for teammate prompts? | Determines if kickoff_gate.py, user_prompt_log.py, prompt_nugget.py need guards |
| Q4 | Do **plugin hooks** (hooks.json) fire for teammates? | If no, only settings.json hooks work — major architectural impact |
| Q5 | What **agent_type** value do teammates get? | Determines `is_teammate()` detection logic |
| Q6 | Do teammates get unique **session_ids**? | Indicates whether teammates are full sessions |
| Q7 | What fields do **TeammateIdle** and **TaskCompleted** provide? | Shapes our hook handlers for these events |
| Q8 | Does **SubagentStart** fire when a teammate is spawned? | Determines if SMM injection works for teammates |
| Q9 | Can a teammate invoke a **plugin skill** (e.g., `/xp-security-triage`)? | Determines if security triage works for teammates |
| Q10 | Do teammates get **worktree isolation** automatically? | Determines if we need to request it via spawn prompt |

## Prerequisites

- Claude Code v2.1.32+
- xp-agents plugin installed
- A test project with a git repo

## Setup

### 1. Enable Agent Teams

Add to `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### 2. Merge probe hooks

The probe hooks add a lightweight logger to every hook event. They run alongside existing hooks without interfering.

```bash
cd /path/to/xp-agents
python3 plugins/xp-agents/scripts/merge_probe_hooks.py
```

This merges entries from `hooks/agent_teams_test_hooks.json` into `hooks/hooks.json`.

### 3. Bump plugin version

Edit `plugins/xp-agents/.claude-plugin/plugin.json` and increment the version so the plugin cache picks up the changes.

### 4. Clear old probe data

```bash
rm -f ~/.claude/plugins/data/xp-agents-xp-agents/agent-teams-probe.jsonl
```

### 5. Update the installed plugin

```bash
claude plugin update xp-agents@xp-agents
```

Or if using `--plugin-dir` for development:

```bash
claude --plugin-dir /path/to/xp-agents/plugins/xp-agents
```

## Run the Test

### Phase 1: Baseline (lead only)

Start Claude Code in a test project:

```bash
cd /path/to/test-project
claude
```

Run kickoff to establish a baseline of lead-only hook firings:

```
/xp-kickoff
```

This captures which hooks fire for the lead (agent_id=main). Every subsequent teammate firing can be compared against this baseline.

### Phase 2: Spawn a team

Ask the lead to create a simple team with tasks that exercise our hooks:

```
Create an agent team with 2 teammates. Give them these tasks:

Teammate 1: Create src/hello.py with a hello() function that returns
"Hello, World!". Write tests in tests/test_hello.py. Commit when done.

Teammate 2: Create src/goodbye.py with a goodbye() function that returns
"Goodbye, World!". Write tests in tests/test_goodbye.py. Commit when done.
```

This exercises:
- **File writes** (PreToolUse:Write, PostToolUse:Write) — do they fire for teammates?
- **Bash** (PreToolUse:Bash, PostToolUse:Bash) — commit gate, test parsing
- **Stop** — does it fire when a teammate finishes a response?
- **Skills** — can teammates run `/xp-security-triage`?

### Phase 3: Observe

Let the teammates work. Watch for:
- Do teammates hit the kickoff gate? (Blocked by `.needs-kickoff`)
- Do teammates hit the security triage gate on commit?
- Do lint checks run after teammate writes?
- Does the lead receive TeammateIdle events?
- Does TaskCompleted fire when tasks are marked done?

### Phase 4: Clean up

```
Clean up the team
```

Exit the session. The probe log is now complete.

## Analyze Results

### Run the analyzer

```bash
python3 plugins/xp-agents/scripts/analyze_probe.py
```

Or with a specific probe file:

```bash
python3 plugins/xp-agents/scripts/analyze_probe.py ~/.claude/plugins/data/xp-agents-xp-agents/agent-teams-probe.jsonl
```

### What to look for

The analyzer reports:

1. **Hook events fired** — which events, for which agent_id/agent_type combinations
2. **Q1: Stop scope** — did Stop fire for any agent_id other than "main"?
3. **Q2: SessionStart scope** — did SessionStart fire for teammates? What source?
4. **Q3: UserPromptSubmit scope** — did it fire for teammate prompts?
5. **Q4-Q6: TeammateIdle/TaskCompleted details** — what fields are available?
6. **Q7: Distinct sessions** — how many unique session_ids?
7. **Input keys by event** — what fields we didn't anticipate?

### Manual checks (during the test)

While the test runs, also note:
- **Q9:** Did the teammate successfully invoke `/xp-security-triage` when the commit gate blocked?
- **Q10:** Did the teammate work in a worktree? Check with `git worktree list` after the test.

## After Testing

### Revert probe hooks

```bash
python3 plugins/xp-agents/scripts/merge_probe_hooks.py --revert
```

Bump the plugin version again and update the installed plugin.

### Record results

Update `docs/AGENT_TEAMS_DESIGN.md` with the empirical results:
- Which model is correct (A, B, or C)?
- Which hooks need `is_teammate()` guards?
- What agent_type value teammates use
- Whether TeammateIdle/TaskCompleted need to replicate Stop gate logic

### Save the probe log

Keep a copy of the probe log for reference:

```bash
cp ~/.claude/plugins/data/xp-agents-xp-agents/agent-teams-probe.jsonl \
   docs/agent-teams-probe-results.jsonl
```

## Decision Matrix

Based on results, the implementation path branches:

| Result | Action |
|---|---|
| Model A (teammates get Stop) | Minimal changes — add `is_teammate()` guards to ceremony hooks, everything else works |
| Model B (teammates don't get Stop) | Build TeammateIdle equivalents for simplify, quality review, and TDD gates |
| Model C (hybrid) | Same as Model B but some Stop hooks work via frontmatter conversion |
| Plugin hooks don't fire for teammates | Major redesign — move hooks to settings.json or find alternative |
| SessionStart fires for teammates | Add `is_teammate()` guards to session_start.py, retrospective.py, kickoff_gate.py |
| UserPromptSubmit fires for teammates | Add `is_teammate()` guards to user_prompt_log.py, kickoff_gate.py |

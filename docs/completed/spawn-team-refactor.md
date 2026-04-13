# Spawn Team Refactor: Inline Skill + Worktree Isolation

## Problem

Agent Teams platform tells teammates "Do NOT commit." The lead ends up with one massive commit containing all stories' work. This conflicts with XP small-commit practice and means the review cycle only runs once on the combined work.

## Session Learnings (2026-04-10)

We tested Agent Teams during M3 of the context gradient work. Two teammates worked in parallel on independent stories (parser extensions + subagent injection) while the lead handled a SKILL.md rewrite. Key findings:

- **Agent Teams commit bottleneck is the main limitation.** Teammates produced clean code but the lead became a serial bottleneck for staging, formatting, reviewing, and committing all work. The review cycle (simplify/quality/security) ran once on the combined diff.
- **Small stories don't parallelize well.** For S-sized stories, coordination overhead (spawning, briefing, waiting, reviewing, committing) exceeds the time saved by parallelism. M/L stories are where parallelism pays off.
- **Spawn-team analysis is valuable even for solo work.** The structured decomposition (file domains, interface contracts, prompt templates) is useful regardless of execution mode.
- **Teammates respect domain boundaries when briefed well.** Explicit file domain lists + "message the lead if you need changes outside your domain" worked perfectly.
- **Review cycle is serial with Agent Teams but parallel with worktree subagents.** This is the key insight driving the two-mode simplification.

## Solution

Convert `/xp-spawn-team` from a forked analysis agent to an inline skill that directly spawns worktree-isolated subagents. Each subagent works in its own worktree, runs the full development lifecycle (TDD + review cycle + commits) independently, and the lead merges branches after.

## Architecture

### Current Flow (forked agent)
1. Lead runs `/xp-spawn-team`
2. Forked subagent analyzes plan, outputs spawn instructions as text
3. Lead manually spawns teammates using TeamCreate or Agent tool
4. Teammates work in same repo, cannot commit (platform restriction)
5. Lead commits everything in one large commit

### New Flow (inline skill + worktree subagents)
1. Lead runs `/xp-spawn-team`
2. Inline skill analyzes plan (has access to SMM, sprint, plan via SubagentStart + preload)
3. Skill spawns N `xp-teammate` agents directly with `run_in_background: true`
4. Each teammate auto-gets its own worktree (via `isolation: worktree` frontmatter)
5. Teammates commit independently within their TDD cycles
6. Lead gets notified as each finishes, merges branches, runs final review cycle

## Subagent Autonomy

Worktree subagents run the full development lifecycle independently. The lead does NOT review, format, or commit their work — each subagent is a self-sufficient developer:

1. **Own TDD cycle** — write tests first, implement, refactor
2. **Own review cycle** — run /simplify, /xp-quality-review, /xp-security-triage
3. **Own commits** — small, frequent, within TDD cycles (XP small-commit practice)
4. **Own event recording** — log status, concerns, decisions to shared SMM via flock-protected append

### Lead Role with Worktree Subagents

The lead's job is coordination, not execution:
1. Run `/xp-spawn-team` to analyze plan and spawn subagents with story-specific prompts
2. Wait for completion notifications (subagents run in background)
3. Merge branches — resolve conflicts if any (rare with good file domains; lead has full context from the plan)
4. Run integration tests on the merged result (full test suite)
5. Check acceptance criteria for each story
6. Final commit on main branch if integration passes

### Lead Role Solo

When working solo (sequential mode), the lead executes stories directly — same as current workflow with full TDD + review cycle per story.

## Changes Required

### New: `agents/xp-teammate.md`
Generic worktree-isolated teammate agent definition.
```yaml
---
name: xp-teammate
description: Worktree-isolated teammate for parallel story implementation
isolation: worktree
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
---
```
Body contains generic teammate instructions. Story-specific context (file domain, TDD steps, references) comes from the spawn prompt.

### Update: `skills/xp-spawn-team/SKILL.md`
- Remove `context: fork` and `agent: xp-agents:xp-spawn-team`
- Change to inline skill
- Skill analyzes plan + sprint, determines:
  - Team size (number of independent stories)
  - File domains per story
  - Dependency order
  - TDD steps with commit boundaries
- Skill spawns `xp-teammate` agents directly using Agent tool
- Each spawn includes story-specific prompt with file domain, references, TDD steps
- Spawns use `run_in_background: true` for parallel execution

### Update: `agents/xp-spawn-team.md`
- Remove or repurpose — analysis logic moves to inline skill

### Update: `BEHAVIORAL_GUIDE.md`
- Update Agent Teams section to reference worktree-isolated teammates

### Update: `TEAMMATE_GUIDE.md`
- Add instructions about committing in worktree
- Add instructions about branch naming
- Note that lead will merge their branch when complete

## Key Design Decisions

### Why inline skill instead of forked agent?
- Inline skill runs on main agent → can use Agent tool to spawn subagents
- Forked agent is a subagent itself → cannot spawn other subagents
- Inline matches the pattern: interactive skills that take action are inline

### Why one generic `xp-teammate` agent vs per-story agents?
- Same agent definition can be spawned multiple times simultaneously
- Each spawn gets its own unique worktree (confirmed by docs)
- No need for dynamic agent creation or `/reload-plugins`
- Story-specific context comes from the spawn prompt

### Why worktree isolation?
- Each teammate gets independent working directory
- No file conflicts between parallel teammates
- Teammates CAN commit (no platform "do not commit" restriction)
- Auto-cleanup when teammate finishes without changes
- Orphaned worktrees cleaned after configurable period

### Branch merge strategy
- Each teammate works on an auto-generated branch in their worktree
- Lead merges branches after teammates complete
- Review cycle runs on the merge commit
- Conflicts resolved by lead (rare if file domains are respected)

## Two Spawn Modes

The spawn skill supports two modes, chosen based on plan analysis:

### Solo (Sequential)
- Stories with dependencies, overlapping file domains, or all S-sized
- Run one at a time, lead executes each story directly
- Simplest, safest — no merge conflicts, no coordination overhead
- Best for: dependent work, small stories, overlapping domains

### Worktree Subagents (Parallel)
- Independent M/L stories with clear file domain boundaries
- Each subagent gets isolated worktree, runs full lifecycle independently
- Subagents own: TDD cycle, review cycle (simplify/quality/security), commits
- Lead merges branches after completion, runs integration tests
- Best for: parallel story implementation with separate file domains

### Why not Agent Teams?
Agent Teams exist as a platform feature but are not recommended by spawn-team:
- **Commit restriction** — teammates cannot commit, making the lead a serial bottleneck
- **Review cycle runs once** on the combined diff, not per-story
- **Worktree subagents are strictly better** when file domains are independent — they get full autonomy (TDD + review + commits) with the same parallelism benefit
- Agent Teams remain useful for ad-hoc collaborative work outside the sprint flow

### Mode Selection Heuristic
The spawn skill's analysis phase determines file domains, dependencies, and story size:
- **Dependency chain** between stories → Solo
- **All S-sized stories** → Solo (coordination overhead exceeds parallelism benefit)
- **Overlapping file domains** (shared infrastructure, index files) → Solo
- **Independent M/L stories with clear file domains** → Worktree Subagents

## Platform Constraints (from official docs)

### Worktree Isolation
- `isolation: worktree` works for plugin agents in frontmatter ✅
- Worktree subagents **CAN commit** — no "do not commit" restriction ✅
- Same agent definition can be spawned multiple times with separate worktrees ✅
- All hooks (PreToolUse, PostToolUse, etc.) still fire inside worktrees ✅
- `/reload-plugins` NOT needed for pre-registered plugin agents ✅

### Branch Management
- Branches auto-named `worktree-<name>`
- **Worktrees branch from `origin/HEAD` by default** — for non-default branches (e.g. v2), need a WorktreeCreate hook or `git remote set-head origin v2` to set the correct base
- WorktreeCreate hook can customize branching strategy (fetch from specific ref, custom naming)
- WorktreeRemove hook available for custom cleanup

### Worktree Lifecycle
- **No changes → auto-removed** (directory + branch cleaned up)
- **Changes/commits exist → prompt to keep or remove**
- Orphaned worktrees from crashed subagents cleaned up after `cleanupPeriodDays`
- Untracked files (never staged) do not prevent auto-removal

### Worktree Environment
- Gitignored files (`.env`, etc.) are NOT copied to worktrees
- Use `.worktreeinclude` file (`.gitignore` syntax) to auto-copy needed files
- Subagents can define their own hooks in frontmatter (only fire during that agent's execution)

### Agent Teams (existing — not recommended for spawn-team)
- Platform-managed lifecycle
- "Do NOT commit" restriction on teammates — lead becomes serial bottleneck
- Teammates share repo — real-time visibility of each other's writes
- TeammateIdle / TaskCompleted hooks for coordination
- File conflicts possible if domains overlap
- **Tested 2026-04-10**: works for parallel code generation but review cycle + commit overhead negates parallelism benefit for most use cases

## Risks & Concerns

### Merge Conflicts
Stories often share infrastructure files (imports, registrations, test fixtures, conftest.py). If file domains aren't truly independent, worktree merges will conflict. The spawn skill MUST analyze file domains rigorously and fall back to Solo when overlap is detected. When conflicts do occur (expected to be rare with good file domain analysis), the lead resolves them during the merge step — the lead has full context from the plan and both stories' work.

### Post-Merge Test Failures
Tests passing in isolation but failing after merge is the biggest operational risk. Each worktree has a consistent snapshot — interactions between stories only surface after merge. The lead must understand ALL the work to fix these. Mitigation: keep file domains truly independent; run full test suite after each merge.

### SMM Path Resolution in Worktrees
`git rev-parse --git-common-dir` points to the same git dir across worktrees, meaning all worktree subagents share the same SMM. **Verified** — the SMM at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` is shared across all worktrees, coordinated by existing `flock`-based concurrency control (see "Shared State Across Worktrees" in Community Findings).

### Hook Compatibility
TeammateIdle and TaskCompleted hooks were built for Agent Teams. Worktree subagents fire SubagentStop instead. The hook layer needs to handle both paths, or worktree subagents need separate hook coverage.

### Branch Base Mismatch
If the project works on a non-default branch (e.g. v2), worktrees branching from `origin/HEAD` (main) would start from the wrong base. Requires either a WorktreeCreate hook or `git remote set-head` configuration.

## Open Questions (All Resolved)

1. ~~How should the teammate's branch be named?~~ → Auto-named `worktree-<name>` by platform
2. ~~Should the skill wait for all teammates to finish, or return immediately (`run_in_background`)?~~ → Teammates spawn with `run_in_background: true`. Lead waits for completion notifications — each teammate sends a message when done.
3. ~~Should the lead auto-merge, or present branches for review first?~~ → Lead merges manually with `git merge <worktree-branch> --no-ff`, resolves any conflicts (rare with good file domains), then runs full test suite on the merged result.
4. ~~How does the accept gate interact with worktree branches? Does it check sprint.md in the worktree or the main repo?~~ → Accept checks sprint.json in the shared SMM at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/`, which is shared across all worktrees. Story status is tracked there, not in any worktree-local file.
5. ~~Should teammates get the full SMM via SubagentStart, or a trimmed version?~~ → Teammates get SMM + TEAMMATE_GUIDE.md via SubagentStart tiered injection (detected by `is_teammate_by_agent_type()`). Story-specific context comes via the spawn prompt, not SubagentStart.
6. ~~What happens if a teammate's tests pass in their worktree but fail after merge? (See Risks above)~~ → Lead runs the full test suite after each merge. Post-merge failures are rare with good file domain separation. When they occur, the lead has full context from the plan and both stories' work to resolve them.

## Testing Strategy

### Empirical Verification (before building)
- Verify `isolation: worktree` works for plugin-defined agents
- Verify `git rev-parse --git-common-dir` resolves to shared SMM from worktree
- Verify XP plugin hooks (TDD gate, commit gate, review cycle) fire correctly inside worktree subagent
- Verify WorktreeCreate hook can set custom branch base

### Automated Tests
- Unit tests for mode selection heuristic (file domain analysis → mode choice)
- Unit tests for the new inline skill logic
- Integration test: spawn a teammate, verify worktree created
- Integration test: teammate commits in worktree, verify branch exists
- Integration test: lead merges branch, verify combined tests pass

### Manual Tests
- Manual test in test project with real multi-story sprint
- Manual test with overlapping file domains to verify mode fallback

## Community Findings

### Critical Bug: Worktree Isolation Broken for Agent Teams
`isolation: "worktree"` is silently ignored when combined with `team_name` in the Agent
tool. Agent Teams teammates always run in the main repo regardless of the isolation
setting. This confirms our three-mode design — Agent Teams and worktree subagents are
separate paths, not combinable. ([anthropics/claude-code#33045](https://github.com/anthropics/claude-code/issues/33045))

### WorktreeCreate Stdout Handling Is Fragile (Other Hooks Unaffected)
WorktreeCreate hooks expect a **plain text path** on stdout (not JSON). Any extra output
(e.g., `git worktree add` status messages) gets concatenated with the path, causing
Claude Code to **hang silently with no timeout**. Fix: redirect all subprocess output to
stderr/dev/null, only echo the path on stdout.
([anthropics/claude-code#27467](https://github.com/anthropics/claude-code/issues/27467),
[claude-worktree-hooks](https://github.com/tfriedel/claude-worktree-hooks))

**This does NOT affect our PreToolUse/PostToolUse/SubagentStart hooks.** Those use JSON
output for `additionalContext` injection, and JSON parsing is robust regardless of
worktree context. Only WorktreeCreate has the fragile plain-text path contract. If we
implement a WorktreeCreate hook for branch base customization, it must keep stdout clean:
```bash
git worktree add "$PATH" -b "$NAME" >/dev/null 2>&1
echo "$PATH"  # only this on stdout
```

### WorktreeCreate/Remove Hook Pattern (Database Isolation)
Production pattern from damiangalarza.com for bootstrapping per-worktree resources:
- **WorktreeCreate**: Creates branch, copies env files via `.worktreeinclude`, generates
  `.env.local` with unique names derived from branch slug, runs setup/migrations
- **WorktreeRemove**: Drops per-worktree resources, deregisters worktree, deletes branch
- Both hooks receive JSON via stdin and return the worktree path on stdout
- Key insight: "Worktree gives you file isolation, the hook gives you everything else"
  — worktrees isolate the code, hooks bootstrap whatever else needs isolation

### EnterWorktree Hook Timing Issue
`PostToolUse:EnterWorktree` does NOT fire when worktrees are created via `claude -w`
flag. It only fires for internal `EnterWorktree` tool use (agent isolation cases). Use
`SessionStart` instead for early setup.
([anthropics/claude-code#39277](https://github.com/anthropics/claude-code/issues/39277))

### Branch Naming Not Configurable
Branches are auto-generated as `worktree-{hash}` — not configurable to story-ID based
naming. Feature request exists but is not implemented.

### Parallel Development in Practice (incident.io)
incident.io uses shell wrappers to quickly spawn Claude in worktrees for parallel
feature work. Measured improvement: 18% on their codegen pipeline (30 seconds saved).
Main workflow insight: Plan Mode + worktrees + voice dictation for rapid feature
spawning. They don't detail merge strategy or hooks — it's a workflow advocacy piece,
not a technical deep-dive.
([incident.io blog](https://incident.io/blog/shipping-faster-with-claude-code-and-git-worktrees))

### Shared State Across Worktrees
From production users:
- `.git` history and remote connections shared (no duplication)
- `~/.claude/projects/<repo>/memory/` shared (learning carries over)
- `CLAUDE.md` files at project root inherited by all worktrees
- `.claude/state/` isolated per worktree (task state doesn't bleed)
- Our SMM at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` would be shared across worktrees
  — all agents write to the same event log, coordinated by our existing `flock`

## Dependencies

- Requires `isolation: worktree` to work reliably for plugin agents
- Requires SubagentStart dispatch table entry for `xp-teammate` (already have pattern)
- WorktreeCreate hook needed for non-default branch bases
- No platform changes needed — uses existing Claude Code features
- **Blocker**: Agent Teams + worktree isolation is broken (anthropics/claude-code#33045)
  — must use standalone subagents, not team agents

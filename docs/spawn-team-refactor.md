# Spawn Team Refactor: Inline Skill + Worktree Isolation

## Problem

Agent Teams platform tells teammates "Do NOT commit." The lead ends up with one massive commit containing all stories' work. This conflicts with XP small-commit practice and means the review cycle only runs once on the combined work.

## Solution

Convert `/xp-spawn-team` from a forked analysis agent to an inline skill that directly spawns worktree-isolated subagents. Each teammate works in its own worktree, commits independently within TDD cycles, and the lead merges branches after.

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

## Platform Constraints (verified)

- `isolation: worktree` works for plugin agents (confirmed)
- Same agent can be spawned multiple times with unique worktrees (confirmed)
- Worktree creation/cleanup is automatic (confirmed)
- WorktreeCreate/WorktreeRemove hooks available if custom behavior needed
- `/reload-plugins` NOT needed for pre-registered plugin agents
- Agent Teams' "do not commit" restriction does NOT apply to subagents

## Open Questions

1. How should the teammate's branch be named? Auto-generated, or story-ID based?
2. Should the skill wait for all teammates to finish, or return immediately?
3. Should the lead auto-merge, or present branches for review first?
4. How does the accept gate interact with worktree branches? Does it check sprint.md in the worktree or the main repo?
5. Should teammates get the full SMM via SubagentStart, or a trimmed version?
6. What happens if a teammate's tests pass in their worktree but fail after merge? Who fixes?

## Testing Strategy

- Unit tests for the new inline skill logic
- Integration test: spawn a teammate, verify worktree created
- Integration test: teammate commits in worktree, verify branch exists
- Integration test: lead merges branch, verify combined tests pass
- Manual test in test project with real multi-story sprint

## Dependencies

- Requires `isolation: worktree` to work reliably for plugin agents
- Requires SubagentStart dispatch table entry for `xp-teammate` (already have pattern)
- No platform changes needed — uses existing Claude Code features

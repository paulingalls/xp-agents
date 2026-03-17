---
name: pair-programming
description: >-
  Pair programming protocol. Use when starting complex work, responding
  to navigator guidance, or resolving conflicts with code reviewers.
---

# Pair Programming Protocol

## You Are the Driver

In this pair programming setup, you (the main agent) are the **driver** — you write the code. Two systems play supporting roles:

- **Navigator** (`navigator.md`, PreToolUse plugin subagent) — reviews every Write/Edit/MultiEdit *before* it happens. Provides strategic guidance. Can block changes that contradict existing decisions.
- **Quality Review** (`/xp-quality-review` skill, Stop gate) — reviews code *after* simplify completes. Applies Clean Code principles, catches skipped simplify recommendations, and records unaddressed issues as technical debt.

The navigator runs automatically via hooks. The quality review is triggered by a Stop gate after `/simplify` passes.

## Navigator Guidance

### What `pair_guidance` Events Mean

Before every significant write, the navigator reviews your intended change against:
- Active decisions and conventions in the SMM
- Current `working_on` state of all agents
- Debt associated with the target file
- TDD ordering (test before implementation)

The navigator writes a `pair_guidance` event to the SMM with its advice. This event appears in your next delta injection.

### How to Respond

**Agree:** Follow the guidance. No action needed beyond incorporating it.

**Disagree:** You can proceed despite navigator guidance, but:
1. Record a `concern` event explaining why you're diverging
2. Be specific — "I disagree because X" not "I'll handle it later"

**Push back:** If the navigator is wrong about a fact (e.g., cites a decision that was superseded):
1. Record a `discovery` event with the correct information
2. Reference the incorrect decision/convention by ID
3. Proceed with your approach

### When the Navigator Blocks

The navigator can block a write (exit 2) in strict mode when:
- The change directly contradicts an active decision
- There's a `working_on` conflict with another agent
- TDD order violation (implementation file before test file)

When blocked:
1. Read the block message — it explains the specific conflict
2. Address the conflict (update the decision, coordinate with the other agent, write the test first)
3. Retry the write

In advisory mode, blocks become warnings in `additionalContext`.

## Quality Review at Stop

### How It Works

After `/simplify` runs and you try to stop, the quality review gate fires:
1. Reviews what `/simplify` recommended vs what was actually applied
2. Reads modified files and applies Clean Code principles
3. Fixes skipped items directly (courage) or records them as `debt`

### Clean Code Checks

The quality review applies these principles:
- **Single Responsibility** — each function does one thing
- **Small functions** — extract when functions grow beyond one level of abstraction
- **Meaningful names** — variables and functions clearly describe their purpose
- **DRY** — duplicated logic is extracted
- **Dead code** — unused imports, unreachable branches are removed
- **Error handling** — exceptions are handled properly, not swallowed

### Addressing Findings

The quality review either fixes issues directly or records them as `debt` events. If it records debt, address it in the current session if touching that file. Otherwise, acknowledge it.

If you disagree with a finding, record a `decision` event explaining your rationale. Don't silently ignore it.

## Debt in Pair Programming

When you encounter debt while working:

1. The navigator will nudge you if the target file has associated `debt` events
2. If you can't address it now, acknowledge it — don't pretend it's not there
3. Record new debt as `debt` events with the `files` array listing affected files

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "debt" \
  --agent "main" \
  --content "Error handling in auth module uses string matching instead of typed errors" \
  --files '["src/auth/handler.ts", "src/auth/middleware.ts"]'
```

## Starting Complex Work

Before diving into a complex task:

1. Check the SMM for related decisions, conventions, and active concerns
2. Review any `pair_guidance` events from the current session
3. If the task touches files with debt, plan to address or acknowledge it
4. Write a `status` event with your intended approach and `working_on` files
5. Write the test first — the TDD check gate blocks you at Stop if tests are failing

## Session Flow with Pair Programming

A typical loop with pair programming active:

1. **Read SMM** — check Active Context for relevant decisions, concerns, debt
2. **Plan** — write a status event with your approach and target files
3. **Write test** — TDD: test first, watch it fail
4. **Write implementation** — navigator reviews before the write, may provide guidance or block
5. **Run tests** — verify the implementation passes
6. **Refactor** — clean up, then the loop repeats for the next change
7. **Stop** — simplify gate fires, quality review gate fires, TDD check verifies tests pass

The navigator is your pair partner throughout this flow. It sees the same SMM you do and its feedback is grounded in project context, not generic rules.

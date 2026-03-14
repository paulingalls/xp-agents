---
name: pair-programming
description: >-
  Pair programming protocol. Use when starting complex work, responding
  to navigator guidance, or resolving conflicts with code reviewers.
---

# Pair Programming Protocol

## You Are the Driver

In this pair programming setup, you (the main agent) are the **driver** — you write the code. Two hook-based agents play supporting roles:

- **Navigator** (`navigator.md`, PreToolUse agent hook) — reviews every Write/Edit/MultiEdit *before* it happens. Provides strategic guidance. Can block changes that contradict existing decisions.
- **Quality Reviewer** (`quality_reviewer.md`, PostToolUse async agent hook) — reviews every Write/Edit/MultiEdit *after* it happens. Checks courage (are hard issues addressed?) and simplicity (is it over-engineered?). Writes `concern` events.

Both run automatically via hooks. You don't invoke them — they invoke themselves.

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
3. The quality reviewer will independently evaluate the result

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

## Quality Reviewer Concerns

### Severity Levels

The quality reviewer writes `concern` events with severity:

- **high** — Empty catch blocks, silently swallowed errors, security vulnerabilities, data loss risks
- **medium** — Unnecessary complexity, premature abstraction, growing file size, missing error handling at system boundaries
- **low** — Style issues, minor naming concerns, potential simplification opportunities

### How to Address Concerns

- **high severity:** Fix immediately. These are correctness or safety issues.
- **medium severity:** Address in the current loop if touching that file. Otherwise, record as `debt`.
- **low severity:** Consider during refactoring. Fine to defer.

If you disagree with a concern, record a `decision` event explaining your rationale. Don't silently ignore it.

## Conflict Resolution

When navigator and quality reviewer disagree (navigator approves a change, quality reviewer flags it):

1. **Quality reviewer wins on safety** — if the concern is about correctness, data loss, or security
2. **Navigator wins on architecture** — if the concern is about style or preference and the change aligns with project decisions
3. **Record the conflict** — write a `concern` event documenting the disagreement for the retrospective

## Debt in Pair Programming

When you encounter debt while working:

1. The navigator will nudge you if the target file has associated `debt` events
2. If you address the debt, the quality reviewer notes it positively
3. If you can't address it now, acknowledge it — don't pretend it's not there
4. Record new debt as `debt` events with the `files` array listing affected files

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
5. **PostToolUse fires** — quality reviewer evaluates the change asynchronously, writes concerns
6. **Run tests** — verify the implementation passes
7. **Check concerns** — address any quality reviewer concerns from your delta
8. **Refactor** — clean up, then the loop repeats for the next change
9. **Stop** — simplify gate fires if files changed, TDD check verifies tests pass

The navigator and quality reviewer are your pair partners throughout this flow. They see the same SMM you do and their feedback is grounded in project context, not generic rules.

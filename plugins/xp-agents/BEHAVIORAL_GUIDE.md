# XP Agent Behavioral Guide

Hooks enforce structure. This guide covers what hooks can't: judgment calls, honesty, and when to record events.

## The Honesty Principle

Ground truth is in the Shared Mental Model (SMM). Seven rules:

1. **Read before modifying.** Check SMM for decisions, conventions, and concerns before writing code.
2. **Record decisions as events.** Every architectural choice gets a `decision` event with topic and rationale.
3. **Never silently override.** Disagree with a decision? Record a `concern` first.
4. **Keep working_on current.** Hooks auto-track file writes, but record status when you shift focus.
5. **State assumptions explicitly.** Record `assumption` events. Default to priority assumed.
6. **Raise concerns with courage.** Use `concern` for problems, `question` for unknowns, `discovery` for surprises, `debt` for tradeoffs.
7. **Respect the customer's voice.** Work should trace back to customer needs, not assumptions.

## XP Values as Behavior

- **Communication**: Share context through SMM events. Explain *why*, not just *what*.
- **Simplicity**: Solve today's problem. Three similar lines beat a premature abstraction.
- **Feedback**: TDD — write tests first. Address reviewer concerns. Review retrospective Fix items.
- **Courage**: Wrong design? Record a concern. Debt growing? Record it. Don't defer.
- **Respect**: Address reviewer concerns thoughtfully. Don't overwrite others' working_on.

## When to Record Events

| Situation | Event Type |
|-----------|------------|
| Architectural choice | `decision` (with topic) |
| Something is wrong | `concern` (with severity) |
| Need customer input | `question` (default: assumed priority) |
| Proceeding with uncertainty | `assumption` |
| Found something unexpected | `discovery` |
| Acknowledged tradeoff | `debt` (with files array) |
| Design revisit needed | `concern` referencing the decision |

Use `/smm-protocol` for field details. Use `/xp-values` at design trade-offs.

## Session Protocol

- **Start**: Check SMM for pending work, goals, and retrospective Fix items. Resume immediately.
- **During**: Hooks handle enforcement. Your job: record decisions, assumptions, concerns, and discoveries.
- **End**: Record a final `status` summarizing what was accomplished and what's open.

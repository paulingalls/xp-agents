# Security-review swap + close-reviewer marker

**Plugin:** `xp-agents`
**Origin:** sprint-062 kickoff discussion (2026-05-04). Concern `ecc527295e8a` (security-review delegation stalls) has been deferred for 3 sessions; this captures a concrete design.
**Status:** Draft — feed into next `/xp-sprint-start` planning.
**Resolves:** `ecc527295e8a` (close-skill /security-review delegation stall)

## Why

In v3.1 the close skills (`xp-{free,sprint,plan}-close`) run Step 4.5 = `/security-review` AFTER the close-reviewer subagent. This was set by decision `0fdb19d1995d` ("xp-close-reviewer is quality-only across ALL modes; security review fires from each close skill's Step 4.5") to keep security signals off the close-reviewer's plate.

The downstream stall: the existing PostToolUse:Skill nudge for /security-review fires at **skill-load time** (when the Skill tool returns instructions), not when the agent finishes acting on them. By the time SECURITY_COMPLETE actually fires, the "resume close" nudge has scrolled out of attention. The close cycle stalls after security review until the user notices and prompts "continue".

Two prior attempts (nudge + tighter context injection) didn't move adoption — the underlying issue is that the agent has nothing forcing it back to the close cycle.

## Design

**Two changes, neither sufficient alone:**

1. **Swap order in close skills.** `/security-review` runs FIRST, then close-reviewer. The close-reviewer becomes the LAST step before merge — finishing it is the natural "ready to merge" handoff.

2. **Marker-gated Stop.** When the close skill invokes `/security-review`, the close skill itself writes a marker (NOT the generic PreToolUse:Skill hook — that loses context about why /security-review was invoked). A new Stop hook checks for the marker; if present, blocks Stop with `decision: "block"` + reason "Run the close-reviewer next; the close cycle is mid-flight (marker present)". The close-reviewer agent (or its SubagentStop hook) consumes the marker.

After close-reviewer completes → marker gone → Stop proceeds → agent returns to the close skill's remaining steps (commit / merge).

### Why both pieces are needed

- **Swap alone**: the current stall happens AFTER /security-review starts. Swapping order without the marker just moves the stall earlier — the agent forgets to invoke close-reviewer next.
- **Marker alone**: with the current order (close-reviewer first), the marker has no obvious automatic consumer. Security-review's own completion would have to clear it, and the agent still has to remember "go run merge" — same forgetting problem.

The combination works because the marker has an automatic consumer (close-reviewer) AND that consumer is positioned at the natural endpoint.

## Trade-offs accepted

**Close-reviewer fix-cycle skips re-security-review.** Close-reviewer findings can produce code edits from the main agent. With the swap, those fixes ship without security re-review. We accept this:
- Close-reviewer flags XP-value / simplify / drift / debt patterns, not security patterns. Security risk in fix-cycle code is low.
- Security gaps that slip here get caught at the next plan-level review (Tier 3 close-reviewer at sprint-close, or independent /security-review at /xp-plan-close).
- Adding "security re-review on close-reviewer fixes" would mostly defeat the swap's simplicity.

## Out of scope (deferred)

- **Manual /security-review invocation outside close cycles**: marker is written by the close skill, not the security-review tool itself, so manual /security-review runs don't write a marker. No Stop block, no orphan state. (This is why "close skill writes the marker" is non-negotiable — it sidesteps the manual-invocation case cleanly.)
- **Marker timeout / session-bounded TTL**: not needed — marker is consumed deterministically by close-reviewer in the same session. If the user kills the session mid-close, the marker becomes stale; cleanup belongs to a SessionStart hook or a `/xp-{type}-close --resume` flag (separate work).

## Implementation sketch (story-sized)

### Story-A — Swap step order in close skills

- **File domain:** `plugins/xp-agents/skills/xp-{free,sprint,plan}-close/SKILL.md` — move Step 4.5 (`/security-review`) to BEFORE the close-reviewer dispatch
- **Tests:** assertion in `test_plugin_integrity.py` that the security-review step number is < the close-reviewer dispatch step number in each close skill
- **Doc:** update decision `0fdb19d1995d` (or supersede with new decision) to reflect the new order

### Story-B — Marker write + Stop block + close-reviewer consume

- **File domain:**
  - `plugins/xp-agents/scripts/_close_pipeline_shared.md` (or per-close skill) — call to write marker before `/security-review` invocation
  - `plugins/xp-agents/scripts/stop_close_marker.py` (NEW) — Stop hook that checks marker presence, blocks with reason
  - `plugins/xp-agents/hooks/hooks.json` — register the new Stop hook
  - close-reviewer agent prompt or SubagentStop — consume the marker on completion
- **Tests:** `tests/hooks/test_stop_close_marker.py` — marker present → block; marker absent → pass-through; close-reviewer subagent completion → marker consumed
- **Marker location:** `${SMM_DIR}/.close-cycle-active` (presence-only per constraint `1282264150f5`)

### Story-C — Doctrine + acceptance test

- Update PROCESS_GUIDE.md to describe the new order + marker semantics
- Capstone integration test: drive a full close cycle from `/xp-free-close`, assert /security-review fires first, assert close-reviewer fires second, assert no Stop stall in between

## Sequencing notes

- A → B are tightly coupled; same sprint or even same story
- C can defer to a follow-up
- All three are dep-free with sprint-062's stories (no file overlap)

## Provenance

- Concern raised originally as `ecc527295e8a` (3 sessions ago)
- User design proposed in sprint-062 kickoff conversation
- Critical design Q&A: (1) close-reviewer fix-cycle skip — accepted; (2) manual invocation — sidestepped via "close skill writes marker"

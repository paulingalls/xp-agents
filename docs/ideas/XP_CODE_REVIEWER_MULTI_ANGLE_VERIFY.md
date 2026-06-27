# Strengthen xp-code-reviewer: multi-angle finders + independent verify

> **Status: Proposed — not implemented.** Design source for a future `/xp-plan`
> milestone. Authored 2026-06-26 after the v3.11.1 close caught two confirmed
> regressions that the per-increment review layer missed.

## Problem (with hard evidence)

Per increment, `/xp-quality-review` spawns a **single** `xp-code-reviewer` agent
that does one self-find pass over the diff (correctness + drift + debt +
reuse/quality + XP lenses). The v3.10.0 cost rework deliberately made this the
cheap path and moved the expensive multi-agent `/code-review` to a once-at-close
gate.

This session produced a hard datapoint that the cheap pass is **structurally too
weak for subtle state-machine interactions**: two CONFIRMED correctness
regressions (`d69748e92ad1` — a stop gate that can latch off forever;
`8e0264cfcf43` — an accept marker that never drains mid-sprint) sailed through
**three** independent cheap reviews — `/xp-review-plan`, *both* experiment
teammates' `xp-code-reviewer` (Opus *and* Sonnet wrote the same flawed code),
and the `xp-close-reviewer` — and were caught **only** by the broad
`/code-review high` workflow at close. This is not an Opus-vs-Sonnet gap; it is a
gap in the single-pass review *structure*.

## What makes /code-review catch what the single pass misses

`/code-review` (workflow-backed at `high`) is not "a bigger reviewer" — it is a
different *structure*:

1. **Multiple angle-specific finder agents** (one per review angle), each looking
   for one failure class, blind to the others.
2. **Pool the candidates** across finders.
3. **An independent verifier per distinct `(file, line)`** that tries to *refute*
   each candidate before it is reported.
4. **Rank + cap** the survivors.

The angle-diversity surfaces failure modes a single generalist pass rationalizes
away; the independent verify kills the false positives that diversity creates.
That find-then-adversarially-verify shape is what caught the two regressions.

## Proposal: bring a *lightweight* version of that structure to the per-increment review

Not the full 18–100-agent fan-out (that is exactly the cost v3.10.0 stripped) —
a **middle**: a handful of angle finders + a verify pass, cheap enough to run per
increment, structured enough to catch state-machine interactions.

Shape options to weigh in the milestone:
- **A) `xp-code-reviewer` spawns its own sub-agents.** Since teammates now load
  the plugin and can spawn agents, the single `xp-code-reviewer` could fan out a
  few internal finders (e.g. correctness / state-&-lifecycle / drift) and run a
  self-verify pass before reporting. Keeps the `/xp-quality-review` contract.
- **B) Restructure `/xp-quality-review`** into a mini find→verify pipeline (a few
  finder calls + a verifier call), closer to `/code-review`'s shape but bounded.
- **C) Risk-gated escalation.** Run the single pass by default; escalate to the
  multi-angle+verify shape only when the diff touches high-risk surfaces (stop
  gates, markers, the review-cycle state machine) — detected by changed-file path
  or a cheap classifier. Spends the extra finders only where this session's bugs
  actually live.

## The cost tension (must be navigated, not ignored)

v3.10.0's whole point was a cheap per-increment review + one expensive close pass.
This proposal adds cost back to the per-increment path. The lesson is **not**
"make per-increment as expensive as `/code-review`" — it's "raise the *floor* of
the cheap pass so fewer regressions reach the close backstop." Targets:
- Keep the per-increment budget bounded (a few finders + one verify, not dozens).
- Option C (risk-gating) is the most cost-faithful — most diffs stay single-pass.
- The close `/code-review high` stays the backstop regardless (this session
  reconfirmed it earns its cost at the release gate).

## Open questions

- How many finders, and which angles? (Correctness + a dedicated **state/lifecycle
  /concurrency** angle is the one that would have caught both regressions.)
- Verifier shape: one refuter per finding (like `/code-review`), or a single
  verify pass over all candidates? Adversarial "default to refuted" framing?
- Where does it live — inside the `xp-code-reviewer` agent (option A) or the
  `/xp-quality-review` skill (option B)?
- Does it run every increment (A/B) or only on risk-gated diffs (C)?
- Token budget per increment, and how it interacts with teammate-delegated runs
  (the reviewer sub-agents already run on the opus tier).

## Suggested milestone shape (starting decomposition for /xp-plan)

1. Add a dedicated **state/lifecycle/concurrency** review angle to
   `xp-code-reviewer` (the gap that missed both regressions) — cheapest first win.
2. Add a bounded self-verify pass (adversarial refute) before the reviewer reports.
3. Risk-gate the full multi-angle escalation on changed-file surface
   (gates/markers/state machines).
4. Measure: re-run this session's two regressions (and a few seeded
   state-machine bugs) through the enhanced per-increment review; confirm it
   catches them without the close `high` pass.

## Related

- The close-effort question (keep `high` at close, threshold-gated) is settled by
  this session's evidence — `high` caught what the cheap layer missed. A
  complementary **size-graduated effort ladder** (skip / medium / high by diff
  size) is a separate, lower-priority lever; this enhancement raises the *floor*,
  the ladder tunes the *ceiling*.
- [[docs/ideas/TEAMMATE_PLANNING_PIPELINE.md]] — the other systemic-quality idea
  from this session (deep per-story planning for parallel teammates).

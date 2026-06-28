# Strengthen xp-code-reviewer: multi-angle finders + independent verify

> **Status: Sprint-103 attempted, fully abandoned mid-close. Defer to sprint-104+ with a real plan cycle from scratch.** See "What sprint-103 taught us" at the bottom of this file.
>
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
- [[docs/completed/TEAMMATE_PLANNING_PIPELINE.md]] — the other systemic-quality idea
  from this session (deep per-story planning for parallel teammates).

---

## What sprint-103 taught us (2026-06-27, abandoned mid-close)

Sprint-103 attempted this proposal end-to-end and was fully abandoned at close
time after the close gate caught architecture-level holes the inline review
couldn't. All three stories rolled back to deferred; v3.11.1 stays the
shipped release. Capturing the lessons here so the sprint-104 redo doesn't
repeat them.

### The three architectural reworks (in one sprint, all at close time)

1. **Regex classifier (story-002 as shipped)** — A Python regex-based content
   classifier scored each changed `.py` file against state-field density, exit
   blocks, lock primitives, lifecycle pairs, async complexity. Close-time
   `/code-review high` found 10 bugs in it + the meta-issue: **Python-only**.
   The plugin ships to projects in any language; a `.py`-suffix-gated
   classifier silently returns RISK=low for every TS/Rust/Go diff. Third
   "plugin-project-agnostic" leak this sprint after story-001 prose + story-002
   AC. **The principle we added (vocabulary-only) didn't catch coverage leaks.**
2. **LLM-judged classifier (mid-sprint pivot)** — Replaced the regex with
   `agents/xp-risk-classifier.md` (haiku tier) spawned via the standard Agent
   tool. Cross-language by judgment, no API keys, no per-language regex chase.
   The right pivot — but coupled to a 3-spawn parallel fan-out on RISK=high
   that close-time `/code-review high` then found 10 MORE bugs in.
3. **Single-spawn-enriched (proposed but never landed)** — Drop the fan-out;
   route RISK=high by enriching the single reviewer's prompt with explicit
   angle directives. Avoided 6/10 of the fan-out's issues. Plan-reviewer caught
   2 more gaps (sprint.json AC drift, milestone-1 done unproven under new
   shape). At that point sprint was reworking the same surface for the THIRD
   time at close. Aborted.

### The pattern (real cost)

**Rush past planning → close-time bug discovery → architectural rework → repeat.**

Each rework cycle:
- Cost: full /security-review + /code-review high workflow + xp-code-reviewer
  validation + commits + plan-review (eventually) + this retrospective writeup
- Real-time cost: hours per rework
- Token cost: 1.7M+ subagent tokens for ONE /code-review high pass; we ran two

We did three reworks in one sprint. The close gate worked — it caught real
bugs every time — but the gate is the wrong place to discover that the
architecture is wrong. Plan-review is the right place; we skipped it for
story-002 (jumped straight from approval to implementation) AND for the
mid-sprint LLM-classifier pivot AND for the single-spawn redesign. Every
time, the same anti-pattern surfaced more bugs.

### What was actually good and should survive into sprint-104

- **LLM-judged classifier** (cross-language by judgment, no API keys, standard
  Agent tool plumbing) is the right shape. Keep `agents/xp-risk-classifier.md`
  as a starting point — it had the right output contract (RISK=high|low +
  SIGNALS=) and the anti-prompt-injection clause.
- **State/lifecycle/concurrency review angle** (story-001) is the right addition
  to xp-code-reviewer.md's Section 1. The vocabulary cleanup made it
  cross-language. Keep.
- **Bounded self-verify pass** (story-001 Section 1b) had the right intent.
  Need a category-based spare-clause (sparse state-findings, refute style
  nitpicks), NOT an uncertainty-based default-refuted bias.
- **single-spawn-enriched** beats 3-spawn fan-out. The fan-out had irreducible
  coordination races (filesystem writes, SMM appends, exact-tuple dedupe
  failure, angle prompt key mismatch). Single spawn with a `## Review Focus`
  block in the prompt + an agent-prose clause recognizing the block: cleaner,
  no races.

### What was wrong that the sprint-104 plan must address upfront

- **Plan cycle BEFORE every substantive design choice.** Including the
  classifier shape, the routing shape, the agent tool surface, the output
  contract. Plan-reviewer catches architecture; /code-review catches
  implementation.
- **MODE-gate Step 1.4 (classifier spawn) on consume-findings** — close already
  ran /code-review; extra classifier call is wasted.
- **Strict first-line output parse** for the classifier (narrative tails
  legitimately contain "RISK=high" as prose; substring search is wrong).
- **Read-only tool surface for the classifier** (untrusted file content + Bash
  is a prompt-injection vector; the diff is in the prompt anyway).
- **sprint.json AC + execution_plan.json status must follow the actual shipped
  shape.** Sprint-103 marked stories done with AC text describing architecture
  that didn't exist by the time we tried to close.
- **Don't mark milestone delivered until its empirical proof exists under the
  shipped shape.** Story-003 proved milestone-1 catches regressions under
  3-spawn fan-out. When we proposed single-spawn-enriched, that proof was
  invalidated — but we had already marked milestone-1 delivered. Tighten.

### The cross-language leak pattern (now a load-bearing principle)

Three leaks in one sprint, none caught by review:
1. story-001 prose used `--no-ff merge` and other xp-agents-specific examples
   as the *rule*, not as illustrative examples.
2. story-002 AC text named xp-agents' own gates/markers/state-machine paths as
   the rule the classifier should match against, instead of as test fixtures.
3. story-002 implementation was Python-only via `.py` suffix check, not
   project-agnostic.

The principle-and-Constraint pair we added covered (1) and (2) (vocabulary)
but not (3) (language coverage). The principle is now strengthened to cover
BOTH; CLAUDE.md adds a prominent callout so future devs and assistants see it
without having to remember the doc.

The cross-language rule, plainly stated: **shipped plugin functionality must
work on ANY language the user's projects use, not just the language the plugin
is written in. Language-specific implementation (regex / parser / tool) is a
leak; language-aware judgment (LLM) or language-agnostic structural signals
are not.**

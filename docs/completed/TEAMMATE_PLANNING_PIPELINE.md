# Pipelined Per-Story Teammate Planning

> **Status: Proposed — not implemented.** This is a design source for a future
> `/xp-plan` milestone, capturing a reshape of the parallel-teammate workflow.
> It is not shipped behavior. Authored 2026-06-26 from the v3.11.0 session's
> Opus-vs-Sonnet delegation experiments.

## Problem

Parallel teammates today all draw their prompts from a **single** plan-mode
session and a **single** `/xp-review-plan` pass: `/xp-schedule` promotes the
whole disjoint frontier as a teammate batch, the lead plans the batch once, then
`/xp-assign` mechanically splits that one plan into N per-teammate prompts and
spawns them.

Consequence: **per-story planning attention ≈ plan_depth / N.** The more stories
parallelized, the thinner the instructions each teammate receives, and the
single batch review cannot scrutinize each split prompt the way it scrutinizes a
solo-story plan.

This is a latent weakness *today* (Opus teammates tolerate thin prompts
gracefully), but it becomes load-bearing if teammates run on a cheaper model
(e.g. Sonnet) whose success depends on instruction clarity. The session's
experiments are the evidence base: a Sonnet teammate **matched Opus** on
correctness and judgment — but only because each got a *single, deeply-reviewed*
plan, and `/xp-review-plan` caught real load-bearing bugs in the lead's plan
*before* handoff (round 2: a `has_reviewing` vs `has_under_acceptance` signal
trap; round 3: predicate-duplication + agent_id-keying gaps). The review is the
safety mechanism, and it must scale with the fan-out.

## Proposed approach

Replace "plan the batch once, split N ways" with a **pipeline**: keep the
batch-level file-domain analysis up front (for conflict safety), then loop
per story — full solo-depth planning, then async launch — so each teammate is
born from its own dedicated plan + review while earlier teammates already
execute in the background.

```
/xp-schedule  → establish the disjoint frontier + per-story file_domains (batch-level, ONCE)
for each story in the frontier:
    EnterPlanMode  → plan THIS story at solo depth (lead interactive, AskUserQuestion in the loop)
    /xp-review-plan → hard review of THIS story's plan
    (decide executor model here — see "Model routing")
    spawn_teammate (async, --plugin-dir, chosen --model)   # launches; does NOT block
    → continue to the next story while this teammate runs
accept/close each teammate per story as it finishes (existing /xp-accept → /xp-story-close)
```

Essentially: **solo-depth planning + parallel async execution.** A synthesis of
the two existing modes rather than a third one bolted on.

### Why this over "review the split prompts"

An alternative is to keep the single batch plan but fan out the *review* across
the N split prompts. The pipeline is better because it fixes quality **at the
source** — each story gets a full *interactive* plan-mode session, so a thin
prompt is never created and then rescued. Quality at the source beats
quality-gating after.

### Model routing falls out for free

Because each story is planned interactively, its clarity/risk is visible *as it
is planned*. The lead picks the executor right there: crisp + mechanical +
well-AC'd → cheaper model (Sonnet); fuzzy, novel, or high-blast-radius →
Opus, or kept solo. No separate scoring step — **the planning is the triage.**

## Prerequisite: keep the batch file-domain pre-pass

Parallel safety depends on **disjoint `file_domain`s** (no merge conflicts), and
that is inherently a batch-level analysis — all N stories' domains must be known
before *any* teammate launches, or the lead could deep-plan and launch story 1,
then discover story 4 touches the same file. So `/xp-schedule` / `xp-sprint-start`
must still establish disjoint domains across the frontier **once, up front**;
the per-story plan→review→launch pipeline runs *on top of* those guaranteed
domains. Planning depth comes per story; conflict safety comes from the batch
pre-pass.

## Tradeoffs and mitigations

- **Serialized planning (slower to fully launch).** Execution overlaps planning
  (teammate 1 runs while the lead plans 2…N), but the lead plans stories
  sequentially, so the last teammate starts later than a big-bang launch. The
  delta ≈ the extra planning depth — which *is* the attention being bought.
  *Mitigation / tuning:* pipeline the complex stories; big-bang a cluster of
  trivial, crisp ones. Depth-on-demand.
- **"Some teammates finish before others start" — a feature, not a bug.**
  Staggered completion maps directly onto the existing per-story merge model:
  `/xp-accept` → `/xp-story-close` already merges **per story as each lands**. A
  teammate finishing early is just an early, clean, isolated merge — more natural
  than big-bang (where all N finish together and you merge a pile).
- **Lead context accumulation.** N sequential plan-mode sessions pile into the
  lead's context. *Mitigation:* cap N per pipeline (wave them); or for the
  trivial tail, delegate per-story planning to a `Plan` sub-agent and review its
  output (trading some interactivity back).

## Structural changes (where the work lands)

- `/xp-schedule` — promote the frontier and lock per-story file domains, but
  stop short of triggering a single batch plan.
- `/xp-assign` (or a new per-story driver) — becomes a **per-story** spawn called
  repeatedly, interleaved with per-story planning, instead of "split one plan +
  spawn all at once." The spawn mechanism (`spawn_teammate.py`, already
  per-teammate) is reused as-is.
- The plan cycle (`EnterPlanMode` → `/xp-review-plan`) is invoked once per story
  inside the loop rather than once for the batch.
- Per-story executor-model selection (the routing decision) needs a place to be
  recorded (e.g. each story's `execution_mode` / a new model field).

## Evidence and open questions

- **Evidence so far (v3.11.0 session):** three `1 plan : 1 task : 2 executors`
  A/B rounds. Sonnet matched Opus on correctness/judgment on deeply-reviewed
  single-story plans; cost ~wash on a trivial task, ~18% cheaper on a bigger one
  (Sonnet uses more turns/time). The deep plan + hard review was the load-bearing
  precondition every time.
- **The missing datapoint:** we have **zero** data on the `1 plan : N tasks`
  thinning effect itself. The decisive validation is a **real ≥3-story parallel
  batch on Sonnet**, measured *with* vs *without* this pipeline — to see where
  per-story thinness bites and whether per-story planning closes the gap. Do this
  before committing to the reshape.
- **Coordination-hook hole (observed).** When two teammates' domains overlap,
  the `PreToolUse:Edit` coordination guard blocks the second editor — and a
  teammate can bypass it via `Bash` (observed in round 3, debt `6e462b1b6e54`).
  Disjoint per-story domains make this rare, but the Bash-bypass hole is worth
  closing independently.
- **Escalate-on-ambiguity (complementary).** A headless teammate that finds its
  instructions too ambiguous to proceed confidently should record a blocking
  concern and **stop**, rather than guess — letting the lead re-plan that story.
  A safety net that bounds the downside of any residual thin prompt, independent
  of this pipeline.

## Suggested milestone shape (starting decomposition for /xp-plan)

1. Batch domain pre-pass in `/xp-schedule` decoupled from batch planning.
2. Per-story plan→review→async-spawn loop (the core reshape of `/xp-assign`).
3. Per-story executor-model routing + recording.
4. Escalate-on-ambiguity teammate protocol (+ close the Edit-coordination Bash
   bypass).
5. Validation: a real ≥3-story Sonnet batch, pipeline vs batch, measured.

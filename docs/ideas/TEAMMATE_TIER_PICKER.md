# Teammate tier picker (per-story executor_model recommendation)

**Status:** idea
**Source:** sprint-107 story-005 close-time conversation (post-validation discussion)
**Files in scope:** `plugins/xp-agents/agents/xp-plan-reviewer.md`; `plugins/xp-agents/skills/xp-schedule/SKILL.md`; `plugins/xp-agents/skills/xp-assign/SKILL.md`; `plugins/xp-agents/skills/xp-sprint-start/SKILL.md`; `plugins/xp-agents/smm/system_context_*.py`

## What the tier picker does

Recommends an `executor_model` per story so teammate spawns run at the right tier (haiku for mechanical, sonnet for pattern-following, opus for architecture-heavy), with a "run solo in-agent" option for trivial stories where spawning a fresh teammate is pure overhead. Today every teammate inherits the orchestrator's model — there is no per-story tier selection in practice, and the existing `executor_model` schema slot (story-002 of sprint-105) is dead in production because nothing recommends or sets it.

## Why now

Sprint-107 ran 3 parallel teammates all on Opus 4.7 [1M] (kept uniform for clean baseline; see [V4_TEAMMATE_PIPELINE_VALIDATION.md](V4_TEAMMATE_PIPELINE_VALIDATION.md)). Observed costs: story-003 (79 LOC, mechanical) at $2.12; story-002 (600 LOC, pattern-following) at $11.95. Story-003 on Haiku would have been ~$0.20 + the fixed spawn cost. Story-002 on Sonnet would have been ~30-40% of the Opus cost. The tier choice is real money, and right now the system doesn't make it.

The risk-classifier rubric-broadening proposal ([RISK_CLASSIFIER_RUBRIC_BROADENING.md](RISK_CLASSIFIER_RUBRIC_BROADENING.md)) is a sibling concern but different agent and different decision point — that's about elevating review focus at close-time. This doc is about choosing the tier at spawn-time.

## Architectural shape

**xp-plan-reviewer recommends the tier** — same agent already reading the plan + story context + system_context for concerns. Adding a tier judgment is incremental on its existing work, costs no new agent spawn, and Opus has the depth for nuanced calls.

The diff-time `xp-risk-classifier` (Haiku) keeps its existing job (SIGNALS for review-focus enrichment) and does NOT get involved here. Two agents, two decisions, no shared rubric vocabulary, no drift risk.

## Three pieces

### 1. Disable flag (smallest; defensive)

A `teammates_disabled` boolean on `system_context.json` (or `XP_TEAMMATES_DISABLED=1` env). When true:
- `/xp-schedule` always picks solo (auto-solo when teammates disabled, even on a disjoint parallel frontier)
- `/xp-assign` refuses with a one-line hint to flip the flag if the lead invokes it anyway

Costs nothing today; saves users when `claude -p` pricing changes (e.g. if it stops being subscription-included).

### 2. Per-sprint default executor_model

Asked once at `/xp-sprint-start`:

> Default teammate model for this sprint? (haiku / sonnet / opus / inherit-orchestrator)

Stored on `sprint.json` as a top-level `default_executor_model` field. Becomes the floor for all teammate spawns; per-story override only when plan-reviewer recommends differently AND the divergence is significant.

### 3. xp-plan-reviewer tier recommendation event

The load-bearing piece. Plan-reviewer already runs after every plan; adding a recommendation is a prose-only edit + one event write.

**xp-plan-reviewer.md addition (~10 lines of prose):**

> After reporting concerns/assumptions/decisions, judge story complexity and write ONE decision event for the tier recommendation. Heuristics:
> - **in-agent** when: <100 LOC AND single file AND mechanical (rename, format, port)
> - **haiku** when: 100-300 LOC AND no judgment surface (mechanical refactors, well-templated additions)
> - **sonnet** when: 300-800 LOC AND pattern-following (mirrors existing code, schema additions following a precedent)
> - **opus** when: >800 LOC OR novel architectural surface OR cross-module integration
>
> If the plan is genuinely ambiguous on tier, OMIT the event — the lead falls back to sprint default. Do NOT guess.

**Event shape:**

```json
{
  "type": "decision",
  "agent_id": "xp-plan-reviewer",
  "topic": "tier-recommendation-story-NNN",
  "content": "Suggested executor_model: <tier> — <one-sentence rationale>",
  "metadata": {
    "recommended_model": "haiku" | "sonnet" | "opus" | "in-agent",
    "story_id": "story-NNN",
    "advisory": true
  }
}
```

**Why an SMM event instead of just the reply text:** plan-reviewer's reply is suppressed (debt `5e180220db1a` — main agent has to dig review concerns from events.jsonl today). The recommendation MUST survive that suppression. Writing the event makes the recommendation:
- Discoverable by `/xp-schedule` and `/xp-assign` via topic-based query
- Durable for retro analysis (recommendation accuracy over time can train the rubric)
- Auditable when the lead overrides

### Consumer side (xp-schedule + xp-assign)

Both skills add a "tier resolution" step that:
1. Reads sprint.json `default_executor_model` (floor).
2. Reads most recent `tier-recommendation-<story-id>` decision event (override candidate).
3. If recommendation present AND differs from default by ≥1 tier AND no `auto-apply-tier-recommendations` flag set → AskUserQuestion: "Apply recommendation X or keep default Y?"
4. If recommendation matches default (or no recommendation) → silent apply.
5. If `executor_model` already set on story (manual override) → respect it, skip the resolution.
6. Write tier choice to story via `sprint_cli edit-story <id>` with `{"executor_model": "<tier>"}`.

**Override audit:** when the lead picks a tier different from plan-reviewer's recommendation, write a sibling event:

```json
{
  "type": "status",
  "agent_id": "main",
  "content": "tier-override story-NNN: chose <picked> over recommended <reviewer>",
  "metadata": {
    "action": "tier_override",
    "story_id": "story-NNN",
    "picked": "...",
    "recommended": "..."
  }
}
```

Retro tooling samples these to compute recommendation acceptance rate.

## Cost reality check

Plan-reviewer's addition: ~10 prose lines + 1 SMM event write per story. Zero new subagent spawns. Negligible token cost (Opus already loaded the plan; adding the tier line costs <100 output tokens per story).

vs the avoided cost: one mis-tiered Opus spawn for a $0.30-of-Haiku-work story is ~$3-7 wasted. Even one correct downgrade per sprint pays for the whole feature 100×.

## When to ask vs auto-apply

- **Always ask at /xp-sprint-start** — sprint default is a one-time call, sets the floor.
- **Silent apply at /xp-schedule + /xp-assign** when recommendation matches default OR matches an explicit per-story override.
- **Ask only when recommendation diverges from default by ≥1 tier** AND a `silent-tier-overrides` flag isn't set.
- **Never ask twice for the same story** — first answer sticks for the sprint's life.

Goal: keep the pipeline moving automatically in the common case; surface a question only when the cost delta is real and the customer might disagree.

## Coupling to existing debts

This feature depends on (and motivates fixing):

- `5e180220db1a` — xp-plan-reviewer output suppression. Without the SMM-event backup, the recommendation would just disappear when reply is suppressed. Writing the event makes the suppression less critical, but fixing the suppression is still worthwhile for the human-readable surface.
- `.assign-pending` solo-leak (no debt id yet — surfaced this session). Solo stories don't go through xp-assign today; if the recommendation is "spawn solo teammate at tier X", we'd want a path that promotes solo + spawns a teammate at the chosen tier. The current "/xp-schedule branches solo directly, no spawn" path needs an extension.

## Out of scope

- The xp-risk-classifier rubric broadening lives in its own doc ([RISK_CLASSIFIER_RUBRIC_BROADENING.md](RISK_CLASSIFIER_RUBRIC_BROADENING.md)). Different agent, different decision point, different vocabulary. No coupling needed.
- Auto-learning from override accuracy (training the rubric from retro data) is a longer-horizon idea. Land the manual path first; collect 1-2 sprints of data; then decide if auto-tuning earns its complexity.
- Per-tier prompt customization (give Haiku teammates terser prompts than Opus) — separate concern; tier picker is just selecting the model, not reshaping the prompt.

## Acceptance ideas (for the implementation story)

- xp-plan-reviewer prose contains the 4-tier heuristic table and writes a `tier-recommendation-<story-id>` decision event per reviewed plan (when the plan is unambiguous).
- /xp-schedule reads the recommendation, applies silently when matches default, asks when diverges.
- /xp-assign respects existing `executor_model` story field (manual override beats recommendation).
- /xp-sprint-start asks the default-tier question and writes `default_executor_model` to sprint.json.
- `teammates_disabled` flag in system_context.json forces solo at /xp-schedule.
- Override events have `metadata.action=tier_override` for retro accuracy analysis.
- AC: replay sprint-107's plan-review events with the new prose → assert tier recommendations match the post-hoc complexity table in V4_TEAMMATE_PIPELINE_VALIDATION.md (haiku for story-003, sonnet for story-002, opus for story-001 + 004).

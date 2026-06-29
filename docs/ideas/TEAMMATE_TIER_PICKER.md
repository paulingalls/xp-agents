# Teammate tier picker (kickoff bundle + universal /xp-assign + plan-reviewer recommendation)

**Status:** idea
**Source:** sprint-107 story-005 close-time conversation (post-validation discussion)
**Files in scope:** `plugins/xp-agents/skills/xp-kickoff/SKILL.md`; `plugins/xp-agents/agents/xp-plan-reviewer.md`; `plugins/xp-agents/skills/xp-schedule/SKILL.md`; `plugins/xp-agents/skills/xp-assign/SKILL.md`; `plugins/xp-agents/scripts/marker_names.py` + `markers.py`

## What the tier picker does

Recommends an `executor_model` per story so teammate spawns run at the right tier (haiku for mechanical, sonnet for pattern-following, opus for architecture-heavy), with `in-agent` as a first-class option for trivial stories where spawning a fresh teammate is pure overhead. Today every teammate inherits the orchestrator's model — there is no per-story tier selection in practice, and the existing `executor_model` schema slot (sprint-105 story-002) is dead in production because nothing recommends or sets it.

## Why now

Sprint-107 ran 3 parallel teammates all on Opus 4.7 [1M] (kept uniform for clean baseline; see [V4_TEAMMATE_PIPELINE_VALIDATION.md](V4_TEAMMATE_PIPELINE_VALIDATION.md)). Observed costs: story-003 (79 LOC, mechanical) at $2.12; story-002 (600 LOC, pattern-following) at $11.95. Story-003 on Haiku would have been ~$0.20 + the fixed spawn cost. Story-002 on Sonnet would have been ~30-40% of the Opus cost. The tier choice is real money, and right now the system doesn't make it.

Also: `claude -p` pricing may change. Today it's subscription-included; tomorrow it may not be. The design needs a clean "disable teammates entirely" path.

## Three layers (clean separation of concerns)

### Layer 1: kickoff bundle (session-scoped, asked once)

`/xp-kickoff` Step 2 currently asks: free vs sprint, then review cadence. Add a third question (single combined AskUserQuestion, 5 options):

> Teammate support + default model for this session?
> - Off — solo only this session (forces in-agent regardless of frontier shape)
> - On — default haiku (mechanical work; cheapest)
> - On — default sonnet (pattern-following; balanced) **[Recommended]**
> - On — default opus (architecture-heavy)
> - On — inherit orchestrator (current default behavior — same model as the lead)

Stored as a marker file `TEAMMATE_CONFIG` with JSON `{enabled: bool, default_model: str | null}`. Sweeps on SessionStart (same pattern as `REVIEW_CADENCE`). For Free session: skip the question entirely — no sprint means no teammates.

### Layer 2: /xp-schedule (per-frontier, structural)

Gated on the kickoff teammate-support flag:

- **Teammate support OFF** → auto-solo silently, even on parallelizable multi-frontiers. No mode question.
- **Teammate support ON + frontier parallelizable** → ask current mode question "Solo or CLI teammates?" Customer keeps the option to pick solo per-frontier even when teammates are enabled (cost concerns, closer oversight, want quick iteration). Kickoff's answer was "do I want the OPTION"; per-frontier is "do I want it HERE".
- **Teammate support ON + frontier solo (FRONTIER_COUNT=1)** → still promotes + branches (no change from today's mechanics). Handoff text changes from "Proceed in-agent" to:
  > After /xp-review-plan, run /xp-assign — it will spawn a teammate if plan-reviewer recommends one, or refuse with a hint if in-agent is the right call.

The tier choice is NEVER asked at /xp-schedule. Kickoff's default carries through; per-story divergence surfaces at /xp-assign (Layer 3).

### Layer 3: /xp-assign (per-story, universal)

Currently /xp-assign is only invoked for teammate-mode parallel frontiers. The new design makes it valid for solo stories too — universal "execution shape" decision point.

When invoked, /xp-assign reads the plan-reviewer's tier-recommendation event for the story (Layer 4 below). Behavior:

| Plan-reviewer recommendation | Action |
|---|---|
| `in-agent` | Exit with "this story is in-agent appropriate; continue here." Customer keeps working in the existing checkout. |
| `haiku` / `sonnet` / `opus` matching kickoff default | Silent spawn at default tier (current parallel-teammate flow). |
| `haiku` / `sonnet` / `opus` diverging from kickoff default | ONE AskUserQuestion: "Default `<X>`, recommended `<Y>` — apply override?" Customer answers; spawn or proceed accordingly. |
| No recommendation (plan-reviewer omitted it as ambiguous) | Silent apply kickoff default. If kickoff default is `inherit`, spawn at orchestrator tier. |

**Always-in-agent escape hatch:** an `--in-agent` flag on /xp-assign forces in-agent regardless of recommendation. Customer agency preserved.

**Disable case:** when kickoff teammate-support is OFF, /xp-assign exits with a one-line hint pointing at the kickoff setting. Doesn't try to spawn.

### Layer 4: xp-plan-reviewer tier recommendation (the foundational event)

The load-bearing piece. Plan-reviewer already runs after every plan; adding a recommendation is a prose-only edit + one event write.

**xp-plan-reviewer.md addition (~12 lines of prose):**

> After reporting concerns/assumptions/decisions, judge story complexity and write ONE decision event for the tier recommendation. Heuristics:
> - **in-agent** when: <100 LOC AND single file AND mechanical (rename, format, port). Spawning a teammate is pure overhead.
> - **haiku** when: 100-300 LOC AND no judgment surface (mechanical refactors, well-templated additions, pattern-driven extensions of existing code).
> - **sonnet** when: 300-800 LOC AND pattern-following (mirrors existing code, schema additions following a precedent, multi-file but no novel architecture).
> - **opus** when: >800 LOC OR novel architectural surface OR cross-module integration OR subtle state/lifecycle/concurrency surface.
>
> If the plan is genuinely ambiguous on tier, OMIT the event — /xp-assign falls back to kickoff default. Do NOT guess.

**Event shape:**

```json
{
  "type": "decision",
  "agent_id": "xp-plan-reviewer",
  "topic": "tier-recommendation-story-NNN",
  "content": "Suggested executor_model: <tier> — <one-sentence rationale>",
  "metadata": {
    "recommended_model": "in-agent" | "haiku" | "sonnet" | "opus",
    "story_id": "story-NNN",
    "advisory": true
  }
}
```

**Why an SMM event instead of just the reply text:** plan-reviewer's reply is suppressed (debt `5e180220db1a` — the main agent has to dig review concerns from events.jsonl today). The recommendation MUST survive that suppression. Writing the event makes it:
- Discoverable by /xp-assign via topic-based query.
- Durable for retro analysis (recommendation accuracy over time can train the heuristic).
- Auditable when the lead overrides (override events get `metadata.action=tier_override` for retro accuracy analysis).

## Override audit trail

When /xp-assign applies a tier different from plan-reviewer's recommendation (customer answered "override no" or `--in-agent` flag), write a sibling status event:

```json
{
  "type": "status",
  "agent_id": "main",
  "content": "tier-override story-NNN: chose <picked> over recommended <reviewer>",
  "metadata": {
    "action": "tier_override",
    "story_id": "story-NNN",
    "picked": "in-agent" | "haiku" | "sonnet" | "opus",
    "recommended": "in-agent" | "haiku" | "sonnet" | "opus"
  }
}
```

Retros sample these to compute recommendation acceptance rate.

## Cost reality check

Plan-reviewer's addition: ~12 prose lines + 1 SMM event write per story. Zero new subagent spawns. Negligible token cost (Opus already loaded the plan; adding the tier line costs <100 output tokens per story).

vs the avoided cost: one mis-tiered Opus spawn for a $0.30-of-Haiku-work story is ~$3-7 wasted. Even one correct downgrade per sprint pays for the whole feature 100×.

For solo-in-agent recommendation: avoiding a spawn entirely on a trivial story saves the full spawn cost ($1-2 even on cheapest tier) plus the orchestrator stays focused on its session.

## When the customer is asked (summary)

| Moment | Question | Frequency |
|---|---|---|
| /xp-kickoff Step 2 | Teammate support + default model | Once per session |
| /xp-schedule (parallelizable + teammates on) | Solo or CLI teammates for this frontier? | Per parallelizable frontier |
| /xp-assign (recommendation diverges from default) | Apply tier override? | Per story where divergence exists |

Goal: keep the pipeline moving automatically in the common case; surface a question only when the cost delta is real and the customer might disagree.

## Coupling to existing debts

This feature depends on (and motivates fixing):

- **`5e180220db1a`** — xp-plan-reviewer output suppression. The SMM event is the survival path; fixing the suppression for the human-readable surface is still worthwhile but no longer load-bearing.
- **`.assign-pending` solo-leak** — surfaced this session, no debt id yet. Today solo stories don't fire /xp-assign at all, so the marker shouldn't arm. Under this new design /xp-assign IS valid for solo, so the marker arming becomes correct semantics — the leak self-resolves into a feature.

## Out of scope

- The xp-risk-classifier rubric broadening lives in [RISK_CLASSIFIER_RUBRIC_BROADENING.md](RISK_CLASSIFIER_RUBRIC_BROADENING.md). Different agent, different lifecycle point, different decision. No shared vocabulary — cousins, not siblings.
- Auto-learning from override accuracy (training the heuristic from retro data). Land the manual path first; collect 1-2 sprints of override events; then decide if auto-tuning earns its complexity.
- Per-tier prompt customization (give Haiku teammates terser prompts than Opus). Separate concern.
- Mid-session change of teammate-support / default model. Today the customer would re-run /xp-kickoff or edit the marker file directly. Acceptable for v1; consider a `/xp-config` skill later if pattern recurs.

## Acceptance ideas (for the implementation story)

- /xp-kickoff Step 2 asks the bundled teammate question; writes `TEAMMATE_CONFIG` marker; SessionStart sweeps it.
- For Free session, the question is skipped (no sprint means no teammates).
- xp-plan-reviewer prose contains the 4-tier heuristic table and writes a `tier-recommendation-<story-id>` decision event per reviewed plan (when the plan is unambiguous).
- /xp-schedule respects teammate-support flag: OFF → auto-solo silently; ON + parallelizable → asks mode question (unchanged shape).
- /xp-assign becomes valid for solo stories; reads recommendation event; behaves per the Layer 3 table.
- Override events have `metadata.action=tier_override` for retro accuracy analysis.
- AC: replay sprint-107's plan-review events with the new prose → assert tier recommendations match the post-hoc complexity table in V4_TEAMMATE_PIPELINE_VALIDATION.md (haiku for story-003, sonnet for story-002, opus for story-001 + 004).
- AC: with TEAMMATE_CONFIG.enabled=false, /xp-schedule on a parallelizable frontier exits with auto-solo + no mode question.
- AC: with recommendation = in-agent, /xp-assign exits with the "continue here" hint and does NOT spawn.
- AC: with recommendation diverging from default, /xp-assign asks override exactly once per story.

## Implementation stories (rough decomposition)

1. **Marker + kickoff bundle** — `marker_names.TEAMMATE_CONFIG`, kickoff Step 2 prose, SessionStart sweep. Smallest; no other dependencies.
2. **xp-plan-reviewer recommendation event** — prose addition + heuristic table. Standalone; landable independently.
3. **/xp-assign universal** — solo path support, recommendation reader, override-question gate. Depends on (1) and (2).
4. **/xp-schedule gate respect** — teammate-support flag check; auto-solo when OFF. Depends on (1).
5. **Override audit + retro analysis** — `tier_override` status events; retro tooling read. Can land later; reads the events written by (3).

Stories 1+2 are parallelizable. Stories 3+4 depend on 1+2 but can be parallel with each other. Story 5 is post-shipping cleanup.

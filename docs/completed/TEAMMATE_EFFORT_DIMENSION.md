# Teammate effort dimension (follow-up to the tier picker)

**Status:** idea
**Source:** sprint-110 M3 planning (story-001/002 close-time discussion)
**Relationship:** extends [TEAMMATE_TIER_PICKER.md](TEAMMATE_TIER_PICKER.md). The tier
picker shipped **model-only**; this note captures the deferred **effort** dimension.

## Why deferred

The tier picker recommends an `executor_model` (haiku/sonnet/opus/in-agent). A natural
extension is to also pick a **reasoning effort** per story. We deliberately left it out
of the M3 tier picker for two reasons:

1. **Effort is not uniform across tiers** — it is not a clean orthogonal "model × effort"
   product. The cheapest tier rejects it outright (see the matrix). So the marker schema
   and the rubric can't treat effort as a free dimension.
2. **It needs a spawn-mechanism change** — `spawn_teammate.py` currently forwards only
   `--model`. Effort would be a second forwarded knob, not just a marker field + rubric
   line.

## Per-tier effort support (the load-bearing fact)

Reasoning effort is `output_config.effort` at the Claude API level; in Claude Code it is
the reasoning-effort setting. Support is **non-uniform** — verified against the Claude
API reference, not memory:

| Model        | `low`/`medium`/`high` | `xhigh`            | `max`              | Adaptive thinking |
|--------------|-----------------------|--------------------|--------------------|-------------------|
| Opus 4.8 / 4.7 | yes                 | yes                | yes                | yes               |
| Sonnet 4.6   | yes                   | **no** (Opus 4.7+) | yes                | yes               |
| Haiku 4.5    | **no — errors**       | no                 | no                 | **no** (legacy fixed-budget extended thinking only) |

The two traps:
- **Haiku 4.5 rejects the `effort` parameter entirely** and has no adaptive thinking — so
  there is no effort knob on the cheapest tier. A naive "model + effort" picker would emit
  an invalid combination for haiku.
- **`xhigh` is Opus-only** (added in Opus 4.7); **`max` is Opus/Sonnet only** — not Haiku.

## What an effort extension would need

1. **Marker:** extend `TEAMMATE_CONFIG` from `{enabled, default_model}` to
   `{enabled, default_model, default_effort}` — OR keep effort out of the session default
   and let the plan-reviewer recommend it per story. `default_effort` must allow "unset"
   (inherit) and must be ignored/null for haiku.
2. **Rubric (plan-reviewer):** add an effort recommendation alongside `recommended_model`,
   with an explicit **tier-gate**: never recommend `effort` for a haiku-tier story; cap at
   `high`/`max` for sonnet (no `xhigh`); full range for opus. The rubric must encode the
   non-uniform matrix above so it never emits an invalid pair.
3. **Spawn mechanism:** add an `--effort` forward to `spawn_teammate.py`, with a guard that
   drops it (and logs) when the resolved model doesn't support the requested level — fail
   safe to the model's default rather than erroring the spawn.
4. **Project-agnostic check:** effort is a Claude-harness concept; keep any shipped rubric
   prose generic ("more reasoning effort for harder correctness surfaces"), not tied to a
   specific provider's level names, OR scope it explicitly as a Claude-Code-only knob.

## Out of scope for this note

- Whether effort even moves the cost/quality needle enough to justify the second knob —
  collect data from the model-only picker first (the M3 design's "land manual path, then
  decide" stance applies here too).
- The xp-risk-classifier rubric broadening ([RISK_CLASSIFIER_RUBRIC_BROADENING.md](RISK_CLASSIFIER_RUBRIC_BROADENING.md))
  is a different agent and lifecycle point — unrelated.

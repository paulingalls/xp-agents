# Remove the xp-risk-classifier from the per-increment review floor

**Status:** idea
**Source:** free session 2026-07-02 (design discussion during /xp-quality-review runs)
**Supersedes:** any `RISK_CLASSIFIER_RUBRIC_BROADENING` note — don't broaden a rubric we're deleting.

## The claim

In the current `/xp-quality-review` self-find path the risk classifier does not earn
its cost, so remove it and fold risk-triage into the reviewer itself.

## What it does today (the load-bearing fact)

`/xp-quality-review` (MODE=self-find) runs two subagents in series:

1. **Step 1.4** — spawn `xp-risk-classifier` (haiku). It reads the diff + changed files +
   design context and returns `RISK=high|low` on line 1, optional `SIGNALS=<comma-list>` on
   line 2.
2. **Step 1.5** — spawn `xp-code-reviewer` (sonnet/opus). It runs **unconditionally**. The
   only effect of Step 1.4 is: on `RISK=high`, prepend a `## Review Focus` block naming the
   `SIGNALS` angles (default `state/lifecycle/concurrency`); on `RISK=low`, no hint.

So the classifier **does not gate whether the expensive reviewer runs** — it only supplies
an optional "look harder at X" hint to a reviewer that was going to run anyway.

## Why it doesn't earn its place

- **No cost saving.** A classifier pays off only when it gates the expensive step. This one
  doesn't; it's pure added serial latency (observed ~55–90s per run, *before* the reviewer
  starts).
- **Inverted tiering.** The cheaper model (haiku) triages risk and hands a hint to the
  stronger model (sonnet/opus). Both read the *same* inputs. The reviewer is the better
  judge of what's risky in the diff it's about to review.
- **Complexity for a hint.** Strict first-line parsing, `SIGNALS=` comma-splitting, the
  `## Review Focus` plumbing, the reviewer's Section 1c handshake, and all of Step 1.4 exist
  to pass something the reviewer can derive itself.

## What removal loses (and why it's acceptable)

- The `RISK=high` enrichment hint — recovered by instructing the reviewer to self-assess
  risk from the diff + design context and elevate angles accordingly.
- An independent risk read — marginal; the reviewer isn't biased about a diff it didn't write.
- The design-context down-rating (don't false-flag documented conventions) — preserve by
  keeping that instruction in the reviewer prompt (it already receives Design Context).

## The one thing that would justify a classifier (explicitly out of scope)

Making it a **real gate**: `RISK=low` → skip or downgrade the reviewer as a cost lever. That
trades false-negatives (shipped bugs) for cost — presumably why the reviewer is unconditional
today. If that trade is ever wanted it's a *different* design; it does not justify keeping the
current no-op-gate classifier.

## Removal surface (actionable checklist)

Shipped:
- `skills/xp-quality-review/SKILL.md` — delete Step 1.4; collapse Step 1.5 to a single
  unconditional spawn; fold "self-assess risk + elevate angles + down-rate documented
  conventions" into the reviewer prompt. Keep the single-spawn invariant.
- `skills/xp-quality-review/scripts/preload.sh` — the Design Context block is currently gated
  as "passed to the risk classifier" (self-find only); re-target it to the reviewer (still
  needed there).
- `agents/xp-risk-classifier.md` — delete the agent.
- `agents/xp-code-reviewer.md` — remove the `## 1c. Review Focus Block` handshake and the
  classifier-signal→focus pairings; replace with a self-triage instruction.
- `scripts/subagent_start.py` — drop the risk-classifier mention from the tier/injection
  comment and any `_TIERS` entry.

Tests (write/adjust red-first):
- `tests/skills/test_quality_review_risk_routing.py` — the primary suite; rewrite to assert a
  single unconditional reviewer spawn with self-triage prose (or delete if fully obsolete).
- `tests/agents/test_risk_classifier_agent.py` — delete.
- `tests/agents/test_agent_model_tiers.py`, `test_agent_budgets.py` — remove the classifier's
  tier/budget entries.
- `tests/agents/test_xp_code_reviewer.py` — update Section 1c expectations.
- `tests/integration/test_review_regression_replay.py` — drop any classifier replay leg.
- `tests/hooks/test_pre_tool_skill.py` — confirm the skill-gate allowlist doesn't assume the
  classifier agent still exists.

## Notes for setup

- Plugin-agnostic check: classifier and reviewer are both LLM-judgment agents (no
  language-specific code), so removal has no cross-language-coverage impact.
- After removal, the "haiku = classifiers" model-tier rationale may lose its only in-repo
  user — worth a glance at whether any other agent still classifies at haiku.
- This is a change to a core review floor. Do it as a deliberate branch with red tests, not a
  drive-by. Reasonable single-milestone sprint or a focused free session.

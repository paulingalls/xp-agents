# Bug report: retro analyzer reports "0 quality reviews" despite QRs running

**Plugin:** `xp-agents` (cached at `~/.claude/plugins/cache/xp-agents/xp-agents/2.25.0/`)
**Suspected location:** the QR-counting logic in the retrospective analyzer (whichever module scans `events.jsonl` for sprint metrics; produces lines like "N quality reviews for M review-required commits"). Exact file unconfirmed.
**Reporter:** AJE PoC, sprint-004 retrospective (2026-04-23)
**Linked decision:** SMM event `1a019208679f` ("Drop: Make xp-quality-review a non-skippable SubagentStop gate" — dropped after this bug was identified.)

## Current behavior

The sprint-003 retrospective output included this line (verbatim):

> "0 quality reviews for 7 review-required commits — 4th consecutive sprint at 0%. Try-2 (non-skippable SubagentStop gate) DEFERRED 4x. Pattern is 'agree it matters, choose not to enforce.'"

This was rendered as a Fix item and used to propose a Try (`Try-2`) escalating `xp-quality-review` to a non-skippable hook gate.

## What we're seeing (evidence is reproducible)

QRs **were running** for sprint-003. Specific evidence:

1. **Commit `5dfc83c`** (sprint-003 web-vitals collector) body explicitly lists "Reviewer-applied refinements" matching the changes the QR agent recommended:

   > "networkidle0 → networkidle2 (web-vitals long connections won't time out)"
   > "2500ms blind sleep → data-driven waitForFunction on LCP entry + 500ms tail"
   > "magic timeouts → named NAV_TIMEOUT_MS / SHIM_READY_TIMEOUT_MS / POST_LCP_TAIL_MS"
   > "type WebVitalsGlobal alias (was duplicated cast)"

2. **xp-quality-review event `5e03a0099fa9`** (timestamp `2026-04-22T17:34:13Z`) says:

   > "QR complete. Fixed: chrome.ts withChrome extracted, collectWebVitals tested (4 cases), data-driven LCP wait, networkidle2, named timeout constants."

   That bullet list matches the commit-body refinements 1:1 — same QR session, same fixes.

3. **70 events tagged `xp-quality-review` or `xp-code-reviewer`** in `events.jsonl` for the project lifetime:

   ```
   $ grep -c "xp-quality-review\|xp-code-reviewer" $SMM_DIR/events.jsonl
   70
   ```

So the analyzer's "0" is wrong by at least 1 (the QR for `5dfc83c`), and probably by more.

## Why this matters

1. **False-positive Try items wasted 4 sprints of retro discussion.** Try-2 was proposed and deferred 4× based on this metric. Each sprint the retro analyzer re-flagged "0% adoption" as a stop-the-line.
2. **Bad signal corrodes trust in retro outputs.** Once one metric is known wrong, agents start mentally discounting all retro outputs. That undermines retros as a feedback loop.
3. **Almost shipped a hard process change based on a counting bug.** The session that adopted Try-2 would have promoted QR to a non-skippable SubagentStop gate. Doing that on top of a metric that already over-reported "0%" would have made the situation strictly worse — the gate would fire on every commit, including ones where QR already ran (because the analyzer can't see them).

## What we want

The analyzer should count QRs by recognizing the actual completion event signature(s) emitted by the `xp-quality-review` and `xp-code-reviewer` agents.

| Strategy                                                                                 | Precision | Robustness                                                  |
| ---------------------------------------------------------------------------------------- | --------- | ----------------------------------------------------------- |
| Count events where `agent_id ∈ {xp-quality-review, xp-code-reviewer}` AND `type=status`  | High      | Catches all completion events even if metadata varies       |
| Require a specific `metadata.action: "qr_complete"` marker on a single terminal QR event | Highest   | Requires the QR agent to consistently emit the marker first |

Either is fine. The current rule appears to look for a marker that nothing emits, hence the universal 0.

## Suggested investigation order

1. Grep retro analyzer source for the existing QR-detection rule (`grep -rn "quality.*review\|qr_complete\|xp-quality-review" <plugin-source>`).
2. Confirm what events the QR agent (`xp-quality-review` skill / `xp-code-reviewer` agent) actually emits (read agent prompts + a real session's `events.jsonl`).
3. Reconcile: either fix the analyzer rule to match what the agent emits, OR update the QR agent to consistently emit the marker the analyzer looks for. (Prefer the former — less invasive, handles historical data.)

## Acceptance criteria

1. Analyzer correctly counts the sprint-003 QR (≥1, not 0) when re-run against this branch's `events.jsonl`.
2. Correctly counts zero when no QR ran in the sprint (verify by deleting the QR events from a copy of the log and re-running).
3. Correctly counts multiple per sprint when multiple QRs ran (sprint-004 has at least 5 QRs from this very story-003 review cycle — verify the analyzer reports ≥5 for sprint-004).
4. Doesn't double-count when both `xp-quality-review` and `xp-code-reviewer` events fire for one logical review (current pattern: skill spawns subagent — two different `agent_id` values for one review).
5. Emits a debug log line (when verbose) listing the event IDs it counted, so future regressions are debuggable.

## Out of scope

- Changing the QR agent itself to emit different events.
- The separate Try-1 commit-gate work (different hook, different doc — see `docs/feature-requests/commit-gate-resolves-event-trailer.md`).

## Contact / validation

SMM dir: `/Users/paulingalls/.claude/plugins/data/xp-agents-xp-agents/bce1d9c11420/smm`

Validation event ID: `5e03a0099fa9` (must be counted as a QR by any fixed analyzer).

Sprint range to test against: sprint-003, between commits `1384cfb` (initial) and `3657095` (HEAD before sprint-004 work). Expect at least 1, probably several QRs. Sprint-004 should report ≥5 (one per story-003 step).

---

## Status update — 2026-04-27 (sprint-007 retro, plugin v2.30.7)

**Bug still present after 5 minor plugin releases (v2.25.0 → v2.30.7) and 13 consecutive sprints.**

Sprint-007 retrospective output included this line verbatim:

> "13th consecutive sprint with quality-review counter mismatch: status_summary.quality_reviews=0 but per_agent.xp-quality-review.status_count=28 (12 review-required commits)."

Evidence the metric is internally inconsistent within a single retro run:

- `status_summary.quality_reviews` = **0**
- `per_agent.xp-quality-review.status_count` = **28**

Both numbers come from the same `events.jsonl` scan, in the same retro invocation. The summary aggregator and the per-agent rollup disagree by 28 events. The summary aggregator is the value used to gate the "0% adoption" Fix line.

The 12 review-required commits in sprint-007 each had a corresponding QR session (verified by `xp-quality-review` and `xp-code-reviewer` agent_id status events with `metadata.action: "qr_complete"` markers). The summary continues to read 0.

The fix proposed in the original report (count by `agent_id ∈ {xp-quality-review, xp-code-reviewer}` AND `type=status`) would resolve the mismatch — the per-agent rollup already does this and gets 28; the summary aggregator should reuse the same logic.

**Reaffirmed acceptance criteria (1) — sprint-007 numbers:** Re-run analyzer against current `events.jsonl` for sprint-007 should report `quality_reviews ≥ 12` (one per review-required commit), not 0.

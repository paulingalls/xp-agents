# Refactor-Mode-Aware TDD Metric

**Plugin:** `xp-agents`
**Type:** Retro agent improvement
**Priority:** Low (reduces noise, no behavioral change to TDD enforcement)
**Decision:** Recorded in session 2026-04-22, topic `tdd-cadence-metric`

---

## Problem

The retrospective agent computes `max_unique_files_without_test` as a global metric. During refactor-mode work (file splits, import normalizations, mechanical renames), batching 6+ file writes before running tests is the natural workflow. The retro flags this as a TDD Fix every session, even when refactor-mode was properly declared via an assumption event. This creates noise — the same Fix appears, gets adopted, and reappears.

---

## Solution

Make the retro agent's TDD gap analysis aware of refactor-mode declarations.

### How it works

1. When computing `max_unique_files_without_test`, scan for assumption events with content matching "refactor mode" or "refactor-mode"
2. File writes that fall within a declared refactor-mode span (between the assumption event and the next commit) are excluded from the gap count
3. Undeclared batches of file writes still count toward the metric and trigger a Fix if over threshold

### What changes

- **`agents/xp-retrospective/`** — update the TDD gap analysis to check for refactor-mode assumption events. When a batch of file writes has a preceding refactor-mode declaration, annotate it as "(refactor-mode)" rather than counting it as a gap
- **Retro output** — change from "TDD gap: 6 files without test" to "TDD gap: 6 files without test (refactor-mode declared, excluded)" so the context is visible

### What stays

- `max_unique_files_without_test` is still computed and reported
- Non-refactor-mode gaps still generate Fix items
- The convention of declaring refactor-mode via assumption event is unchanged
- Commit-time TDD nudges are unaffected (those are in the hooks, not the retro)

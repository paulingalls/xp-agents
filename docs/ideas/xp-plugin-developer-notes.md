# XP Plugin Developer Notes

Caveats, gate-bypass risks, and observed-but-unfixed edge cases in the `xp-agents` Claude Code plugin (`/Users/paulingalls/.claude/plugins/cache/xp-agents/xp-agents/4.4.2/`). Recorded so plugin-developer attention lands on the right surface when they next get to it. None of these block normal solo XP flow — they're failure modes you should know exist.

## 1. Close-cycle gate bypass via `stop_hook_active` termination

**Risk id**: `88ad81a4c0b9`

**Symptom**: The `CLOSE_CYCLE_ACTIVE` marker — set by the stop hook to enforce that `xp-close-reviewer` runs before any merge — can land in an inconsistent state when the stop hook itself is terminated by `stop_hook_active`. The marker says "close cycle in progress" without the close-reviewer ever firing, and the orchestrator may proceed straight to merge without a reviewer pass.

**Trigger path**:
1. Story-close skill enters its close pipeline and the stop hook starts to fire.
2. `stop_hook_active` causes the hook to be interrupted before it has finished its work — e.g. another tool call races it, or the harness short-circuits.
3. The `CLOSE_CYCLE_ACTIVE` marker is set as a side effect of the interrupted hook, but the close-reviewer fork never happens.
4. The next Step in the pipeline reads "marker present, close cycle active" and skips the gate that would have re-fired the reviewer.

**Why it hasn't bitten in practice**: The main agent has so far always invoked the close-reviewer explicitly via `Agent({subagent_type: "xp-agents:xp-close-reviewer", ...})` as part of the close-skill's Step 4.5, independent of the stop-hook chain. The stop hook's CLOSE_CYCLE_ACTIVE logic is a belt-and-suspenders fallback, not the primary gate.

**Fix shape**: The marker should be set only after the reviewer has been invoked and returned, not as a hook-entry side effect. Treat marker-presence as evidence of completed review, not in-progress review. Alternative: cross-check the close-cycle event log for a `concern_classify` event before honoring the marker.

## 2. Accept-gate eager fire on `xp-assign` with zero commits

**Debt id**: `72660c08b680`

**Root cause shared with §4**: both are the same underlying defect — the accept-gate's predicate is `status == in-progress` alone, with no view of work-in-motion. Here that means no commits yet; in §4 it means a live in-place teammate spawn the predicate can't see. Fixing the predicate to account for in-motion work (not just story status) closes both.

**Symptom**: The stop-hook accept-gate (which nags "run /xp-accept before stopping" when a story is in-progress) fires immediately after `/xp-assign` promotes a story to in-progress, even when the story branch has zero commits ahead of base. Running `/xp-accept` at that point verifies nothing — the acceptance command runs against an empty branch and either fails noisily or passes vacuously.

**Why it's annoying, not dangerous**: The nag is noise, not a correctness issue. The next legitimate iteration of the loop (commit → `/xp-accept`) overwrites the spurious state. But it surfaces during every story handoff after a JIT-promote and trains users to ignore the gate, which weakens the signal when it fires legitimately.

**Fix shape**: The accept-gate predicate should check `commits_ahead_of_base > 0` (cheap: `git rev-list --count <base>..HEAD`) before nagging. Story-in-progress alone isn't enough — work-not-yet-done must hold.

## 3. `branching.py create-free --base` missing

**Observation, not a recorded risk**

`scripts/branching.py create-free` always branches off `main` regardless of the orchestrator's current branch. For free-mode work that needs to integrate post-sprint-N state (e.g. doc cleanups that reference recently-shipped code), this forces either:

- A `[chore]` direct commit to the integration branch (current workaround at stage 2+), or
- Manually creating the branch with `git checkout -b` and then registering it with the plugin separately.

**Fix shape**: Add an optional `--base` flag mirroring `branching.py create --base` (which already supports it for story branches). Free-branch base should default to the current `paulingalls/plan-*` or `paulingalls/sprint-*` when one is checked out, falling back to `main` only when the orchestrator sits on a protected branch.

## 4. Accept-gate fires while an in-place teammate is mid-flight

**Debt id**: `b566648b8bce`

**Root cause shared with §2**: same underlying defect as §2 — the predicate is `status == in-progress` alone, with no view of work-in-motion. Here the in-motion work is a live in-place teammate spawn the gate cannot see, rather than zero commits.

**Symptom**: The `/xp-accept` stop-gate reads `status == in-progress` but has no visibility into a live in-place teammate spawn, so it fires on exactly the turn the lead is correctly idle-waiting for the task-notification. Accepting there verifies a half-written tree.

**Why it's dangerous, not merely annoying**: Unlike §2 (a no-op nag on an empty branch), this can green-light an incomplete tree — the gate's false positive coincides with real, in-flight, uncommitted work, so acting on it risks accepting a story before its implementation is done.

**Fix shape**: The gate should suppress while a spawn is live (check for a running spawn / `session_init` event for the story) instead of firing on story status alone.

## Reporting

When any of these bite during real work, add an event to the SMM (`type=concern` or `discovery`) referencing the id above. The plugin maintainer reads these out-of-band; surfacing live reproductions is the highest-value signal.

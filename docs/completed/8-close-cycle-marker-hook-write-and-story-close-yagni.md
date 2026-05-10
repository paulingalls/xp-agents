# Close-cycle marker: hook-driven write + story-close conditional removal

**Resolution:** Both pieces shipped. xp-story-close/SKILL.md Step 4 now reads "Security Review (skipped)" with the comment "Does not apply to story-close". The `write_marker CLOSE_CYCLE_ACTIVE ""` line is present in xp-{free,sprint,plan}-close/scripts/preload.sh and absent from xp-story-close/scripts/preload.sh — exactly the design proposed here.

---

## Context

Two related changes that simplify and harden the close-cycle Stop gate:

1. **YAGNI removal** — `xp-story-close` has a "Step 4: Conditional Security Review" branch that fires `/security-review` when no sprint envelope wraps the story. The codebase doesn't actually support that path:
   - Kickoff binds session mode (sprint vs free) at Step 2 — first AskUserQuestion.
   - `xp-work-selection` in free mode collects goals only, never creates stories.
   - `xp-assign` is the only path that creates story branches; sprint-mode only.
   - `xp-story-close` is invoked by `/xp-accept` per accepted story; `/xp-accept` only runs against an active sprint.

   The "orphan story branch outside a sprint" condition is dead code defending a hypothetical. Carries maintenance cost (conditional gate, predicate duplication risk, multiple test classes).

2. **Marker hook-write** — currently `CLOSE_CYCLE_ACTIVE` is written by LLM-prose at `_close_pipeline_shared.md` Step 4 line 21 (`markers.py write CLOSE_CYCLE_ACTIVE`). The Stop gate (`close_cycle_stop_gate.py`) depends on the marker existing. If the LLM skips the prose line OR reorders security-review before the marker write OR invokes `/security-review` standalone-mid-close, the marker never lands and the gate doesn't arm. Real failure mode user observed.

   With story-close out of the picture (per #1), the remaining 3 close skills (`xp-free-close`, `xp-sprint-close`, `xp-plan-close`) **always unconditionally** run `/security-review`. Their preloads can write the marker deterministically — no predicate, no drift class, no LLM-trust dependency.

The two changes compose: removing story-close's conditional turns the marker design from "complex predicate sharing across 4 skills with drift risk" into "trivially correct unconditional write in 3 preloads".

## Scope

**In scope:**
- Delete `xp-story-close` Step 4 entirely (security review + the conditional gate prose)
- Update `_close_pipeline_shared.md` scoping line to drop story-close mention
- Add `markers.py write CLOSE_CYCLE_ACTIVE` to the 3 unconditional close-skill preloads
- Drop the prose `markers.py write` line from `_close_pipeline_shared.md` Step 4
- Delete the 5-class test file `test_xp_story_close_security_gap.py` (all assertions defend the removed behavior)
- Delete the `STEP_4_SECURITY: APPLIES/SKIP` literal-token machinery from xp-story-close SKILL.md
- Update `tests/integration/test_close_preloads_emit_shared.py` to drop the markers.py-write-precedes-security-review test (or rewrite as preload-emits-marker-write)
- Add new test: each of the 3 close-skill preloads emits a `markers.py write CLOSE_CYCLE_ACTIVE` invocation, executed deterministically before the LLM body runs

**Out of scope:**
- Orphan story-branch triage at kickoff (separate feature, uses `branching_cli.py list-story-orphans` for a different purpose — leave intact)
- Future work to add ad-hoc stories within free sessions — when that lands, security-review wiring for those stories can be re-introduced as a focused feature
- The dedup question on `_record_bypass` (concern `5f4b4b3e1bf2`) — accepted trade-off, not in this scope

## Files affected

### Production / docs

| File | Change |
|---|---|
| `plugins/xp-agents/skills/xp-story-close/SKILL.md` | Delete the entire "## Step 4: Conditional Security Review" section (lines ~128-165). Renumber subsequent steps if any reference Step 4. Verify Step 5 / Step 4.5 references in remaining prose still cohere. |
| `plugins/xp-agents/scripts/_close_pipeline_shared.md` | Line 11 scoping line: change `**free, sprint, plan** close unconditionally, plus **story (when no sprint envelope wraps)**` → `**free, sprint, plan** close unconditionally`. Lines 12-15 (story-close-defers clause) deleted entirely. Line 21 (`markers.py write CLOSE_CYCLE_ACTIVE`) deleted — the preloads now own the write. |
| `plugins/xp-agents/skills/xp-free-close/scripts/preload.sh` | Add `python3 "${PLUGIN_ROOT}/scripts/markers.py" --smm-dir "${SMM_DIR}" write CLOSE_CYCLE_ACTIVE` after the existing `echo CLOSE_CYCLE_ID=...` line so the marker is written from skill-invocation onward. |
| `plugins/xp-agents/skills/xp-sprint-close/scripts/preload.sh` | Same addition. |
| `plugins/xp-agents/skills/xp-plan-close/scripts/preload.sh` | Same addition. |
| `plugins/xp-agents/skills/xp-story-close/scripts/preload.sh` | **No change** — story-close never fires security-review, so it never writes the marker. |

### Tests

| File | Change |
|---|---|
| `plugins/xp-agents/tests/integration/test_xp_story_close_security_gap.py` | **Delete entire file.** All 5 test classes (TestStoryCloseStep4, TestStoryCloseStep4Conditional × 6 tests, TestSharedPipelineScopingLine × 2 tests) defend the conditional behavior being removed. |
| `plugins/xp-agents/tests/integration/test_close_preloads_emit_shared.py` | The "markers.py write precedes /security-review" assertion at line ~174-204 is now wrong — preloads write the marker, the LLM never does. Rewrite to assert each preload's stdout contains the `markers.py write CLOSE_CYCLE_ACTIVE` invocation. |
| `plugins/xp-agents/tests/integration/test_close_cycle.py` | Existing tests should keep passing — they seed the marker via the CLI directly (`run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)`) and exercise the gate logic, which is unchanged. Verify no prose-related assertions need updating. |
| `plugins/xp-agents/tests/_close_fixtures.py` | The `_Step4SecurityIncludeTests` mixin currently runs against story-close (line ~556 references "no sprint envelope wraps"). Drop story-close from the mixin's call-sites; mixin keeps applying to free/sprint/plan close only. |

### Existing infrastructure that stays

- `scripts/markers.py` — unchanged. Already idempotent (`write CLOSE_CYCLE_ACTIVE` on an already-set marker is a no-op).
- `scripts/close_cycle_stop_gate.py` — unchanged. Marker semantics are identical.
- `scripts/subagent_stop.py:_handle_close_reviewer_done` — unchanged. Still consumes the marker on xp-close-reviewer SubagentStop.
- `skills/_preload_base.sh:list_orphan_story_branches` and `branching_cli.py list-story-orphans` — kept; consumed by `xp-kickoff` Step 2.7 (orphan story-branch triage), which is separate from the security-review wiring.
- `smm/sprint_cli.py:exists` (`sprint_exists`) — kept; used by branching.py and other paths.

## Verification

```bash
# Targeted: gate + preload tests
pytest plugins/xp-agents/tests/integration/test_close_cycle.py \
       plugins/xp-agents/tests/integration/test_close_preloads_emit_shared.py -v

# Manual smoke: each close-skill preload emits the marker write
bash plugins/xp-agents/skills/xp-free-close/scripts/preload.sh
# Expect stdout to include: python3 .../markers.py ... write CLOSE_CYCLE_ACTIVE
# AND the marker file to exist after running:
ls "${SMM_DIR}/.markers/CLOSE_CYCLE_ACTIVE"

# End-to-end: a real /xp-free-close run on a test branch should now write
# the marker BEFORE the LLM ever sees the prose body.

# Full suite gate
pytest -n auto
```

Expected: full suite passes after the deletions (5 test classes removed, 1 test rewritten, 0 new failures). Marker write moves from prose-driven to preload-driven without changing the gate's runtime behavior.

## Risks + mitigations

- **Risk**: Some other code path invokes `/xp-story-close` outside `/xp-accept`'s sprint flow (CI hook, manual user invocation on a branch they made). Mitigation: documented YAGNI assumption — "walking without a net" per user's framing. If a real use case emerges, the reintroduction is straightforward.
- **Risk**: Idempotency of `markers.py write` — if a close skill is re-invoked while the marker is already set (e.g., post-failed-merge retry), the second write should be a no-op. Verify with the existing `markers_test.py` or add a test if missing.
- **Risk**: Test count drops noticeably (~5-7 tests from `test_xp_story_close_security_gap.py`). Acceptable — these tests defended a removed feature; deleting is the honest move per "tests are production code, never carry dead tests".

## Open questions for the execution plan

1. **Single sprint or split milestones?** Plausible breakdown: (M-1) YAGNI removal — drop story-close Step 4, delete tests, update shared pipeline scoping. (M-2) Hook-driven marker — add to the 3 preloads, drop the prose write line, update preload-emit tests. M-1 first because M-2's design is cleaner once story-close is out of the picture. Could also be one milestone if the changes feel atomic enough.

2. **Should the preload write also stamp `CLOSE_CYCLE_ID` and `CLOSE_START_TS` to the marker payload?** Today the marker is just a flag file. The IDs are emitted into the preload stdout as separate vars the LLM substitutes. If the gate ever needs to correlate "which close cycle" the marker belongs to, payload-stamping would help. Probably YAGNI for now; the gate just checks existence.

3. **Auto-clear on close-skill subagent failure?** If the close-skill itself crashes mid-flight (preload writes marker, then bash subprocess fails before xp-close-reviewer ever spawns), the marker would persist as an orphan blocking future Stops. Current design has the same risk in prose-driven form. Worth a session-start sweep that clears stale CLOSE_CYCLE_ACTIVE markers older than N hours? Or a SubagentStop on the close-skill itself? Defer to the execution plan — answer depends on observed staleness frequency.

## Why now

This session shipped the bypass instrumentation (commit `3b91bbf3`) which makes silent escapes visible via concern events. Combined with this proposed change (deterministic marker write), the two together close the gap from both ends: the marker can't fail to arm, and if the gate ever IS bypassed via `stop_hook_active=True`, retros will see it.

Closes the architectural gap behind concern `c7600936cd55` (already dropped as already-addressed by the existing `CLOSE_CYCLE_ACTIVE` mechanism, but the prose-driven write was the actual hole the user reported).

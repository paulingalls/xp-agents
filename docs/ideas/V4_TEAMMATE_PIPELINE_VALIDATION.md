# V4 per-story teammate-pipeline validation (sprint-107 capstone)

**Story:** sprint-107 story-005 (carried from sprint-105, deferred until v4.0.0 released to marketplace)
**Scope:** observe the v4.0.0 per-story teammate pipeline running on real work (sprint-107 stories 001-003 in parallel + 004 solo follow-up) and compare against the v3.11.0 batch-fan-out shape sprint-105 retired.

## What ran

Sprint-107 used the live v4.0.0 plugin loaded from the marketplace cache via `--plugin-dir`. The lead orchestrator (Opus 4.7 [1M]) drove the per-story plan→/xp-review-plan→/xp-assign loop:

| Story | Mode | Plan size | Branch | Commits | Tests | Cost | Time-to-report |
|---|---|---|---|---|---|---|---|
| story-001 | teammate (parallel) | 1313 LOC NEW | sister_tests primitive + 10 BUILTIN | 15 (14 + reviewer fix) | 94→96 (path-escape guard) | $6.81 | ~22 min |
| story-002 | teammate (parallel) | 600 LOC | system_context test_layout surface | 7 | 32 | $11.95 | ~21 min |
| story-003 | teammate (parallel) | 79 LOC | sprint_cli dup-id reject | 2 | 5 (67 total in file) | $2.12 | ~6 min |
| story-004 | solo (lead) | 586 LOC | wire save_sprint + Q1(b) soft-warn | 6 (5 + reviewer simplify) | 7 new + integration green | — | done in-session |

All teammates inherited Opus 4.7 [1M] (no per-story `executor_model` set — kept uniform to give story-005 a clean comparison baseline; see "What we didn't measure" below).

Total: **6/6 stories that ran (story-005 plus the four above) reached merge.** No defers in sprint-107. One [verify-deferred] commit on story-004 covered an AC-listed test that didn't need touching post-split.

## Transcript stats (live observation)

| Story | Transcript LOC | Tool uses | Edit/Write | Bash | Pre-tool hook mentions |
|---|---|---|---|---|---|
| story-001 | 506 | 118 | 42 | 51 | 32 |
| story-002 | 488 | 117 | 32 | 43 | 12 |
| story-003 | 122 | 32 | 4 | 13 | 5 |

Hook activity scaled with code volume — story-001 (largest diff, longest TDD cadence with 14 commits) hit 32 PreToolUse interventions; story-003 (smallest, 2 commits) hit 5. No blocked-by-hook decisions surfaced in any teammate (`"decision": "block"` count = 0 across all three).

## Observable differences vs v3.11.0 baseline (batch fan-out)

The pre-v4.0.0 model was `/xp-assign` spawning the full teammate batch in one call, then the lead waited for the batch to complete before any acceptance ran. v4.0.0 split this into per-story plan→review→spawn pipeline.

### 1. Plan-review happens **before** spawn, not after
**v3.11.0:** lead planned the whole batch up front, sent all teammates, then reviewed plans only when problems surfaced post-implementation.
**v4.0.0:** every teammate spawn was preceded by EnterPlanMode→ExitPlanMode→`/xp-review-plan`. The reviewer caught real issues this session:
- story-001 plan had 6 concerns (TDD inversion + py3.11/3.12 `PurePosixPath.match` mid-`**` landmine + csharp_xunit `source_excludes` undefined + `{mirror}` placeholder unwired + YAGNI + commit cadence). Three were correctness blockers that would have shipped broken code.
- story-002 plan had 2 concerns (renderer test path undecided + edit-test-layout `{}` vs `null` semantics ambiguity).
- story-003 plan had 1 concern (sprint.json path drift; locking decision recorded).
- story-004 plan had 1 BLOCKING question (edit-story routing vs M1 impact-zone constraint) + 5 other concerns. The blocking question forced a customer-locked architectural decision (split run/save) BEFORE code landed.

**Win:** the plan-reviewer is doing its job. ~13 plan-time concerns surfaced and fixed pre-spawn this sprint. Estimated rework avoided: a path-escape bug, a cross-Python-version regex landmine, a misnamed config field, a noise-concern cascade on every /xp-accept. Each would have been ~hours of close-time work.

### 2. Accepts interleave with subsequent plans
**v3.11.0:** lead idle while teammates worked; all accepts happened at the end.
**v4.0.0:** the lead planned story-002 while story-001 ran async, planned story-003 while 001 + 002 ran async, then accepts fired as each notification landed:
- story-003 notification arrived first (smallest job) → accepted + closed → continued planning
- story-001 notification arrived second → accepted + closed (reviewer caught path-escape bug, fixed inline)
- story-002 notification arrived third → accepted + closed

This is the explicit design from v4.0.0 — and it worked exactly as intended.

### 3. Per-increment review surface stays small
**v3.11.0:** post-batch close-review faced the full sprint diff (typically 60+ findings; sprint-105 close-cycle was a 5-round marathon).
**v4.0.0:** each story-close ran `/xp-quality-review` on the cumulative-since-merge-base diff (story-scoped, not sprint-scoped). Findings per close-cycle:
- story-003: 0 reviewer findings (truly clean)
- story-001: 1 reviewer finding (path-escape — fixed inline in same close-cycle)
- story-002: 0 reviewer correctness findings + 1 debt (system_context_cli.py 523 lines > 500)
- story-004: 1 simplification finding (guard duplication — fixed inline by reviewer)

Sprint-close /code-review will still face the cumulative diff — but the per-story floor has already caught the obvious stuff.

## Validation observations

### What worked
- **Teammate spawn lifecycle is clean** — `claude -p` headless + `--plugin-dir ${CLAUDE_PLUGIN_ROOT}` produces a teammate that loads xp-agents and follows TDD/review/commit gates. All 3 teammates self-promoted to `reviewing`, all wrote their report file, all exited 0.
- **Hooks fired as designed** — TDD tracker, review-cycle gate, file-domain validate, verify-touch — all surfaced in teammate transcripts (5-32 PreToolUse mentions per teammate). No silent skips.
- **Worktree cleanup ran** — all three teammate worktrees cleaned post-merge via `/xp-story-close` Step 7b.
- **Commit attribution works** — every teammate's commits landed on the right story branch and merged cleanly to sprint-107 base.
- **Risk-classifier + enriched reviewer split paid off** — story-004's `RISK=high SIGNALS=behavioral-split,marker-lifecycle,guard-duplication,lifecycle-pair` got the elevated review focus and the reviewer found the guard-duplication issue. Smaller stories (001-003) classified `RISK=low` and the unenriched reviewer self-find still caught the story-001 path-escape (luck, not directed attention — see [risk-classifier rubric broadening idea](RISK_CLASSIFIER_RUBRIC_BROADENING.md)).

### What didn't work / still gaps
- **`/xp-plan-reviewer` does not surface its review output to the main agent.** Each invocation returned only "run /xp-assign"; the lead had to query `events.jsonl` to read concerns. Filed as debt `5e180220db1a`.
- **`.assign-pending` marker leaked into solo flow.** After story-004's plan-review, `.assign-pending` armed even though story-004 is solo (no teammate to spawn). The lead had to manually `rm` the marker before continuing to TDD. Filed as concern via memory (`feedback_assign_midsprint_skip_branch` notes the recurring issue).
- **`xp-risk-classifier` rubric is narrow.** Three RISK=low calls were on-rubric (pure-function, schema-extension, validation) but missed real risk dimensions on story-001 (combinatorial-data-table, path-traversal, cross-runtime-portability). Filed as debt `8e4728768671` with the [project-agnostic rubric broadening idea](RISK_CLASSIFIER_RUBRIC_BROADENING.md).
- **Teammate-commit recording gap** — retro Try #3 wanted to verify teammate worktree commits appear as SMM commit events. Spot check: `events.jsonl` shows commits per story-id (40 mentions for story-001, 29 for story-002, 23 for story-003, 19 for story-004 — but these are mostly merge-fallback). Per-commit recording from inside the teammate worktree is NOT visible in the main SMM events stream during the teammate run; commits show up at /xp-story-close merge time. **Gap confirmed**; needs a dedicated story to add the recording shim.
- **`save_sprint.run/save` layer inversion** — sprint_cli now imports from skills/, documented but ugly. Filed inline in sprint_cli comments; future cleanup if pattern broadens.

## What we didn't measure (honest limits)
- **Wall-clock comparison to v3.11.0** is not strict — sprint-107 stories are different work than sprint-105's, so per-story durations aren't directly comparable. The qualitative finding (accepts interleave instead of batching) is real; the quantitative speed-up requires running the same work under both shapes which is not feasible mid-release.
- **Per-tier model behavior** — all 3 teammates ran Opus 4.7 [1M]. We did not exercise per-story `executor_model` overrides (haiku for story-003, sonnet for 001/002 would have been right under a richer rubric). Validating the `executor_model → --model` flag end-to-end is future work.
- **Failure modes not tested** — no teammate crashed mid-run, no merge conflict surfaced, no acceptance test failed irrecoverably. The pipeline's recovery paths (stale-spawn detection, debug-and-re-run) ran on a happy-path sprint. They need adversarial probing in a future story.

## Verdict

**KEEP the per-story pipeline.** v4.0.0 ships as designed and the architecture's promised wins materialized: plan-time concern surface (~13 concerns fixed pre-implementation this sprint), accept-as-they-land interleaving, per-story close-review scoping. The two structural gaps (`/xp-plan-reviewer` output suppression, `.assign-pending` solo-leak) are debts with concrete fix paths, not architecture problems. The risk-classifier rubric narrowness is also a debt, not a roll-back trigger.

No regression against v3.11.0 baseline behavior surfaced. Sprint-107 shipped 5/5 stories with all gates green. Move forward on this baseline; sprint-108 picks up the recorded debts.

## Follow-up debts created this session
- `5e180220db1a` — /xp-plan-reviewer suppresses output to main agent
- `8e4728768671` — xp-risk-classifier rubric broadening (with [idea doc](RISK_CLASSIFIER_RUBRIC_BROADENING.md))
- `23c492fe63ad` — system_context_cli.py 523-line file split
- `35b9f08a95ac` — sprint_cli.py 595-line file split (story-004 grew it further)
- (existing) `6171a386de82` — resolves_link_rate identical-ts edge case
- (existing) teammate commit-recording gap — needs dedicated story in next sprint

# Changelog

History prior to v4.0 lives in [`changelog_pre_v4.md`](changelog_pre_v4.md).

## v4.4.1 — Fix teammate prompt-file /tmp collision across sessions

Free-branch fix. The teammate spawn-prompt file was the last piece of teammate state still living at a flat, cross-project-colliding `/tmp` path — the same class of bug the v4.3.2/v4.4.0 log-isolation work fixed for the forensic `.log`. TDD-ordered and reviewed before merge.

- **Teammate prompt files are now namespaced per project.** `/xp-assign` had the orchestrator write each teammate's spawn prompt to a flat `/tmp/prompt-<story-id>.txt`. Story ids repeat across projects, so two concurrent xp-agents sessions in different projects that assign the same story id clobbered each other's prompt. The prompt now lives beside the log under the per-project dir (`/tmp/xp-agents-teammates/<project-id>/<name>.prompt.txt`), exposed via a new `spawn_teammate.py --print-prompt-path` query flag mirroring `--print-log-path`; `/xp-assign` queries the collision-safe path to write the prompt. A shared `_project_dir` helper gives logs and prompts one source of truth for the project-id token. `--prompt-file` is now optional: when omitted or empty, `spawn_teammate` re-derives the same deterministic path from `--name` + `--smm-dir`, so the spawn command carries no queried value that would have to survive a separate shell invocation. `--print-prompt-path` fails loud if it can't create the (externally required) prompt dir.

## v4.4.0 — Remove the risk classifier; reviewer self-triages; live teammate log

Sprint-113. The per-increment review floor no longer runs a separate risk classifier — the reviewer judges risk itself — and a stuck teammate is now diagnosable mid-flight. Every change TDD-ordered and reviewed before merge.

### Review floor

- **The `xp-risk-classifier` agent is removed.** It never gated whether the (expensive) reviewer ran — it only handed an optional "look harder at X" hint at ~55–90s of pure serial latency, and the cheaper model was triaging risk for the stronger one on the same inputs. The reviewer (`xp-code-reviewer` §1c) now **self-triages** risk from the diff plus its injected Constraints pillar and elevates the risky angles itself (state/lifecycle/concurrency, security-sensitive input, cross-contract schema, large mechanical sweeps), and down-rates diffs that match a documented convention. No coverage is lost.
- **`/xp-quality-review` collapses to a single unconditional reviewer spawn.** The classifier spawn (old Step 1.4) and the `## Review Focus` / `RISK=high` / `SIGNALS=` enrichment plumbing are gone; the single-spawn invariant is preserved. A redundant preload `## Design Context` block (a second render of the Constraints pillar built only for the classifier) was dropped — the reviewer receives Constraints via SubagentStart injection.

### Teammates

- **A stuck teammate is diagnosable mid-flight.** The forensic `.log` was already line-flushed and live on disk during a run, but its path was surfaced only on failure and `/xp-assign` pointed diagnosis at the task output (empty until exit) while wrongly implying the output filter tees. `spawn_teammate.py --print-log-path` now prints the deterministic project-scoped `.log` path, `/xp-assign` surfaces it as a `tail -f` target right after spawn, and the diagnostic docs are corrected (the task output holds only the final one-line summary).

### Internal

- Teammate in-place detection (env-name + marker) was DRY'd into a single `worktree.in_place_teammate_from_env` helper across its three call sites.
- Fixed a worktree-cwd test-isolation leak: an ambient `os.getcwd()` under a teammate worktree misdetected ~85 hook tests as teammate runs, failing the pre-commit gate; the test harness now neutralizes the ambient cwd.

## v4.3.2 — Teammate spawn reliability; kickoff question cap; log isolation

Free-branch fixes hardening CLI-teammate spawns, plus a kickoff UX fix. Root-caused from a real cross-project failure (a teammate killed mid-work). Each change TDD-ordered, risk-classified, and reviewed.

### Teammate spawn reliability

- **The output filter no longer kills a healthy teammate.** Its no-progress deadline no longer preempts the 900s spawn watchdog. The old 600s default fired during legitimately *silent* tool calls (a nested review, an acceptance-test run); because the filter is the teammate's sole stdout reader, its exit then deadlocked the otherwise-healthy teammate with no result. Primary liveness is now the watchdog (it kills `claude -p`, the stream EOFs, and the filter's no-result path fires); the filter keeps only a **longer** backstop deadline (watchdog window + grace + margin, overridable via `XP_TEAMMATE_FILTER_TIMEOUT`; `0`/≤0 disables it) that never fires during healthy work but still catches a spawn-side wedge where the stream neither advances nor EOFs.
- **`run_with_tee` survives the filter dying.** A `BrokenPipeError` on stdout stops writing to stdout but keeps draining the child to the log, so the teammate always runs to completion and the raw log stays the source of truth. It reports `stdout_broken`, and the spawn **skips** the rc=0 in-progress→reviewing promote (leaving the story in-progress with a warning, prompt preserved for re-spawn) only when the filter died **before writing the report** — a benign late pipe-close after a completed run still promotes normally.
- **Forensic logs are project-scoped.** Teammate logs move from a flat `/tmp/<name>.log` to `/tmp/xp-agents-teammates/<project-id>/<name>.log`, so two xp-agents sessions in different projects spawning same-named teammates (`worktree-story-001`) no longer stomp each other's logs.
- The subprocess tee + liveness watchdog were extracted into `teammate_runner.py` (behavior-preserving) to keep both files under the size cap.

### Kickoff

- **The "Default model for teammates?" question fits the AskUserQuestion 4-option cap.** It listed 5 options and errored on the first call every session; it now offers 4 buttons (`haiku`/`sonnet`/`opus`/`inherit orchestrator`) with `fable` reachable via the automatic "Other" free-text (validated against the token set), losing no capability.

### Housekeeping

- Idea note proposing removal of the `xp-risk-classifier` from the per-increment review floor (`docs/ideas/RISK_CLASSIFIER_REMOVAL.md`).

## v4.3.1 — Story-close reviewer-fix guard; resolver test coverage

Free-branch follow-ups from adopted retro Tries.

- **Story-close won't discard an uncommitted reviewer fix.** A fix applied during the close review lands in the teammate worktree; if left uncommitted, the merge + worktree cleanup silently dropped it. `close_common.py merge` gains a `--review-clean-cwd` backstop that refuses the merge when the teammate worktree is dirty (after the review, not just before), so the lead commits the fix first. Solo and other close flows are unchanged (backward compatible).
- **Coverage:** integration test for `resolve_review_worktree`'s orchestrator-context fallback through the *real* closing-scan (previously only the own-worktree path and a mocked fallback were covered).

## v4.3.0 — Teammate effort dimension; worktree-detection hardening

Sprint-112. The teammate tier picker now carries a second per-story knob — reasoning **effort** — wired end-to-end (recommend → forward → spawn), plus two cross-cutting worktree-detection fixes. Each change TDD-ordered, risk-classified, and reviewed.

### Teammate effort dimension

- **`spawn_teammate` accepts `--effort`** and forwards it to the headless `claude -p` alongside `--model`, guarded by a support matrix (`tier_wire.effort_supported`). An unsupported model+effort pair (e.g. `haiku`, or an inherited/unknown model) is **dropped with a stderr note** rather than erroring the spawn — it fail-safes to the model default.
- **The plan-reviewer recommends an effort per story** via `metadata.recommended_effort` on the same `tier-recommendation-<story>` decision event, gated to effort-supporting tiers (`sonnet`/`opus`/`fable`; never `haiku`/`in-agent`). Effort is scoped explicitly as a Claude Code knob.
- **`/xp-assign` consumes the recommendation** end-to-end: the preload emits `RECOMMENDED_EFFORT` from the winning event, and the skill sets the story's `executor_effort` and forwards `--effort` to both the worktree and in-place spawns.
- The per-tier effort support matrix was corrected against the current Claude API (Sonnet 5 added `xhigh`), collapsing the tier-gate to binary: `haiku` supports no effort; `sonnet`/`opus`/`fable` support the full `low..max` range.

### Worktree detection

- **`/xp-quality-review` binds to the invoker's own worktree** (cwd walk) over the global closing-scan, fixing a CWD-misdetect that could hand a teammate another worktree's diff (the scan is now fallback-only in orchestrator context).
- **`is_worktree_teammate`'s leaky-env leg is marker-guarded centrally**: `XP_TEAMMATE_NAME` is trusted only when a live in-place marker exists, so a lead that inherited the var is no longer misidentified as a teammate at any of its callers. `smm_dir` self-resolves from the `SMM_DIR` env; the guard fails closed.

### Housekeeping

- Shipped idea notes moved to `docs/completed`.

## v4.2.1 — Teammate boundary hardening, tier-wire consolidation, fable tier

Free-branch backlog cleanup from the group-4 retros. Each change TDD-ordered, risk-classified, and reviewed with `Resolves-Event:` trailers.

### Teammate boundary

- **CLI teammates are now blocked from lead-owned lifecycle skills** (`xp-accept`, `xp-story-close`, the `*-close` family, etc.). A `PreToolUse:Skill` gate lets a teammate run only the review cycle (`xp-quality-review`); everything else is the lead's. Fail-closed — a new shipped skill is blocked for teammates until explicitly allowlisted (superset-guard test). Fixes an in-place teammate driving its own accept/close and inverting the flow past the lead's `/xp-accept`.
- **Teammates are told the session review cadence** at SessionStart, instead of relying on the lead hand-writing it into the spawn prompt.
- **In-place commit attribution no longer trusts a leaky `XP_TEAMMATE_NAME`** unconditionally: `spawn_teammate --in-place` writes a lifetime-scoped marker that `commit_handling` requires before recovering the teammate name from the env, so a lead with a leaked var + stale assignment isn't mis-attributed.

### Tier picker

- **`fable` is a first-class teammate tier** — the most powerful/expensive tier, top of the ladder (in-agent < haiku < sonnet < opus < fable). Recommendable by the plan-reviewer, defaultable, and offered at kickoff (previously a valid `executor_model` the picker could never pick).
- **Single-source tier-wire constants** (`smm/tier_wire.py`): the model vocabulary, config tokens, and the tier-recommendation/tier-override wire strings are consolidated from scattered, divergent copies; shipped prose is pinned to the constants by binding tests.
- **Ambiguous re-review retracts a stale tier recommendation** — the plan-reviewer emits a same-topic retraction (null model) so an earlier non-ambiguous pick can't win the reverse-scan.

### Tests

- Consolidated the duplicated `_slice` prose helper into the shared `tests/_md_helpers.py`.

## v4.2.0 — Group-4 backlog: structural refactor, debt sweep, teammate tier picker, risk-classifier broadening

Four milestones off the group-4 plan branch (sprints 108-111), each TDD-ordered with per-story review and `Resolves-Event:` trailers.

### Teammate tier picker (M3)

- **Per-story `executor_model` recommendation drives teammate spawns at the right tier.** `xp-plan-reviewer` writes a tier-recommendation decision event for each unambiguous plan; `/xp-assign` reads it (universal — solo too), spawning at the recommended tier or asking once on divergence, with a `tier_override` audit signal feeding retro accuracy.
- **`TEAMMATE_CONFIG` session marker** (`{enabled, default_model}`) set via a bundled kickoff question; `/xp-schedule` gates teammate mode on it (OFF → auto-solo). Absent/corrupt fail-safes to inherit-orchestrator, never blocks a spawn.
- **Solo execution shape:** a solo story runs its execution in a cheaper in-place teammate in the main checkout (`spawn_teammate --in-place`) — no worktree to isolate; `execution_mode` stays solo.

### Risk-classifier broadening (M4)

- **`xp-risk-classifier` rubric broadened beyond state/lifecycle/concurrency** with six project-agnostic signals (path-traversal, input-validation, combinatorial-data-table, cross-runtime-portability, file-size-creep, schema-cross-contract) + a decision matrix; thresholds defer to the host project's own standards (no baked-in cap).
- **Per-signal reviewer enrichment:** `xp-code-reviewer` §1c maps each signal to a concrete angle to hunt when a `RISK=high` focus names it.
- **Design-context input:** `/xp-quality-review` now feeds the classifier the project's Constraints pillar as a `## Design Context` block, so it down-rates diffs matching a documented convention instead of false-flagging them (fixes the diff-only false-flag).

### Structural + process (M1, M2)

- **Engine-layer sprint save** — `save_sprint.run/save` relocated out of the skill layer; `sprint_cli` imports it with no `sys.path.insert` shim. Over-cap files split at cohesive boundaries.
- **`Resolves-Event:` trailer pre-merge gate** — close surfaces when eligible commits touching tracked concern/debt files carry trailers below the 80% threshold (advisory, non-blocking). Plus five smaller deferred-debt fixes (plan-reviewer output surfacing, stop-hook close-phase ordering, perf, analyzer fixture, cascade quirk).

### Convention

- **Agent/skill/preload budgets are character-based** (`round(chars×1.125/10)×10`); the last line-based budget test was removed as drift.

## v4.1.1 — Triage-sweep fixes (M1-M10)

Free-session sweep delivering 10 ordered milestones from the kickoff triage backlog (4 retro Tries + 14 debts + 7 concerns adopted, 2 debts deferred, 1 concern dropped). Each milestone shipped TDD-ordered with `/xp-quality-review` + `Resolves-Event:` trailer; all 5774 plugin tests pass post-sweep.

### Behavior fixes

- **M1: verify_acceptance forwards `SMM_DIR` into AC subprocesses.** `_run_commands` and `_run_sprint` now inject `env={**os.environ, "SMM_DIR": str(smm_dir)}` via a new `_ac_env(smm_dir)` helper, so ACs that reference `$SMM_DIR` work on rerun without relying on the caller having exported it (sister-concern of `feedback_acceptance_command_path_drift`). Tests strip `SMM_DIR` from `os.environ` to model the production gap that `_SMMTestCase`'s pin would otherwise mask.
- **M2: close-cycle Stop-gate names all three close phases in canonical order.** `_BLOCK_MESSAGE` previously omitted Step 4b's `/code-review high`. Now lists `/security-review` (Step 4) → `/code-review high` (Step 4b, gated on `RUN_FULL_CODE_REVIEW=true`) → `xp-close-reviewer` (Step 4.5). Test pins canonical order via `assertLess` substring-position so a reversed-order regression can't slip through `assertIn`.

### Agent / skill prose

- **M3: xp-plan-reviewer surfaces concerns/assumptions/blocking-questions in its final message.** New `## Final Message` section requires every reply to end with four enumerated blocks (Concerns, Assumptions, Blocking questions, Next step) plus an empty-case clause for each. The main agent no longer has to dig into `events.jsonl` to find what the reviewer recorded. Doctrine-prose test mirrors `test_sequential_pins.py`, scoped to the section so partial-bullet gutting can't slip through file-wide grep.

### New primitives

- **M8: `markers.warn_once(smm_dir, marker, message, agent_id, *, severity="low")`.** Replaces the hand-rolled marker_exists → concern-append → marker_write dance for session-gated warnings. Returns True if fired, False if already-warned. Lazy-imports `_common`/`concerns` so hook scripts that only need `marker_*` don't pay the import cost. Caller (`save_sprint._warn_sister_skip_once`) collapses to a two-line wrapper that resolves agent_id from cwd. Future warn-once needs (Q1(c), N-th language detection mismatch) should call this rather than copy the pattern.
- **M9: `smm.glob_translator.glob_to_regex(pattern: str) -> str`.** Consolidates two near-duplicate translators (`triage._glob_to_regex`, `sister_tests._compile_source_pattern`). Both prior forms had an outer `?` making them effectively equivalent for project-relative paths — the audit determined the differences (`(?:.+/)?` vs `(?:.*/)?`) were cosmetic, not behavioral. The unified primitive uses triage's spelling as canonical. 12 new behavior tests pin zero-or-more `**/`, trailing `/**`, single-segment `*`, `?`, bracket classes, and malformed-bracket fallback.

### Refactors

- **M4: `_JS_UNIT_SKIP_SUFFIXES` tuple extracted in `sister_tests.py`.** All three js_unit rules now reference the constant; adding a new flavor like `.test.mts` lands in one place.
- **M5: `_load_sister_tests()` helper in `test_system_context_schema.py`.** Collapses two duplicate `sys.path.insert`/try-import/finally-remove blocks.
- **M6: `_cmd_edit_test_layout` collapsed to 3-line delegation; null-unset hint generalized.** The pre-validation in the test_layout edit cmd was redundant — `save_system_context`'s validator already wires `_validate_test_layout`. Collapsed to the `_cmd_edit_acceptance_surfaces` shape; the "pass `null` to unset" hint moved into `_cmd_edit_field`'s save-error path, gated on `_OPTIONAL_TOP_LEVEL_FIELDS` membership so future optional fields inherit the UX. File: 523 → 493 LOC (partial credit toward concern `15fc02bb40f4`).
- **M10: `save_sprint._resolve_project_root` delegates to `worktree.resolve_git_root`.** Eliminates the duplicate ancestor-walk. Now honors `GIT_DIR` env override and submodule `.git` files via `git rev-parse --show-toplevel`. Verified no production code sets `GIT_DIR` — behavior delta is strictly positive.

### Test-fixture churn

- **M7 → M10:** M7 swapped `_make_git_project`'s `git init` fork for a `.git/` mkdir-stub (~500ms parallel-CI saving). M10's `git rev-parse` swap stopped accepting the stub (no HEAD/refs/objects), so the fork was reverted as the correctness floor. M7's commit message and docstring both flagged this exact dependency.

### Triage-sweep stats

- 4 retro Tries adopted (trailer gate, layer inversion, SMM_DIR fix, file splits — last three of which are partially or fully delivered here).
- 14 debts triaged (12 adopted, 2 deferred: tier-picker design, risk-classifier rubric broadening — both larger plan-shaped work).
- 7 concerns triaged (6 adopted, 1 dropped: commit-cadence discipline issue).
- 16 commits on branch `paulingalls/free-2026-06-29-triage-concerns-debts`. 5774 tests pass.

## v4.1.0 — Sister-test discovery + V4 pipeline validation

Project-generic sister-test auto-inclusion driven by a new `system_context.test_layout` field, plus the deferred sprint-105 validation capstone closing out the v4.0.0 paradigm shift. Shipped via the per-story teammate pipeline itself (3 parallel teammates + 1 solo wiring + 1 capstone) — the decomposition was the live test bed.

### Sister-test discovery (M-1)

**Pure-function primitive in `plugins/xp-agents/skills/xp-sprint-start/scripts/sister_tests.py`** discovers existing sister-test files for source paths in any story's `file_domain`. The auto-include runs inside `save_sprint.run()` so sprint mutations that introduce a new story (or new source) get their sister tests appended without manual bookkeeping.

- **10 BUILTIN_LAYOUTS**: `python_pytest`, `go_native`, `js_unit` (jest/vitest/bun), `rust_cargo`, `ruby_rspec`, `java_junit`, `csharp_xunit`, `elixir_exunit`, `swift_xctest`, `php_phpunit`. Each is a `TestLayout` carrying `TestLayoutRule[]` with `source_pattern` / `stem_extractor` / `test_glob` (+ optional `skip_basenames` / `skip_suffixes` / `source_excludes`).
- Customer overrides via `system_context.test_layout.overrides` for projects whose convention isn't covered.
- Cross-version-portable glob compiler (`_compile_source_pattern`) — token-walks mid-pattern `**` because `PurePosixPath.match` doesn't honor it until Python 3.13.
- Path-escape guard rejects resolved candidates starting with `/`, `../`, or equal to `..` so customer-authored `{dir}/../...` templates can't escape `project_root`.
- Brace-aware throughout: source_pattern, test_glob, AND source_excludes route through `_expand_braces` for symmetric semantics.

### New `system_context.test_layout` surface (M-1)

Optional top-level field on `system_context.json` declaring which sister-test convention the project uses.

- **Schema enum** (`_VALID_TEST_LAYOUT_CONVENTIONS`): 10 builtin names + `unknown` + `custom`. Drift-locked against `BUILTIN_LAYOUTS.keys()` via `TestTestLayoutConventionEnumLock`.
- **`stem_extractor` enum** (`_VALID_STEM_EXTRACTORS`): schema validator rejects unknown extractors at write time. Drift-locked against `STEM_EXTRACTORS` registry.
- **New CLI subcommands**: `system_context_cli.py edit-test-layout` (stdin `null` unsets, `{}` rejects) and `get-test-layout`.
- **xp-system-analyzer Step 3.8**: probes 10 marker sets; writes detected convention (or `unknown`); records `assumption` event when multiple markers match.

### save_sprint.run/save split (M-1)

`save_sprint.py` now exposes both:
- `run(data, smm_dir)` — full pipeline: sister discovery → atomic save → milestone transition → accept-marker handling. Called by `sprint_cli._cmd_create` and `_cmd_add_story` (structural sprint mutations).
- `save(data, smm_dir)` — atomic write only, no side effects. Symmetry helper / test surface; status-flip callers (`/xp-accept`, `/xp-schedule`) bypass save_sprint via `store.edit_story` to preserve the M1 impact-zone constraint.

### sprint_cli dup-id rejection (M-1)

`_cmd_add_story` rejects duplicate-id payloads (exit 1 + clear stderr message). Guard runs AHEAD of `save_sprint.run()` so a dup never triggers run()'s side effects.

### Soft-warn-once for missing test_layout (Q1(b))

`save_sprint._warn_sister_skip_once(smm_dir, reason)` appends one low-severity concern per session when `test_layout` is unset, `convention='unknown'`, or `project_root` can't be resolved. Persisted via `SISTER_TEST_LAYOUT_WARN` marker (SessionStart sweeps it). Survives the `sprint_cli`-as-subprocess model.

### V4 pipeline validation capstone (M-1, sprint-105 carryover)

`docs/ideas/V4_TEAMMATE_PIPELINE_VALIDATION.md` documents the live observation of v4.0.0's per-story teammate pipeline running on sprint-107 itself. Verdict: **KEEP** — no regression vs v3.11.0 baseline.

### Idea docs filed for sprint-108

- `RISK_CLASSIFIER_RUBRIC_BROADENING.md` — broaden xp-risk-classifier signals beyond state/lifecycle/concurrency (project-agnostic shapes; debt `8e4728768671`).
- `TEAMMATE_TIER_PICKER.md` — 4-layer design: kickoff bundle for teammate-support + default model; /xp-schedule respects flag; /xp-assign universal entry; xp-plan-reviewer recommends executor_model per story (debt `ccf0cc5e13d8`).

### Notable debts filed for sprint-108

- `5e180220db1a` /xp-plan-reviewer output suppression (load-bearing for tier picker)
- `23c492fe63ad` / `35b9f08a95ac` / `e428c29f0edf` file-size cap violations (3 engine + 3 test files)
- `8ccf898d97d3` duplicate glob translators
- `ba6d355070c6` verify_acceptance.py SMM_DIR propagation
- `ebda28b72eac` stop-hook close-cycle message missing /code-review mention
- `d0c2f84acdf5` _resolve_project_root duplicates worktree.resolve_git_root
- `b380e493e7a7` discover_sister_tests N×M tree walks at scale
- `f32e57c380ec` warn-once primitive generalization
- Plus `aa468aa96fb3`, `823f7ba4a56f`, `d77c1785873d`, `e7578400e015` (flag-cascade closure quirk), `fe953be9e665` (analyzer Step 3.8 fixture), `5c63d3ac4248` (save() dead-API), `0aa5e8be097a` (test sys.path shim duplication), `bf30e8462e1b` (in-place dict mutation).

### Gates
- /security-review clean at sprint-107 close AND plan-close.
- /code-review high ran at sprint-107 close (10 findings → 7 fix + 2 debt + 1 concern) AND plan-close (10 NEW findings → 3 fix + 2 concern + 5 refuted).
- xp-close-reviewer ran at sprint-107 (4 concerns → 2 fix + 2 debt-pinned) AND plan-close (5 concerns → all debt-pinned, 0 Blocks).
- Full suite: 5752 passed, 2 skipped.

### Honest release-hygiene note
This v4.1.0 version bump landed as a post-merge `[release]` commit on main, NOT before the plan-close merge as `feedback_release_bump_before_close` prescribes. The commit immediately preceding this one (b6d860cf, plan merge) shipped v4.1-content under the v4.0.0 version string for the brief window before this bump landed. Sprint-108 retro should capture the gap.

## v4.0.0 — Systemic Quality v2: per-story teammate pipeline + cross-language review floor

This release ships two milestones from the **Systemic Quality v2** plan.

### Paradigm shift (M-2: per-story teammate planning pipeline)

**CLI teammates moved from batch fan-out to per-story plan→review→spawn loop.** v3 spawned the whole frontier in one `/xp-assign` call after a single batch plan. v4 plans ONE story at a time, runs `/xp-review-plan`, then `/xp-assign` targets the lowest-id un-spawned story, creates its branch, and spawns ONE teammate. Loop until the frontier is spawned. **Old teammate sessions don't transfer; existing workflows that batch-plan multiple stories will not work as before.**

- `/xp-assign` is per-invocation single-spawn (auto-detect lowest-id un-spawned via `find-teammate-worktree`)
- `/xp-schedule` teammate-mode handoff points at the per-story loop, no longer at batch planning
- Per-story `executor_model` schema slot (`sonnet`/`opus`/`haiku`/`fable`/null) drives the spawned teammate's `--model` flag; default null inherits orchestrator. Set per story via `sprint_cli edit-story` when tier matters
- Sprint-render surfaces `executor_model` + `execution_mode` so `sprint_cli render` shows tier assignments at audit time
- `/xp-assign` Step 5 surfaces teammate exit explicitly: read the report file, surface failures, run `/xp-accept` before further plans/spawns

### Cross-language per-increment review floor (M-1)

A new automatic risk-classification + enriched-review pipeline catches correctness issues earlier in the loop, on every code change in any language.

- **New `xp-risk-classifier` agent** (haiku-tier, `tools: Read`-only). Reads the staged diff, emits a strict first-line `RISK=high|low` verdict. Anti-prompt-injection guardrails on every input surface.
- **`xp-code-reviewer` enriched**: state/lifecycle + concurrency angle, bounded self-verify with category-spare clause, `## Review Focus` recognition for risk-classifier-driven targeting.
- **`/xp-quality-review` Step 1.4 + 1.5**: MODE-gated classifier dispatch + single-spawn `xp-code-reviewer` with conditional `## Review Focus` prepend (no fan-out — risk-gated targeting). `## Changed Files` block + `CLOSE_DIFF_UNAVAILABLE` flag in preload.
- **Cross-language regression-replay integration test** (`test_review_regression_replay.py`): Python pre-fix shapes + seeded TS/Rust + mixed-extension anti-leak. Proves preload surfaces every language extension to the classifier.

### Plugin-namespace scoping (hardening)

A `target_routing.strip_our_namespace` helper extraction closes a previously-silent third-party plugin false-positive class. Five hook sites now reject `otherplugin:<our-skill-name>` qualified forms that previously could trip our flags:

- `review_cycle_done._detect_target` — explicit allowlist (no substring), `_TARGET_BY_NAME` dict
- `subagent_stop._is_quality_review` — exact-match (closes `xp-quality-reviewer-helper` family)
- `subagent_stop._is_code_review` — substring kept for instance-id support, namespace-gated
- `accept_terminal._is_terminal_target` — `xp-agents:`-scoped frozenset lookup
- `subagent_start._DISPATCH` — bare-name keys, namespace-strip before lookup
- `pre_tool_skill` — exact-match instead of `'code-review' in skill`

### Other hardening + ergonomics

- `TEAMMATE_GUIDE` adds **Escalate on Ambiguity**: teammates raise a blocking concern + stop on ambiguous specs instead of guessing
- `executor_model` lookup in `/xp-assign` is fail-loud — three-step capture/check/parse so tier drift on a malformed sprint.json fails fast instead of silently inheriting orchestrator
- `pre_tool_write` blocking message rewritten to per-story shape (matches the new pipeline)
- `_TASK_CREATION_NUDGE` after `/xp-assign` rewritten for per-story coordination tasks
- `close_cycle_stop_gate` split into defer-window + abandonment-timeout (was one knob serving two purposes)
- `close_common._append_merge_commit_event` resets the orchestrator's review cycle after `--no-ff` merge (fixes a latent gate-latch for the next solo commit on a sprint branch)
- `VALID_EXECUTOR_MODELS` widened to include `fable`

### Removed: pre-tool Bash file-modification coordination gate

Sprint-105 story-004 originally added a hard-block coordination gate for Bash file-mods (`mv`, `sed -i`, redirects, etc.) over teammate-claimed files. **It was reverted entirely.** Three rounds of `/code-review high` found ~50 distinct edge-case bugs in the shlex-based detector (`<<<` here-strings mis-skipping, `bash --posix -c` bypassing recursion, `cp -t destdir` flag-with-value, `sed -i f1 f2 f3` multi-file, heredoc body re-tokenization, etc.) — bash is not statically parseable with shlex. Whack-a-mole was the wrong approach.

The honest model: `pre_tool_write` covers Edit/Write (the common case for code changes); CLI teammates run in isolated git worktrees so cross-agent damage from Bash file-mods only materializes at story-close merge where git is the deterministic safety net. Trust+merge handles this class.

What survives from story-004: the TEAMMATE_GUIDE `Escalate on Ambiguity` section.

### Deferred

- **Story-005** (real ≥3-story Sonnet teammate batch validation under the new pipeline) was deferred from sprint-105 to a post-v4.0 session. Validating the per-story pipeline against the **shipped** marketplace plugin (not in-dev code) is the only honest signal; that requires this release to land first.

### Docs

- New `CHANGELOG.md` cut at the v4 boundary; v1–v3 history archived as `changelog_pre_v4.md`
- `docs/ARCHITECTURE.md`, `docs/SMM_DESIGN.md`, `README.md` swept to reflect the no-Bash-gate model and the per-story `/xp-assign` shape

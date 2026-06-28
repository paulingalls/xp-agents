# Changelog

History prior to v4.0 lives in [`changelog_pre_v4.md`](changelog_pre_v4.md).

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

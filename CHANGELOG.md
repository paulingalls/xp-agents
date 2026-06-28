# Changelog

History prior to v4.0 lives in [`changelog_pre_v4.md`](changelog_pre_v4.md).

## v4.0.0 — per-story teammate planning pipeline (paradigm shift)

**This is a paradigm shift in how CLI teammates run.** v3 used a batch fan-out: lead plans the whole teammate batch, `/xp-assign` splits the plan per teammate and spawns them all in parallel. v4 replaces this with a per-story plan→review→spawn loop: the lead plans ONE story at a time, runs `/xp-review-plan`, then `/xp-assign` targets the lowest-id un-spawned story, creates its branch, and spawns ONE teammate. Loop until the frontier is fully spawned. Old teammate sessions don't transfer; existing workflows that batch-plan multiple stories will not work as before.

### What changed

- **`/xp-assign` is per-invocation single-spawn.** It auto-detects the next un-spawned story via `find-teammate-worktree`, no longer takes a multi-story plan. Spawns one teammate per invocation.
- **`/xp-schedule`'s teammate-mode handoff points at per-story plan→review→spawn** rather than batch planning.
- **Per-story `executor_model` schema slot** (`sonnet` / `opus` / `haiku` / `fable` / null) drives the spawned teammate's `--model` flag. Set per story via `sprint_cli edit-story` when tier matters; default null inherits orchestrator model.
- **Plugin-namespace scoping** on review-cycle gates: `target_routing.strip_our_namespace` extraction; three hooks (`review_cycle_done`, `subagent_stop`, `accept_terminal`) and two more sites (`subagent_start`, `pre_tool_skill`) now reject third-party `otherplugin:<skill>` qualified forms that previously could trip our flags.
- **`review_cycle_done._detect_target` is an explicit allowlist** (no substring matching) — closes false-positive routes like `xp-quality-reviewer-helper`, `xp-housekeeper-helper`.
- **`subagent_stop._is_quality_review` is exact-match** — closes the parallel defect class for the SubagentStop hook.
- **TEAMMATE_GUIDE adds "Escalate on Ambiguity"** — teammates raise a blocking concern + stop on ambiguous specs instead of guessing.
- **`/xp-assign` Step 5 surfaces teammate exit explicitly** — read the report file, surface failures, ensure `/xp-accept` runs before further spawns.
- **executor_model lookup is fail-loud** — three-step capture/check/parse in `/xp-assign` SKILL.md so tier drift on a malformed sprint.json fails fast instead of silently inheriting orchestrator.
- **Sprint-render surfaces `executor_model` + `execution_mode`** so `sprint_cli render` shows tier assignments at audit time.

### What removed

- **The pre-tool Bash file-modification coordination gate** (`bash_target_detect.py` + the file-mod block in `pre_tool_bash.run`). Three rounds of `/code-review high` found ~50 distinct edge-case bugs in the shlex-based detector; bash isn't statically parseable. `pre_tool_write` covers Edit/Write (the common case for code changes); CLI teammates run in isolated git worktrees so cross-agent damage from `mv` / `sed -i` / redirects materializes at story-close merge where git is the deterministic safety net. Trust+merge is the honest model.

### Docs

- New `CHANGELOG.md` cut at the v4 boundary; v1-v3 history archived as `changelog_pre_v4.md`.
- `docs/ARCHITECTURE.md`, `docs/SMM_DESIGN.md`, `README.md` swept to reflect the no-Bash-gate model and the per-story `/xp-assign` shape.

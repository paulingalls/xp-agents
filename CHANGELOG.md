# Changelog

## v3.1.42 — sprint-087: retire `read_events_raw` (M-5) + system-context CLI shrink + LIKELY→MAYBE rename + decide.py scan consolidation

### M-5: retire `_common.read_events_raw` (sprint-087, stories 001-003)

Final milestone of the system-context-redesign plan. `_common.read_events_raw` — the unlocked event-read helper — is now retired in favor of the M-4 `read_events_locked` wrapper. Story-001 + story-002 migrated ~141 test call sites across 18 files (tranche A: 6 high-count hook tests; tranche B: 11 remaining hook tests + `tests/engine/test_smm_cli.py`). Each test file gains a module-level `_WATERMARK_ID = "test-<slug>"` constant matching the production-script convention; identifier convention recorded as a curated convention (`test-watermark-slug-convention`).

Story-003 deleted the function, the unused `_MAX_EVENTS_FILE_SIZE` constant, and the now-unused `parse_jsonl` import from `_common.py`. Replaced the per-site `_MIGRATED_SITES` allowlist (14 entries + meta-programming machinery) in `test_read_events_migration_parity.py` with a single **negative-space AST guard** that `rglob`s the entire plugin tree and asserts zero `_common.read_events_raw` Call nodes. Self-extending — catches re-introduction at any new site, not just enumerated ones. Matches the absence-of-flag invariant-guard convention.

Two honesty fixes surfaced during migration and landed alongside: dead `patch("commits._common.read_events_raw")` mock target (commits.py never called `read_events_raw` — calls `_common.load_events_with_resolutions`) swapped to target the function actually called, making the "`events=` kwarg skips disk read" assertion load-bearing instead of vacuously true; same fix for `work_selection_decide.py` mock target. Class `TestReadEventsRaw` in `test_common_smm.py` renamed to `TestReadEventsLocked` so the 4 boundary tests (valid / malformed / empty / missing) cover the canonical wrapper directly.

### `system_context_cli.py` shrink: caps + nested-field-edit extractions (story-005)

`smm/system_context_cli.py` shrank from 642 → 458 lines (under the 500-line target). Two new modules mirror the existing `system_context_retire_cli.py` + `system_context_edit_cli.py` extraction convention:

- **`system_context_caps_cli.py`** (97 lines) — `_COUNT_CAP_TABLE` (gated-list field → `(soft, hard, retire-subcmd)`) and `cmd_append_to_list` cap-enforcement gate for the `add-*` dispatch.
- **`system_context_nested_field_cli.py`** (123 lines) — the 4 stack/branching nested-field commands (`cmd_edit_stack_field`, `cmd_edit_branching_field`, `cmd_get_stack_field`, `cmd_get_branching_field`) collapsed to 1-line dispatchers over private `_edit_nested_field(args, parent_key, seed)` + `_get_nested_field(args, parent_key)` helpers. Distinct docstrings preserved on the public commands; the parent key and seed dict are the only per-command differences.

Both modules re-imported by `cli.py` via the documented `from <mod> import name as _name` shim; `__all__` documents the public-attribute surface; identity contract pinned by sister tests via `assertIs`.

### `/xp-quality-review` gains COURAGE-FIX framing (story-006)

`xp-quality-review/SKILL.md` Step 3 (Act on Subagent Findings) gains a new bullet alongside the existing "Fix directly (preferred — courage)" guidance:

> **Fix overlapping open concerns now (COURAGE-FIX).** If an open plan-review or close-reviewer concern's `files` overlap the diff you're already touching, fix it now while the file is open — file overlap is in scope, no re-litigation. Don't defer to "LIKELY ADDRESSED" triage at close time. Resolve via the `Resolves-Event:` trailer in the same commit.

Pulls concerns forward before they reach close as heuristic-triage candidates. Pin test `TestQualityReviewFramings` covers both framings with anchor-bounded section slicing per the SMM convention (Step 2 → Step 3 slice asserts RESOLVE framing; Step 3 → Step 4 slice asserts the `COURAGE-FIX` token + `"fix it now while the file is open"` + `"file overlap is in scope"`).

### `LIKELY ADDRESSED` → `MAYBE ADDRESSED` atomic rename (story-007)

The "LIKELY ADDRESSED" annotation overclaimed: file-overlap-after-timestamp is a heuristic candidate that requires LLM judgment, not a fix. The label is renamed to "MAYBE ADDRESSED" to bias triage toward judgment rather than drop. Atomic across 22 files / ~80 hits:

- `"LIKELY ADDRESSED"` → `"MAYBE ADDRESSED"` (prose, annotations)
- `"LIKELY_ADDRESSED"` → `"MAYBE_ADDRESSED"` (constants, section headers)
- `"likely_addressed"` → `"maybe_addressed"` (~55 hits: `draft_summary.py` JSON key + 6 test files + `event_metadata.py` + skill prose)
- `"likely-addressed"` → `"maybe-addressed"` (hyphenated docstring form)
- File + class rename: `test_draft_summary_likely_addressed.py` + class `TestDraftSummaryLikelyAddressed` → `*_maybe_addressed.py` + Maybe variant

Landed atomically per the SMM-shared-field-rename wisdom.

### `work_selection_decide.py` force-drop scans: 3 reads → 1 (story-008)

The force-drop path (`drop`, `defer --force-drop` with refs, convention dedupe) used to do up to 3 separate `_common.read_events_locked` calls under flock. Refactored to a single locked read fed through 3 pure filter functions:

- `_convention_topic_exists_filter(events, topic) -> bool`
- `_count_prior_defers_filter(events, ref_ids) -> int`
- `_cascade_ids_filter(events, tokens) -> set[str]`  *(new — was inline in `_build_drop_event`)*

`_build_drop_event` and `_build_defer_event` now accept a `load_events: Callable[[], list[dict]]` instead of `smm_dir`. `run()` supplies a memoized closure that does one locked read on first invocation; lazy initialization preserves the "no-tokens drop skips disk read" perf guard. Net per invocation:

- force-drop with cascade + prior-defer + convention checks: **1 read** (was 3)
- plain drop with no hex tokens: **0 reads** (preserved)
- adopt or triage path: **0 reads**

7 new pure-filter unit tests (`TestForceDropFilterFunctions`) land alongside — no SMM I/O, no flock.

### `concerns.py` qualified-import alignment (story-004)

`scripts/concerns.py` was the lone outlier among 16 migrated sites — used bare-name `read_events_locked(...)` via `from _common import` instead of the canonical qualified `_common.read_events_locked(...)`. Aligned to the qualified form so the call site is grep-able as the canonical helper invocation. The mock-patch target on `test_bash_failure.py:223` follows mechanically (`patch("concerns._common.read_events_locked")`).

### Tests

4817 → 4816. (TestParity 4 tests + `_MIGRATED_SITES` 14 generated tests removed in story-003; replaced by 1 broader negative-space guard. 7 new filter unit tests + 2 framing pin tests + caps/nested-field wiring tests added.) Ruff + pyright + tests gate clean throughout.

## v3.1.41 — sprint-086 (M-4 read_events_locked migration) + edit-* CLI for capped lists + analyzer principles routing

### M-4: extract `_common.read_events_locked` helper (sprint-086)

`scripts/_common.py` gains `read_events_locked(smm_dir, slug) -> list[dict]` as the canonical wrapper for the locked-read pattern that was duplicated across ~17 sites. Story-001 lands the helper + the AST guard extension that accepts it as a valid migration target. Story-002 migrates 13 canonical sites (8 in `scripts/` + 5 in `skills/*/scripts/`) plus drops the now-unused `import read_delta` at each. Story-003 migrates the 4 atypical multi-line sites (`concerns.py` 2x, `lint_resolution.py`, `_common.load_events_with_resolutions`), documents `prompt_nugget.py:61` as the legitimate exception (advances watermark, uses both tuple elements), and adds a whole-directory AST guard (`TestNoInlineCanonicalReadDeltaFull`) that fails CI on any future re-introduction of the inline pattern outside the helper's own body.

### `edit-*` CLI for capped lists

`system_context_cli.py` gains five `edit-*` subcommands symmetric with `retire-*`: `edit-module`, `edit-principle`, `edit-convention`, `edit-project-specific`, `edit-acceptance-surface` (commit `3e3ba882`). The four object-shaped commands accept a JSON patch on stdin (`{"field": "new value"}`; `null` clears a key); `edit-convention` takes a JSON-encoded replacement string and looks up by index or substring (mirrors `retire-convention`).

Why: `/xp-system-context` had no surface for single-field refinement on an existing capped-list entry — the analyzer fell back to `create` (whole-file rewrite, overwrites every field) or `retire+add` (loses the entry's `ts`/`source` metadata). The new commands merge a patch into the matched entry, re-validate via the whole-doc save path (`ValueError` rolls back without saving or emitting an event), and short-circuit on no-op patches.

Implementation lives in new `smm/system_context_edit_cli.py`, re-exported via the split-shim convention. 5 new `STATUS_ACTION_EDIT_*` constants registered in `_NON_HOOK_PRODUCERS`. Shared `resolve_convention_index` helper extracted from `retire_cli` and consumed by both retire-convention + edit-convention.

Tests: `TestEditCommands` + `TestEditConvention` + `TestEditNullClearsKey` etc., split into a new `test_system_context_cli_edit.py`. `TestRetireCommands` extracted alongside into `test_system_context_cli_retire.py` per the proactive-file-split convention (`test_system_context_cli.py` was 964 lines, now ~768).

### Analyzer prompt: durability lens + principles routing table

`agents/xp-system-analyzer.md` gains two load-bearing additions discovered after auditing the analyzer's output across two real projects (commits `25bd028e`, `c897c6ba`):

1. **Durability lens at top.** New opening sentence: *"Every entry must still be true a year from now without curation; transient content (changelogs, status, implementation details that turn over with each refactor) belongs in git history or code comments instead."* Filters every field, not just principles.

2. **Positive routing table on the principles bullet** replaces the prior negative trailing list. 6 rows route the common misshapen entries to their real destinations (`stack` field, `architecture_overview`, `modules`, `conventions`, `project_specific`, or "consolidate" for near-duplicates). One trailing line names the non-destinations (implementation details, phase status, bug-fix/refactor/race-condition narratives → code comments, git history, sprint.json). Field discipline bullets reordered to `modules` → `project_specific` → `principles` so the table's destinations are already-defined by the time the analyzer reads it.

The analyzer prompt + `PROCESS_GUIDE.md` are also taught about the new `edit-*` subcommands — Update-mode gains a refinement paragraph alongside the existing cap-awareness paragraph. PROCESS_GUIDE's System Context paragraph collapses the per-CLI enumeration to `add-*` / `edit-*` / `retire-*` family references.

### Known issue

Schema validators (`_validate_module`, `_validate_principle`, `_validate_project_specific_entry`, `_validate_acceptance_surface_entry`) accept unknown keys silently — a typo like `{"naem": "x"}` would persist to disk through any of `add-*`, `edit-*`, or `create`. Pre-existing surface; filed as debt `7431a629b4b1`, not addressed in this release.

Tests: 4791 → 4817.

## v3.1.40 — sprint-084 + sprint-085: system_context redesign (M-1 + M-2) + close-cycle bypass age gate

### Breaking change: `add-decision` CLI renamed to `add-principle`

The `system_context_cli.py add-decision` subcommand was renamed to `add-principle` as part of the schema field rename `key_decisions` → `principles`. Out-of-tree scripts invoking `add-decision` will fail with `invalid choice: 'add-decision'` at first run after upgrade. There is no alias / deprecation shim — the rename landed atomically (decision `b6107e89b7db`). Migration: replace every `add-decision` invocation with `add-principle`; the stdin JSON schema is unchanged.

### Schema rename + soft/hard count caps + string caps (sprint-084 M-1)

`system_context.json` schema canonicalized: `key_decisions` → `principles`; `sources` field dropped. Existing on-disk files load cleanly via silent canonicalization in `load_system_context` (in-memory only — see issue note below). 9 new string caps and 5 count-cap pairs (soft / hard) land as named constants in `system_context_schema.py`. CLI gates `add-*` writes: at soft cap, stderr warns and write succeeds; at hard cap, the command refuses non-zero and names the matching `retire-*` subcommand. Pattern lives in `_COUNT_CAP_TABLE` as the single source of truth. Schema constants are pinned by `TestCountCaps`.

### Retire-\* CLI subcommands (sprint-084 M-1)

Five new subcommands hard-delete an entry from a capped list and emit a status event for traceability: `retire-principle <topic>`, `retire-module <name>`, `retire-project-specific <name>`, `retire-acceptance-surface <name>`, `retire-convention <index-or-substring>`. Substring path resolves to one entry (0 → not-found, ≥2 → ambiguous). Retire-\* family extracted to `system_context_retire_cli.py` via the documented re-export shim convention. New `STATUS_ACTION_RETIRE_*` event-metadata constants registered in `_NON_HOOK_PRODUCERS`.

### `add-project-specific` CLI gate (sprint-085 M-2)

`project_specific` entries now route through `_COUNT_CAP_TABLE` like the other four capped lists. Sprint-084 added the constants and the `retire-project-specific` CLI but left the add path bypassing the gate — the constants were decorative. Wired as a two-line delegator to `_cmd_append_to_list`. Argparse + dispatch dict reordered so `add-*` entries match `_COUNT_CAP_TABLE` order (modules, conventions, principles, project_specific, acceptance_surfaces) for scan consistency.

### Analyzer prompt + PROCESS_GUIDE: discriminator framing (sprint-085 M-2)

`xp-system-analyzer.md` Step 4 rewritten with per-field discriminator tests and negation framing — keeping principles identity-shaped rather than diary-shaped. Four discriminator phrases (navigation-index for modules, reversal for principles, session-relevance for `project_specific`, retire-first guidance under Update mode) are pinned verbatim by `test_agent_prompts.py` so future prompt drift breaks loudly. `PROCESS_GUIDE.md` §System Context surfaces the reversal-test discriminator + the principles soft/hard caps + `retire-principle` as the over-cap remedy. Preload subset literals (`_preload_base.sh`) flip `key_decisions` → `principles` for plan-reviewer and close-reviewer renders. The analyzer Step 4 JSON template is synced to the actual schema caps with per-field cap annotations; sync-test extension pins 14 string caps + 5 count caps via per-case subTests so per-field drift can't first-fail-mask-rest.

### Close-cycle bypass age gate (sprint-084 M-1 follow-on)

`close_cycle_stop_gate._record_bypass` previously consumed the `CLOSE_CYCLE_ACTIVE` marker unconditionally when `stop_hook_active=True` was observed with the marker present. Claude Code latches `stop_hook_active` session-wide once any Stop hook returns a reason, so an earlier latch BEFORE a genuine close cycle started caused the first Stop after the cycle to burn the just-written marker. Fix: gate marker consumption on marker file mtime age via new `_CLOSE_CYCLE_AGE_THRESHOLD_SEC = 600`. Young markers stay so `xp-close-reviewer` consumes them normally on the same cycle; old (abandoned) markers still get consumed so subsequent Stops don't re-fire the gate.

### Known issue: legacy on-disk format not auto-rewritten

`load_system_context` canonicalizes legacy `key_decisions` / `sources` in-memory but does not auto-save the canonical shape — legacy files stay legacy on disk until an `add-*` / `retire-*` / `edit-*` op triggers `save_system_context`. The planned one-release backward-compat window will silently never close for projects that only read the file. Tracked as concern `ed63c17e572d`; fix lands in a future release (opportunistic write-on-load or a one-shot migration CLI).

## v3.1.39 — free session: skill hardening, reviewer-scoped system_context, close-cycle bypass diagnosis

Free-session sprint resolving sprint-083 retro carry-forwards. Eight commits on `paulingalls/free-2026-05-15-harden-skills-tries-context`.

### Skill discipline: autonomy-nudge bypass guard (commit `07495156`)

A Claude Code `<system-reminder>` ("work without stopping for clarifying questions") was mis-applied as license to skip prescribed `AskUserQuestion` gates in `/xp-kickoff` Step 2 (session mode) and `/xp-plan` Step 1 (source gathering). Both gates now carry an inline `**Unconditional gate — do not skip.**` marker; `/xp-plan` Step 1 gains the `(ALWAYS)` header convention used elsewhere. New pin test `test_skill_askuserquestion_discipline.py` asserts the marker is present in the right region of each SKILL.md; tightened to a stable ASCII prefix so an em-dash auto-format normalization doesn't silently break the pin. Discipline lives at the two specific sites that were bypassed — most other `AskUserQuestion` calls are correctly conditional, so no universal rule lands in PROCESS_GUIDE.

### file_domain drift: stop polluting open-event surface (commit `e8e91044`)

`xp-story-close` Step 1b previously appended a `--type concern --kind file_domain_drift` event on every drift, re-polluting the open-concern surface each sprint close. Convention `9074fed13abf` declares drift a planning signal that retro surfaces from `cascade_size`, not from concern events. The Step 1b emission is gone; `validate-domain` runs with stdout silenced (drift writes naturally to stderr); `|| true` keeps the close pipeline non-blocking on drift-over-tolerance. The close-reviewer agent still raises drift as a Concern bullet when severity warrants — independent emission path, unaffected. Pin test ensures the emission can't silently return.

### Reviewer-scoped system_context renders (commits `f5c6754d`, `fd1714ef`, `62bfc19e`)

`system_context.json` is loaded into the main agent's session-start context, but the two highest-leverage reviewers (`xp-plan-reviewer`, `xp-close-reviewer`) previously saw none of it. The plan-reviewer cited the layered "system_context=WHERE / milestone=WHY / story=WHAT" model in its instructions without actually receiving the WHERE; the close-reviewer reviewed diffs without knowing the project's stack, conventions, or prior architectural decisions. Goal #3 wires both with scoped subsets at a fraction of full-file token cost.

**Commit A — CLI foundation:** `system_context_cli.py render` gains `--sections <csv>` and `--topics-only <csv>` flags. `--topics-only` collapses sections with identifier fields (`topic` for `key_decisions`, `name` for `project_specific`) to TOC bullets, leaving other sections full. Renderer consolidated through a single internal `render_subset(data, sections, topics_only, include_doc_header)` entry point; `render_markdown` and `render_section` become explicit thin wrappers. The function raises ValueError on misuse (ineligible `topics_only`) so direct Python callers fail loud.

**Commit B — plan-reviewer wiring + PROCESS_GUIDE:** New `system_context_render_to_tempfile_for <kind>` helper in `_preload_base.sh` centralizes the per-reviewer section subset. `xp-review-plan/scripts/preload.sh` emits `SYSTEM_CONTEXT_RENDERED=<tempfile>` when `system_context.json` exists; `xp-plan-reviewer.md` Inputs section adds the file as the WHERE layer. PROCESS_GUIDE gains a tight `### System Context` section listing the readers, the create/refresh skill, the patch CLI subcommands, and the empty-`test_command` auto-merge consequence. Plan-reviewer subset (~1.8K tokens) renders product/architecture/stack/modules/conventions/branching/acceptance full + key_decisions/project_specific topics-only.

**Commit C — close-reviewer wiring (4 close skills):** All four close-skill preloads (story/sprint/plan/free) emit `SYSTEM_CONTEXT_RENDERED` via a new `emit_system_context_rendered_for <kind>` helper (5 call sites collapse to a one-liner per the simplify rule-of-three). Each close-SKILL's `Agent()` prompt threads `SYSTEM_CONTEXT_RENDERED=<SYSTEM_CONTEXT_RENDERED>` to `xp-close-reviewer`; the reviewer agent is updated to Read the file when present and use it to flag convention/decision contradictions in the diff. Close-reviewer subset (~0.9K tokens) renders stack/conventions/branching full + key_decisions topics-only.

### Design doc: system_context redesign (commit `1780332f`)

`docs/ideas/SYSTEM_CONTEXT_REDESIGN.md` captures the audit + design discussion that ran across this session — drop `sources` (dead field with no consumer), rename `key_decisions` → `principles` with a reversal-test definition, tighten `modules.purpose` cap 200→100ch with a navigation-index discipline, add string-length + count caps on every uncapped leaf, new `retire-*` CLI subcommands + soft/hard cap warnings. Appendix lists 28 retirement candidates from this project's bloated `key_decisions` (42 → 14 architectural principles). Source for next-session's `/xp-plan`.

### close_started literal pin (commit `d38d8e89`)

`_preload_base.sh:emit_close_started_event` hardcodes the literal `"close_started"` in metadata JSON; `retro_metrics.security_close_ran` filters on the `STATUS_ACTION_CLOSE_STARTED` constant. Prior coverage only checked the runtime-emitted shape via another hardcoded literal at the consumer side — a bash-side typo could silently disable the security_checks=0 Courage rule with no test turning red. New pin test scopes its regex to `emit_close_started_event`'s function body (via brace-depth walk) so a future sibling helper adding `"action":"X"` elsewhere in the file can't false-pass. The adjacent consumer helper at `test_close_preloads_emit_shared.py:462` also imports the constant so producer and consumer pins now share a single failure surface.

### Close-cycle bypass: diagnosis + structural fix (commit `af8be2f9`)

Recurring concern `764dbea8d4b7` ("close-cycle gate bypassed: stop_hook_active=True with marker still set") had recurred across two consecutive sessions without root-cause investigation. Transcript analysis of session `136b9973` produced an empirical diagnosis: **Claude Code latches `stop_hook_active=True` session-wide once any Stop hook returns a `reason`** (e.g., `session_end_warning`'s nudge). It does NOT reset per-turn. Evidence: `session_end_warning` fired at 06:19:59 with a "Session-end checklist: 1 unresolved concern" reason; the flag stayed True through 45 minutes of work + many skill invocations until the single `close_cycle_stop_gate` fire at 07:05:49. Once the flag is latched, the gate's block message can no longer reach the agent reliably — the safety net is defeated.

Fix: when the bypass fires, the gate also consumes the `CLOSE_CYCLE_ACTIVE` marker. The cycle is empirically abandoned (the latched flag disables every subsequent gate fire); leaving the marker would cause duplicate concerns on every Stop for the rest of the session. The high-severity concern + stderr recovery prose remain — the user still sees what happened and what to do next session. Test renamed and assertion flipped; module + function docstrings rewritten to explain the structural reasoning without project-local IDs (which the historical-IDs emitter guard would otherwise reject).

### Deferred to next session

Try #3 (retire `_common.read_events_raw`) was deferred — the original Try description estimated "17 sites" but the actual scope is 142 test sites across 35 files. The Try itself said "at next /xp-plan" and naturally pairs with the system_context redesign sprint.

## v3.1.38 — sprint-083: probe surface retired, EVENT_CATEGORY enum, read_events_raw audit, security gate scoping

Sprint-083 shipped 6 stories.

### Story-001: probe surface decision

Retire the resolves-trailer probe surface. Evidence across this project and a downstream peer: 620+ commits, <1% probe firing, 0% adoption, ongoing migrating failure modes that kept producing carried retro Trys. Decision `2bcea1b6ecd0` retires the surface; convention `1b939cc2d4b0` (`probes-retired`) prevents reintroduction.

### Story-002: probe emission removal (PR 288)

Deleted `resolves_probe.py`, `story_probe.py`, `large_batch_probe.py` (~700 LOC) and their hook registrations. Stripped probe-caller blocks from `pre_tool_bash.py`, `pre_tool_skill.py`, `work_selection_decide.py`. Removed emission-side schema constants (`STATUS_ACTION_*`, `METADATA_KEY_PROBE_*`, `METADATA_KEY_STORY_CANDIDATE`, `SELECTION_REASON_*`). `duplicate_debt_probe.py` (different surface — Jaccard dedup at debt-write time) kept.

### Story-003: probe measurement removal (PR 289)

Deleted `_compute_probe_adoption`, `_classify_divert_reason`, `_normalize_file_set`, `_VALID_RESOLVES_TYPES` from `retro_metrics.py`. Removed measurement-side schema constants (`STATUS_ACTION_RESOLVES_PROBE`, `METADATA_KEY_PROBE_*`, `SELECTION_REASON_*`, `DIVERT_REASON_*`). Dropped `cwd` parameter from `_compute_resolves_link_rate` (no consumer). Scrubbed probe narrative from `xp-retrospective.md` and removed 5 project-local IDs from a pin test (project-generic constraint).

### Story-004: EVENT_CATEGORY enum (PR 290)

Introduced `EVENT_CATEGORY` StrEnum (`sibling_artifact`, `curation_pillar`, `transient`) with `_EVENT_CATEGORY_MAP` covering all 17 `EVENT_TYPE_*` values. Derived `_BUCKET_INTENTIONALLY_ABSENT` cleanly from the enum. `_COMPACT_INTENTIONALLY_ABSENT` derivation requires filter + override sets (`_COMPACT_INDEX_RETENTION_TYPES`, `_COMPACT_REFERENCE_TIED_TYPES`, `_COMPACT_RETAINED_TRANSIENT_TYPES`) because compact-absence is orthogonal to event category; orthogonality recorded as concern `410394eff46b` per sprint AC#3. Split-shim convention: `event_metadata.py` extracted at the 500-line trigger; source re-exports preserve every caller's import path.

### Story-005: read_events_raw audit (PR 291) + sprint-close fix-up

Audited all 12 `_common.read_events_raw` call sites in `plugins/xp-agents/scripts/`. Per audit-scope decision `981877ecab16` (user-confirmed migrate-all), every site migrated to `read_delta.read_delta_full(smm_dir, _WATERMARK_ID, update_watermark=False)[0]` — shared flock against single writer, sub-millisecond cost. Module-level `_WATERMARK_ID` constants (kebab-case of script name) per the `prompt_nugget.py` precedent; `concerns.py` has two constants for its two distinct call sites. New `tests/hooks/test_read_events_migration_parity.py`: byte-equal parity test (regression coverage) + per-site AST-walk enforcement (`TestNoReadEventsRawCallers`) pinning the migrate contract.

Sprint-close fix-up (concern `b5cae49b484f`): the original audit decision scoped to `plugins/xp-agents/scripts/`, missing 5 production callers in `plugins/xp-agents/skills/*/scripts/` (`debt_for_files.py`, `open_plan_concerns.py`, and 3 sites in `work_selection_decide.py`). Migrated atomically at sprint close + extended `_MIGRATED_SITES` to cover both `scripts/` and `skills/*/scripts/` so the AST guard catches regressions across both surfaces. Follow-up debt `ccfd95be6d3c` (helper extraction) and `d25645411b6e` (retire `read_events_raw` — only test-fixture callers remain) filed.

### Story-006: security_checks=0 retro gate scoping (PR 292)

Pivots the retro `security_checks=0` Courage rule from "any close cycle ran" to "a security-bearing close ran" (sprint/free/plan). Story-close has no Step 4 `/security-review` (the enclosing sprint-close covers it cumulatively), so story-close-only sessions were producing a spurious Courage Try every session. New `STATUS_ACTION_CLOSE_STARTED` constant; new `emit_close_started_event` helper in `_preload_base.sh` that the three security-bearing close-skill preloads call (story-close preload deliberately omits it). `retro_metrics.close_cycle_ran` → `security_close_ran`, gated on `close_mode in {sprint,free,plan}` via the new lifecycle event. Inverse-pin test asserts story-close emits no `close_started`; per-mode true-positive tests cover sprint/free/plan. Helper stderr is left visible — silent failure on the gate's emit-path would re-introduce the false negative this story exists to fix.

### Suite

4665 → 4687 (+22 net, ~169 probe-test deletions absorbed). Ruff + pyright clean across all 6 stories. Per-commit `Resolves-Event:` trailers link 12 audit decisions + reviewer-resolved concerns to their fixes.

## v3.1.37 — scheduled-overlap glob crash, Resolves-Event trailer convention, dropped-Tries cap

Free session addressing one bug report and three carried retro Trys.

### Commit 1: `scheduled_file_domains_overlap` — conservative-overlap=True on glob

`sprint_cli scheduled-overlap` crashed on a real story whose `file_domain` declared a glob (`packages/db/drizzle/meta/*`). `sprint_status.scheduled_file_domains_overlap` called `extract_file_domain_paths` without `cwd=` or `candidate_files=`, hitting the documented `ValueError` raise-on-glob (triage.py:129-132). The crash returned Python rc=1, indistinguishable from the function's intentional rc=1 ("no overlap") — `xp-assign`'s bash predicate treated rc!=0 as "ask user solo/parallel", silently degrading conservative-solo to a parallel prompt.

Fix: catch `ValueError` and return `True`. xp-assign picks solo on uncertainty. Option (b) `cwd=.` was rejected — planned sprint stories often declare paths that don't exist yet, so `Path.glob()` would expand to nothing and miss real overlap. Honest about the uncertainty.

### Commit 2 (Try 1): document Resolves-Event trailer convention in close skills

Adds a brief reminder line near the top of `xp-sprint-close/SKILL.md` and `xp-free-close/SKILL.md` describing the rule for closing carried retro Trys via `Resolves-Event: <try-id-or-ref>` trailers so `try_status` closes the loop. Housekeeping added the constraint (`19aeba3ccd53`) at session start; this commit covers the literal "(xp-free-close/xp-sprint-close templates)" parenthetical the constraint promised. Test catch: shipped SKILL.md must not reference this-project event IDs (the plugin ships to other projects where those IDs are meaningless) — kept the prose project-generic. Resolves Try decision `309e0eeb05ed`.

### Commit 3 (concern adopted): `_collect_dropped_tries_recent` — reverse-iterate with hard cap

Refactor mode. Old impl scanned the full events list, sorted by ts descending, then sliced `[:limit]`. As `events.jsonl` grows in long-lived projects, the scan is wasted work — drops are typically near the tail. Reverse-iterate with hard cap: early-break once `limit` matches are collected. Worst case unchanged (no drops in tail → full scan); best case dramatically improved (10 drops in last K events → K iterations).

Honesty pivot caught by the independent code reviewer: the original docstring claimed events.jsonl writes are "monotonic-ts in production" because ts is assigned inside the flock. Trace showed otherwise — `event_builder.build_event` assigns `ts` BEFORE `append_event` takes the flock, so concurrent writers can land events out of ts order by a microsecond-millisecond window. Updated docstring states "reverse file-order, not strictly ts-descending"; renamed the existing test from `test_surfaces_last_10_drops_by_ts_descending` to `test_surfaces_last_10_matching_drops_in_reverse_file_order` with an assertion verifying the actual file-order contract (the old name/assertion happened to pass because test data had file-order = ts-order). Resolves adopted concern `1a5a7a379467`.

### Investigation (Try 3): probe-selection-miss trace

Traced the divert at 2026-05-14T05:30:52 where probe surfaced only `86821b45ba14` (keyword+recency) but the commit at 05:31:15 resolved `8584032f0bbb` + `bc7b07e9e2ba`. Root cause: the probe fired BEFORE the closer-files were fully staged — `work_selection_decide.py` was modified at 05:31:01, after the probe at 05:30:52. No file-overlap match was possible at probe time. Not a probe bug; staging-timing issue. Follow-up concern `b7bf0f649c3d` recorded for gating probe emission on git-commit bashes only. Resolves Try decision `65ca91ea654b` via status `240cd46c301b`.

---

## v3.1.36 — carried retro Trys: probe pairing, superseded backstop, _seed_* extraction

Three commits addressing the three carried retro Trys from the prior session.

### Commit 1: extract `_seed_*` probe test helpers to `conftest._ProbeTestHelpers`

Consolidates four near-identical test helpers (`_seed_concern`, `_seed_discovery`, `_seed_debt`, `_seed_anchor_in_cycle`) into the `_ProbeTestHelpers` mixin. Eliminates ~80 lines of duplication across `test_resolves_probe_pool.py` and `test_resolves_probe.py`. Cycle-aware variants take `cycle_id` + `close_mode` as keyword-only params; an internal `_seed_event` absorbs the shared kwargs-build + `make_event` + `append_safe` pattern. Resolves debt `0fd6e85c77a4`, adopted Try `4ffc1d86f563`, plus plan-reviewer concerns `b9a27fdd20ae`, `cb22d1f4847b`, `8f04cdd94e82`.

### Commit 2: gate superseded-decision detector on `metadata.resolves` backstop

Extends `concerns.py:detect_conflicts` to treat `metadata.resolves` equivalent to `metadata.supersedes` as a supersedence declaration. Symmetric with the existing `pre_tool_bash._decision_metadata_declares_supersedence` advisory nudge. Rationale: a later decision carrying `metadata.resolves=[prev_id]` triggers the cascade auto-closer (STRONG link), so flagging the prior as unresolved would contradict the link hierarchy. Resolves concerns `266b3a8b42ea` + `404f81ffb2ad`, adopted Try `faab3805afc2`. Bonus: code-reviewer caught + fixed a stale docstring in `pre_tool_bash.py`.

### Commit 3 (Try 1, pivoted): probe-commit pairing fix

The prior session's retro flagged 4/4 `newer-than-snapshot` diverts on sprint-082. Initial diagnosis was incomplete (recorded as discovery `ceef689a6536`); a deeper trace this session found the actual root cause was NOT in the staleness mechanism (which works as designed) but in `retro_metrics._compute_probe_adoption`'s probe-commit pairing.

Algorithm bug: `sorted_probes` iterated oldest-first, each probe consuming its earliest unmatched commit. When two probes by the same agent preceded one commit (probe A at T=0 misses a not-yet-existing concern Z; concern Z created at T=20m; probe B at T=37m sees Z; commit at T=40m references Z), the commit got attributed to probe A. The classifier then asked "did A see Z?" — no — and labeled the divert `newer-than-snapshot` even though the agent had used probe B's candidate set.

Fix is one line: `sorted(probes, ..., reverse=True)`. Probes now iterate newest-first, consuming the earliest still-unmatched commit each preceded — which gives the LATEST probe before each commit the pairing it deserves.

Residual concern `acac09099204` (low severity): the greedy newest-first heuristic is a net improvement but not a true maximum-matching algorithm; n-probe-m-commit cases with m≥2 may still mispair in some configurations. Carried for a future session.

---

## v3.1.35 — dropped-Try resurfacing fix; xp-accept auto-close + JIT-next continuation

Free session investigating why dropped retro Trys kept resurfacing across sessions in two downstream projects (SimplyHuman, Legacy). Forensic trace identified a single architectural gap: the retrospective agent had **zero memory** of prior drops. Three layers combined to bury them — `signal_events` excluded `status` events, `MAX_RETRO_HISTORY=1` truncated history, and `retro_history.py:125-131` actively stripped dropped Trys from `previous_retros` before the agent saw them. Plus a rule-firing issue: `security_checks=0 → Fix` triggered on non-close sessions, regenerating the same Try every session whether or not a close cycle even ran.

### Commit 1: surface drops via `digest.dropped_tries_recent`

Adds a new digest channel scanning the FULL events list (not session-scoped) for status events with `metadata.disposition="dropped"` AND non-empty `metadata.resolves`. Slimmed to `{id, ts, content[:200]}`, sorted ts-descending, capped at 10. Agent prompt at xp-retrospective.md:28 documents the channel; the Cross-Session Trends rule at line 208 instructs the retro analyst to scan before proposing — matches as Keeps under Courage rather than re-proposing.

### Commit 2: gate `security_checks=0` rule on close-cycle presence

Adds `digest.close_cycle_ran: bool` (any event in `unanalyzed` carrying `metadata.close_cycle_id`). The Security Practices rule at xp-retrospective.md:165 now requires `close_cycle_ran=True` before flagging `security_checks=0` as Fix under Courage. Non-close sessions no longer spawn spurious `/security-review` Trys. Test seeds use the realistic shape (`EVENT_TYPE_CONCERN` with `kind=security` + `close_cycle_id`) per `_close_pipeline_shared.md:31` — close-pipeline never stamps commits with `close_cycle_id` in production. Resolves concerns 9f653bdf1aef + lint debt 4e264fba67b7.

### Commit 3: convention emission on `defer --force-drop`

New `--record-convention-topic SLUG` + `--record-convention-content TEXT` flag pair on the `defer` subparser. When paired with `--force-drop`, the helper atomically appends a `convention` event alongside the drop status event as a durable suppression record — future retros see it via `digest.signal_events` and can suppress same-shape Try proposals. Constraints: topic must use `retro-drop-` prefix + kebab-case slug (prevents collision with `retro-try-<slug>` adoption topics, validated by `_KEBAB_SLUG_RE`); both flags required together; only honored with `--force-drop`. Idempotent — re-drops with the same topic skip the convention emission AND print a stderr notice surfacing the discarded rationale (honesty: silent first-write-wins would lose user signal). Policy "convention on force-drop only" encoded as decision `bcdad3b2ad05` so future re-decisions trip the superseded-detector. Resolves concerns 8584032f0bbb + lint debt bc7b07e9e2ba.

### Commit 4: remove dead strip in `retro_history.py`; expose `disposition="dropped"` on try_status

Removes the 7-line filter that stripped dropped Trys from `previous_retros[0].try` before the agent saw them. The agent prompt rule at xp-retrospective.md:208 ("disposition='dropped' — do not re-propose") is now reachable for the first time. Drop memory is **double-walled**: `digest.dropped_tries_recent` (Commit 1) carries any session's drops; `try_status[i].disposition` carries the most-recent retro's drops in their original Try slot. Inverts FOUR pre-existing tests that pinned the strip contract (across `test_retro_history.py`, `test_retro_history_pipeline.py`, `test_retrospective_wiring.py`) plus two stale prose references. Resolves concern 86821b45ba14.

### Commit 5: xp-accept auto-close on all-E2E-pass + chain into next story

Two SKILL.md ergonomics fixes for the accept flow.

**Manual acceptance auto-close** — When every criterion is E2E-prefixed and all E2E commands exited 0, skip the AskUserQuestion prompt and proceed to Step 1.5 with disposition `done`. Symmetric to the automated path's existing "Auto-proceed without an extra confirmation prompt" rule (d6f54b25). Green tests are the confirmation. The prompt still fires when any non-E2E criterion exists or any E2E failed.

**Chain into next story** — New Step 8: if Step 7 (sprint review) didn't fire and `sprint_cli.py next-in-progress` returns a story id (a fresh JIT-promote from `/xp-story-close`), call `EnterPlanMode` so the plan + TDD cycle starts immediately on the next iteration. Previously the orchestrator stopped here and the user had to re-invoke `/xp-plan` manually.

---

## v3.1.34 — session_history wired into retro+housekeeper; decision-supersedence nudge; assorted hygiene

Four-track free session driven by an investigation into where `session_summary` is loaded — the answer was "only the main agent's kickoff preload," walling the highest-value consumers (retro analyst + housekeeper) off from cross-session narrative context. Plus three carried retro Trys, addressed in the same pass.

### Track 1: `session_history_cli.py` + freshness + retro/housekeeper wiring (4 commits)

Promotes the read side of `session_history.json` to a canonical CLI alongside `smm/retro_cli.py` / `smm/smm_cli.py`. The renderer that lived inside `skills/xp-kickoff/scripts/render_history.py` was misfiled — session_history is a general SMM artifact. New CLI is fail-loud on corrupt history (matches the smm/*_cli.py convention); kickoff wraps the invocation in `|| true` so a crashed CLI never blocks session start.

- **Freshness annotation**: each render of `### LAST_SESSION` annotates `(stale — N sessions ended without /xp-end-session since this summary)` when intervening sessions skipped `/xp-end-session`. Detection is timestamp-based via the existing `event_schema.sessions_since_event` primitive — `count == 0 → unknown`, `count == 1 → fresh` (the entry's own session_end), `count >= 2 → stale` with `skipped = count - 1`. Mechanically correct given that events.jsonl entries don't carry a `session_id` field; the plan-reviewer's session-id-pairing recommendation was diagnosed against an incorrect mental model.
- **Public helper**: `session_history.gather_recent_summaries(smm_dir, *, session_end_timestamps=None, limit=RECENT_SUMMARIES_LIMIT)` consolidates the formerly-duplicated retro and housekeeper logic. When `session_end_timestamps` is `None`, falls back to a fresh `read_session_end_timestamps` scan; callers with timestamps already in hand (retro pre-collects from in-memory events; materialize pre-collects from its aging scan) pass them in to eliminate double events.jsonl reads.
- **Wiring**: `.retro-input.json` gains a `recent_summaries` field adjacent to `previous_retros`; `.curation-input.json` gains the same field alongside `retro_history`. Agent prompts (xp-retrospective, xp-housekeeper) updated with parallel-but-divergent anti-retell guidance: retro emphasizes cross-session pattern detection; housekeeper emphasizes durable-wisdom-vs-noise framing.
- **Migration**: `render_history.py` (61 lines) and its test (226 lines) deleted; coverage migrated to `tests/smm/test_session_history_cli.py`. `pyrightconfig.json` extra-path entry retired in both root and plugin configs.
- **Format regression caught + fixed in-cycle**: the new `render_markdown` initially emitted a per-entry `### LAST_SESSION` header (the original emitted ONE header followed by N bodies). Caught by the close-reviewer, fixed before landing T1.C4; test strengthened to pin the single-header contract.

Resolves concerns 13dba721bf75 (freshness diagnosis), 6141441bbcb6 (cleanup gap), and the assorted in-cycle lint debts (06ed20cb1466, 4e54ca27b510, fdb41490825c).

### Track 2: split `test_resolves_probe.py` (1 commit)

Adopts the third-pass split named in the prior retro Try. Extracts three cohesive cluster TestCase classes (`TestFindProbeCandidatesInSprintBatch` + `TestFindProbeCandidatesOutMeta` + `TestFindProbeCandidatesDiscovery`, 387 lines) to a new sibling `tests/hooks/test_resolves_probe_pool.py`. Pure move — no shim required (test classes have no external importers); mirrors the precedent set by `test_resolves_probe_scoring.py` and `test_resolves_probe_staleness.py`.

Source file lands at 561 lines (1.12× the 500-line target — accepted residual; no further cohesive cluster remains, far better than the 1.9× starting point). Helper-extraction follow-up (`_seed_discovery` / `_seed_debt` / `_seed_anchor_in_cycle` + cycle_id-aware `_seed_concern` to `conftest._ProbeTestHelpers`) recorded as debt for a future commit. Resolves debt 4506169502b2.

### Track 3: strengthen plan-reviewer assumption directive (1 commit)

The retro flagged 4 consecutive sessions of zero-assumption plans on multi-story sprints. Root cause was the prompt itself, not a missing mechanical gate: section 6 of `agents/xp-plan-reviewer.md` was defensive ("only assumptions that **matter**") with no proactive directive telling the reviewer that *finding* implicit plan assumptions IS its job.

Rewrites section 6 with an active opener ("Read the plan and identify the implicit assumptions it rests on — bets about caller behavior, preserved contracts, customer intent, and unenumerated code paths. Surfacing them is your job, not the planner's."), keeps the significance filter, adds an explicit release valve ("Zero is a valid count when the plan genuinely rests on no significant assumptions"). No mechanical gate — size proxies don't correlate with assumption need, and the disease is the prompt not the absence of a counter. Resolves retro Try c8542c5f61be.

### Track 4 (pivoted): decision-supersedence nudge (1 commit)

Original retro Try framed the bug as a probe scoring problem (stale flag concerns surfacing in candidate selection). Mid-implementation investigation revealed the cascade in `resolution.py` already excludes flag-style concerns whose root is resolved — the probe filter would be redundant. The actual root cause is **silent decision-supersession**: a new decision emitted on a topic that has an unresolved prior decision, without declaring the supersedence. The cascade can't close the resulting superseded-decision flag because the prior decision stays unresolved.

Pivot: extend the existing `pre_tool_bash.py` decision-emit hook (which already nudges with open questions) to also nudge when the same topic has unresolved prior decisions. Suggests `metadata.supersedes` (suppresses the superseded-decision flag) or `metadata.resolves` (also cascade-closes the prior decision). Advisory only — agents emitting legitimate "split-into-aspects" decisions can ignore the nudge.

Refactor side-effects (per /simplify review):
- New `event_schema.METADATA_KEY_SUPERSEDES = "supersedes"` constant; replaced bare `"supersedes"` literal in `concerns.py:399`.
- Extracted `_parse_metadata_dict()` to dedupe JSON parse boilerplate across the two metadata-inspection helpers.
- Consolidated two adjacent `if args.get("type") == _common.DECISION` guards into a single block; share one events/resolutions load between both nudges (open-questions and same-topic).
- Extracted `_SAME_TOPIC_HEADER_TEMPLATE` constant; dropped misleading `agent_id` param from `_same_topic_decisions_context`.

Resolves retro Try 87ade402ec4f, concern ebcb854fcc93 (the divert case that proves the filter is needed), partial resolution of 404f81ffb2ad (the new-concern follow-up 266b3a8b42ea tracks the detector-side false-positive that remains for agents who ignore the nudge).

### Tests

4823 unit + integration tests pass, 1 skipped, 404 subtests passing. Each of 8 commits ran `/simplify` (3 review subagents in parallel) and `/xp-quality-review` (independent code-reviewer subagent); lefthook pre-commit (ruff, pyright, shellcheck, tests) green on every commit.

## v3.1.33 — cascade Try-drop to underlying debt/concern/discovery

Free-session fix for a long-standing dishonesty in the retro loop: a "dropped" Try kept resurfacing every session with a fresh ID. Live evidence — SimplyHuman 1Password debt `9c3f5406cacd` spawned 8 consecutive Tries despite repeated drops.

### Root cause

When the user dropped a retro Try via `/xp-work-selection drop`, only the Try IDs (the Try's own id plus chain refs from the `[refs: ...]` suffix) ended up in `metadata.resolves`. The underlying **debt / concern / discovery** the Try was about stayed open — and the retro agent obediently re-proposed a fresh Try about it the next session. Two leaks, one sending-side and one receiving-side:

- **Sending side**: `/xp-work-selection drop` didn't walk the Try's prose for hex IDs pointing at the root.
- **Receiving side**: `retro_metrics._build_retro_digest` filtered resolved **concerns** out of `signal_events` but not resolved **debts** (asymmetric). Even with sending-side cascade, a dropped debt would still appear in the next retro's input.

### Fix (3 commits, refactor-before-feature TDD)

- **Commit 1 (`cc67b6de`)** — symmetric receiving-side filter. `_build_retro_digest` now also strips resolved debts from `signal_events`. Two-line fix mirroring the existing concern filter, with paired pin tests (resolved → excluded, unresolved → retained).
- **Commit 2 (`687d5162`)** — pure refactor. Extracted `_build_drop_event` helper from the two duplicate construction sites (`case "drop":` and `if force_drop:`). No behavior change; existing tests cover both call sites unchanged.
- **Commit 3 (`673bd093`)** — content-scan cascade. `_build_drop_event` now scans post-suffix-strip content for 12+ hex IDs, filters them against `_common.PROBE_RESOLVABLE_TYPES` (`debt | concern | discovery`), and unions matching root IDs into `metadata.resolves` via the new `event_builder.merge_resolves` helper. Perf-guarded: `read_events_raw` is only called when content has hex tokens, and pinned by `test_drop_with_no_hex_tokens_skips_events_read`.

### Reuse / cleanup

- **`merge_resolves(event, ids: Iterable[str])`** extracted to `event_builder.py` from inside `extract_refs_suffix`. Both call sites now delegate — same dedupe semantics, defensive copy.
- **`HEX_ID_RE`** promoted from private `_HEX_ID_RE` in `retro_history.py`. `work_selection_decide.py` now imports the public name instead of reaching across modules into a `_`-prefixed symbol.
- **`_common.PROBE_RESOLVABLE_TYPES`** reused for cascade type filter — was duplicated as a local `_CASCADE_TYPES` constant.

### Tests (10 new in `TestDropContentCascade`)

- **Positive**: debt, concern, discovery in content prose all resolve via cascade.
- **Negative**: question / decision / unknown hex tokens do NOT resolve (type filter pins).
- **Dedupe**: ID in both content prose AND `[refs: ...]` suffix appears exactly once.
- **Force-drop parity**: same cascade fires via `defer --force-drop` codepath.
- **Multi-debt**: two debt IDs in content both cascade.
- **Perf-guard pin**: `_common.read_events_raw` is NOT called when content has zero hex tokens (mocked).

### Tests overall

- 4802 unit + integration tests pass, 1 skipped, 404 subtests passing.
- Lefthook pre-commit (ruff, pyright, tests) green on every commit in the cycle.

## v3.1.32 — teammate liveness watchdog + skill prose audit

Free-session release shipping two cohesive threads: a watchdog that bounds silent-teammate hangs to ~15 min recovery (was 31+ min, manual), and a focused audit of skill prose that cuts ~900 tokens per kickoff and removes 2 mechanical regression-pin tests.

### Teammate liveness watchdog (concern `e1a8f7e17d84`)

Sprint-082 saw a teammate hang silent for 31 minutes overnight before manual kill. Forensic autopsy of `/tmp/worktree-story-006.log` showed the spawned `claude -p` made two successful Read calls in the first 10 seconds, then went completely silent until killed — the next API request to the model after the second tool_result never produced a token.

- **`--include-partial-messages`** added to the spawned `claude -p` command. Without it, `--output-format stream-json` only emits one stdout line per content-block completion (1-4 lines per assistant message), so legitimate text/tool_use generation looks identical to a hang from outside the process. With it, model output streams as 50-500 chunks per block (empirically: 351 `text_delta` events for a ~3500-token answer in 20s), giving the watchdog continuous mtime signal during real work.
- **`_ActivityWatchdog`** in `plugins/xp-agents/scripts/spawn_teammate.py`: daemon thread, pinged on each line read from the subprocess. After `_WATCHDOG_TIMEOUT_S` (900s = 15 min) of silence sends SIGTERM, waits `_WATCHDOG_KILL_GRACE_S` (10s), then escalates to SIGKILL — the latter because a child blocked in C-level `recv()` on the model API socket (the suspected hang mode) may not respond to SIGTERM. 900s sized at ~1.5x the longest legitimate thinking-on-large-context gap observed historically (~10 min on 256K-token inputs from story-008).
- **`run_with_tee` integration**: watchdog starts before the stdout-read loop, gets pinged on each line read, stopped in the finally block. Recovery handoff is to the existing `CalledProcessError` rc!=0 path — story stays in-progress, prompt file preserved for re-spawn.
- **TDD throughout**: 7 new tests across `tests/hooks/test_spawn_teammate_watchdog.py` (split from `test_spawn_teammate.py` to keep the original under the 500-line budget): `_ActivityWatchdog` unit tests for terminate-after-timeout, no-terminate-when-pinged, stop-prevents, terminate-failure-no-propagate, escalate-to-kill-on-TimeoutExpired; `run_with_tee` integration tests for terminates-on-silence and no-terminate-when-streaming.
- Constructor cleanup landed mid-cycle: switched `timeout_s`/`poll_interval_s`/`kill_grace_s` from default-bound to None sentinels resolved at call time. Prior defaults captured module constants at class-definition time, so `patch.object` in tests didn't reach `run_with_tee`'s construction path.

### Skill prose audit (~900 tokens saved per kickoff)

Used 16 parallel `skill-reviewer` subagents to audit all xp-agents skills with the load-bearing test: *"would removing this prose cause the LLM to make a different (worse) decision about which command to run, what to ask the user, or how to recover from an error?"* Bias was lean keep when unsure. Result: ~25 small cuts of helper-internal narration, restated state, and WHAT-not-WHY explanations across 12 files.

- **`xp-work-selection`**: dropped probe-refresh sentinel internals — the deleted block's own last sentence was "No manual signaling required — the helper handles it." If the LLM doesn't act on it, the LLM doesn't need it loaded into context every kickoff. WHY survives in the helper code comment + 2 tests pinning the contract.
- **12 other skills**: cuts to `xp-scaffold-acceptance`, `xp-accept`, `xp-story-close`, `xp-sprint-start`, `xp-plan`, `xp-assign`, `xp-kickoff`, `xp-free-close`, `xp-plan-close`, `xp-end-session`, `xp-quality-review`, `xp-stage-migration`. Pattern audit identified 4 recurring anti-patterns: helper-internal narration ("X auto-records Y"), architectural rationale not actioned by LLM, restated preload output, and inverse restatement of conditionals.
- **2 mechanical regression-pin tests deleted** (`TestAcceptSkillTextDocumentsMarkerConsumption`, `test_skill_skips_when_stage_ge_2`): both pinned prose that captured side-effects agents don't act on; their referenced concerns are no longer in active SMM events. **2 genuine regression-pin tests respected** — the audit broke 4 tests; individually evaluated each before deciding restore-or-delete.
- Audit method recorded as decision `858868d66d4e` so future audits trip the superseded-decision detector if they diverge.

### Tests

- 4790 unit + integration tests pass, 1 skipped, 404 subtests passing.
- Lefthook pre-commit (ruff, pyright, tests) green on every commit in the cycle.
- Empirical verification of `--include-partial-messages` will land at next teammate spawn — `/tmp/worktree-story-NNN.log` should contain hundreds of `stream_event/content_block_delta` lines per assistant message.

## v3.1.31 — xp-end-session honesty signal cleanup

Patch release tightening `/xp-end-session`'s `### UNCOMMITTED` count and the Step 5 nag prose so the honesty signal stops drowning real work in orchestration noise.

### What changed

- **`uncommitted_event_count`** (in `plugins/xp-agents/scripts/_common.py`) narrowed from "every event type except SESSION_SUMMARY post-last-commit" to "concern/debt/discovery only" via a new `PROBE_RESOLVABLE_TYPES = (CONCERN, DEBT, DISCOVERY)` constant. The probe (`find_probe_candidates`) only pools those three types as resolvable candidates, so they're the only types whose absence-of-resolution actually matters for the next session's signal quality. Status, goal, retrospective, decision, question, answer, and session_summary are now correctly excluded.

- **Shared `_last_index_of_type(events, etype)` helper** extracted from three sibling reverse-scan callers (`current_session_start_index`, `prior_session_end_ts`, `uncommitted_event_count`) — fourth caller triggered the rule of three. `PROBE_RESOLVABLE_TYPES` is also reused in `resolves_probe.py`'s in-batch sibling pool, eliminating a duplicate inline tuple.

- **Step 5 prose rewritten**: drops the "Consider committing" suggestion. Empty commits to clear the counter were the wrong fix the wrong prose was inviting — the SMM resolution chain (any event with `metadata.resolves`) closes targets without code changes. New prose suggests "drop now via `metadata.resolves`" (mirrors Step 3's auto-judge pattern) or "leave for triage" at next `/xp-work-selection`.

- **Step 1 prose** (manual edit, carried in this commit): clarifies that `### CANDIDATES` is a memory trigger for the agent, not the verbatim refinement source — aligns with the v3.1.28 fix that made `write_history.py` use the refined `session_summary` content for `session_history.json` instead of mechanical synthesis.

- **Step 3 prose** (manual edit, carried in this commit): drops the conservative "When multiple commits are cited, ALL must contribute to the fix — defer if any are unrelated" rule. The detector is purely file-overlap-based, so coincidental file-touches at unrelated commits would have produced false-defers on real resolutions. If any cited commit clearly fixes the concern's intent, auto-resolve and list only the contributing commits in `resolved_by_commits`.

### Tests

- New `TestUncommittedEventCount` (5 unit tests in `tests/hooks/test_common.py`) pins both axes of the new contract: empty list, post-commit count of concern/debt/discovery, exclude-noise post-commit, exclude-pre-commit, no-commit-means-all-actionable, and a mixed scenario (1 commit + 5 noise + 4 actionable = 4).
- `test_draft_summary.py` (3 tests), `test_end_session_skill.py`, and `test_end_session_pipeline.py` fixtures updated to seed post-commit concerns/debts so the count assertions are meaningful under the new semantics.
- 4784 tests, 1 skipped, 404 subtests passing.

## v3.1.30 — sprint-082 (probe-adoption recovery + house cleanup, 6 stories)

Sprint-082 closes execution-plan Milestone 1 — restores probe-adoption signal after 19 consecutive sessions of sub-50% adoption, plus 4 isolated cleanups designed for parallel teammate execution. **6/6 stories delivered, velocity 1.0.**

### story-001 (solo) — probe-adoption cluster: pool builder + AC#4 E2E + try_status audit

Three converging touchpoints around probe + retro wiring shipped together. **(a)** New `_matching_open_by_keyword` in `resolves_probe.py` adds keyword-overlap candidates to the pool builder, mirroring `_matching_open_discoveries`. The pool previously unioned only file-overlap matches (`open_matches + discovery_matches + sibling_matches`); `_score_candidate` already used keyword overlap for ranking but never sourced new candidates. Dedups via `matched_ids` so a candidate matching by both file AND keyword appears once with both reasons attached. Hoists `haystack_keywords` computation above pool building so the helper and per-candidate scoring share a single tokenization. Closes the SPIKE-named gap from sprint-081 story-004 (`resolves_probe.py:460-484`). **(b)** New `tests/integration/test_kickoff_adopt_commit_probe_e2e.py` pins debt `23c1a5d62d16`'s long-deferred AC#4: stale-snapshot probe correctly rereads disk after `work_selection_decide.adopt` touches the refresh sentinel. Test pins `now_ts == seed_ts` to isolate the sentinel branch from wall-clock staleness — mutation-verified by commenting out `signal_probe_refresh`. **(c)** Audit confirmed `annotate_try_status` id-as-token resolution path is intact (was always working); new test pins it so `tokens.add(own_id)` at `retro_history.py:103` can't regress silently into the next retro mystery.

### story-002 (teammate) — scaffold_cli.py extraction to scaffold_cli_apply.py

Pre-emptive split before next CLI-touching commit. `scaffold_cli.py` was at 499/500 lines after sprint-081; the 7 `_cmd_apply_*` callables (~120 lines, lines 167-288) plus their two helpers (`_load_snapshot_or_exit`, `_run_apply_phase`) and three CLI utilities (`_emit`, `_require_smm_dir`, `_load_stdin_json`) extracted to `scaffold_cli_apply.py`. `scaffold_cli.py` re-exports each name via shim so callers ("apply-*" dispatch table, tests, downstream stories) keep working with no change. Lands at 351 lines — comfortable margin, not a 499-line cliff. New `tests/scaffold/test_scaffold_cli_split.py` pins both halves: each module stays <500, and `scaffold_cli` still re-exports every `_cmd_apply_*` with `assertIs` identity (catches accidental local re-definition in <1s). Drive-by DRY consolidation: `_require_smm_dir` (3 inline copies → 1 helper), stdin-JSON parse pattern (3 try/except blocks → `_load_stdin_json` raising SystemExit(1)).

### story-003 (teammate) — marker_names centralization (7 dotfile constants across 6 scripts)

Closes debt `6d5683b0b36a`. Adds 5 flat constants (`LINT_WARNED`, `SPRINT_RETRO_INPUT`, `CURATION_INPUT`, `COORDINATION_JSON`, `COORDINATION_LOCK`) and 2 templates (`TEAMMATE_REPORT`, `STORY_ASSIGNMENT`) to `smm/marker_names.py`. Replaces inline literals at all 7 call sites across `lint_check.py`, `retrospective.py`, `worktree.py` (×2), `subagent_start.py`, `coordination.py` (×2), `session_end.py` — the last is a paired-lifecycle drift (clears `.lint-warned` set by `lint_check`; centralizing one half without the other defeats the centralization). Per-site audit preserved raw I/O vs `marker_consume` semantics. Drops two vestigial private aliases (`_COORDINATION_FILE`/`_LOCK`, `_CURATION_INPUT_FILENAME`) per simplify pass.

### story-004 (teammate) — large_batch_probe: checkpoint-nudge probe

Reframes the carry-forward checkpoint Try as **tooling, not discipline**. New `plugins/xp-agents/scripts/large_batch_probe.py` registered on `PostToolUse` (matcher `Write|Edit|MultiEdit|Bash|Skill|Agent`) emits a status nudge "consider committing intermediate green state" when main has emitted >40 events since the last main-agent commit. Filters by `agent_id == "main"` (teammate event flow doesn't trigger), `is_xp_agent` recursion guard for xp-* subagents, dedups within the batch window so rapid tool calls don't spam. Critical correctness fix from xp-code-reviewer: status events alone are functionally invisible (filtered by `prompt_nugget._NUGGET_PRIORITY`); the probe MUST return its text via `additionalContext` for the agent to actually see it. Status event remains the audit trail. Decision `dbace441bca6` captures this as project policy for future advisory probes.

### story-005 (solo) — convention-bundle-pattern decision capstone

Closes concern `073c8694f755`. Decision event `ddb1be281bc1` records the sister-test discovery design pattern: built-in convention bundle (curated likely-test paths) + `system_context.json` overrides for project-specific divergence. Future divergent designs (lint, format, CI conventions) landing a competing decision with the same topic will trip the superseded-decision detector and surface the choice for explicit reconciliation. Originally scoped with a pytest pin for the decision marker; **xp-code-reviewer caught the pin as a CLAUDE.md project-generic-IDs violation** (shipped tests must not reference project-local concern IDs); test deleted, decision event itself is the architectural artifact.

### story-006 (solo, after teammate hang) — xp-kickoff Step 2.4 → xp-stage-migration skill extraction

xp-kickoff/SKILL.md Step 2.4 (~430 tokens) was injected at every session kickoff for a step that fires at most once per project (one-time stage-2 migration prompt + dismissal). Extracted the migrate/continue/dismiss flow into new `xp-stage-migration` skill; kickoff carries only a 9-line conditional pointer (was 33). Net per-session win: ~430 tokens saved in kickoff body; ~80 tokens added via skill description (always loaded). Skill body itself loads on demand only when stage<2 + not dismissed. **Critical regression caught pre-merge:** the slimmed Step 2.4 lost the original `(ALWAYS, every kickoff)` override, which would have caused free-session users to skip Step 2.4 entirely (per Step 2's "jump directly to step 5" path); restored the override + added regression test `test_step_24_runs_regardless_of_session_mode`. Bash globs in xp-stage-migration tightened per-subcommand vs sibling pattern (least-privilege win). Final close-reviewer caught a Block: kickoff Step 2.4 invoked the skill via Skill tool but xp-kickoff allowed-tools doesn't include `Skill`; aligned both files to slash-command form (`/xp-stage-migration`, `/xp-sprint-start`) matching sibling dispatches.

### Notable in-sprint events

- **Teammate worktree-story-006 hung 31min** at 0.1% CPU with no progress — concern `e1a8f7e17d84`. Killed and switched story-006 to solo execution. Worth investigating spawn_teammate hang root cause (possibly waiting on AskUserQuestion in `-p` mode without stdin).
- **3 file_domain drifts within K=1 tolerance** (all infra-required, no scope creep): story-003 paired-lifecycle session_end edit; story-004 emitter fixture + injection budget entry; story-006 prose-pin test + skill budget entry.
- **5 plan-reviewer / close-reviewer concerns surfaced + addressed inline** during the sprint: probe pool dict-dispatch (story-001), test fixture noise (story-001 + 002), allowed-tools globs (story-006), Skill-tool dispatch Block (sprint-close).

### Test status

4778 tests, 1 skipped, 404 subtests passing throughout. Test count grew by ~20 (new tests for keyword pool, try_status pin, AC#4 E2E, scaffold split, marker_names, large_batch_probe, kickoff stage-floor + xp-stage-migration prose pins, skill budgets entry).

### Next

**Sprint-083 (Milestone 2)** remains planned: EVENT_CATEGORY enum refactor (collapses 3-entry tax across `event_schema.py` / `materialize.py` / `compact.py`) + `read_events_raw` audit (14 call sites; migrate watermark-semantics ones to `read_delta_full`). Both have high blast radius across SMM engine; deserve their own focused sprint.

## v3.1.29 — sprint-081 (scaffold-acceptance hardening: 3 real-world bug fixes + probe-quality SPIKE)

Sprint-081 closes execution-plan Milestone 1 — three independent fixes from the first real-world `/xp-scaffold-acceptance` invocation on 2026-05-04 (Expo mobile project; ~5 manual recovery prompts), plus a SPIKE adopted from this session's retro Try investigating 18 consecutive sessions of sub-50% probe adoption. **4/4 stories delivered**.

### story-001 — Bug 1: known_installs map + tool-identity verify probe

Curated `plugins/xp-agents/scripts/known_installs.json` (initial map: maestro, playwright, cypress, detox) overrides `WebSearch` for tools where the popular package name collides with an unrelated package (`brew install --cask maestro` lands `Maestro.app` GUI, not the mobile-dev-inc CLI). Map entries provide fully-qualified `install_cmds` + paired `verify_identity_cmd` / `expected_version_pattern`. SKILL.md Step 2 consults the map FIRST; map hits bind those fields verbatim into Step 4's `build-plan` input. WebSearch still always runs to refresh `tool_version` (entries omit it).

New apply phase `run_verify_identity` between `run_install` and `run_verify`: runs `verify_identity_cmd`, asserts `re.search(expected_version_pattern, stdout)`, raises `CalledProcessError` on mismatch so `apply_plan`'s revert engages. `validate_plan` rejects cmd-without-pattern pre-snapshot using a single-source `IDENTITY_PATTERN_REQUIRED_MSG` constant; defense-in-depth `raise ValueError` inside `run_verify_identity` for direct callers. Output mirrored to `verify-identity.log` for symmetric failure diagnostics. `render_preview` surfaces the identity probe in the customer's Step 5 confirmation.

`Phase = Literal["write", "install", "verify-identity", "verify"]` eliminates magic phase strings symmetrically across `scaffold_apply.py` and `scaffold_cli.py`. `known_installs.py` lives standalone (CLI entry for SKILL.md to call via Bash + importable function for tests) — keeps `scaffold_cli.py` at 499/500 and avoids coupling `scaffold_plan.py` to disk I/O.

### story-002 — Bug 2: scaffold branch base derivation from current non-protected branch

`create_scaffold_branch` previously always forked off primary, silently stranding user work that lived on a free / sprint / plan branch. Now reads `identity.get_current_branch(cwd)` + stage; non-protected → use as base, protected (main/master) → fall back to primary. `commit_scaffold` passes its already-cached `stage` and `current_branch` into `create_scaffold_branch` (optional kwargs), eliminating two duplicate subprocess + SMM lookups per scaffold run.

Drive-by extraction: `branching.py` at 499 lines + this story's edits crossed the 500-line budget. Pure-string naming helpers (`_slugify`, `branch_name`, sprint/plan/free/scaffold name builders, `_utc_today_iso`, `_SPRINT_BRANCH_RE`, `is_sprint_branch`) split into `branch_names.py` and re-exported from `branching.py` for back-compat. Mirrors the existing `branch_lifecycle.py` extraction pattern. Tests patching `branching._utc_today_iso` updated to `branch_names._utc_today_iso` (the patch source-module rules apply to the moved function).

### story-003 — Bug 3: drop HEAD subject prefix gate from apply-record

Manual-recovery commits with non-canonical subjects (conventional-commits, plain prose, custom prefix) failed the `[chore] Scaffold ` prefix check at `scaffold_post.py:247` and couldn't flip the surface. The SHA-match gate at lines 234–243 already binds record to the exact commit, so the prefix check was redundant safety with high false-positive cost in real-world recovery scenarios. Dropped lines 244–256 (assignment + gate); SHA-match gate preserved. `SCAFFOLD_COMMIT_PREFIX` still drives `build_commit_message` subject formatting for scaffold-generated commits — only the read gate is relaxed.

Drive-by: extended `tests/scaffold/_helpers.init_git_with_seed` with a `subject` kwarg + return-sha; collapsed the local `_seed_scaffold_commit` helper and the new test's 12-line commit-creation block into a single helper call.

### story-004 SPIKE — probe candidate-set quality

Investigation traced the 18-session probe-adoption regression to pool construction at `resolves_probe.py:460–484`: `open_issues_matching_commit` + `_matching_open_discoveries` are file-overlap-only; `sibling_matches` requires an active close-cycle. Keyword-only matches never enter the pool — `_score_candidate` already keyword-weighted, but it never sees them. Sprint-082 fix scoped at ~30 LOC + 2 tests: add `_matching_open_by_keyword` to the pool builder. Decision event `4d181aef4c31` records the trace and the fix direction.

### Token-audit M-4 closeout (decision)

Pre-existing risk `8e68053a96f0` ("M-4 preload audit incomplete") confirmed stale: sprint-077 v3.1.24 shipped the structural M-4, sprint-079 v3.1.25 self-corrected 3 helpers via existing budget tripwires. Five surface-scan tests (`preload`, `emitter`, `guide`, `agent`, `skill`) catch unbudgeted additions. Decision `ff14a38ab90d` documents the structurally-complete state.

### Test count

- Full suite: 4756 passed, 1 skipped, 377 subtests passed (was 4742 in v3.1.28)
- New tests: TestKnownInstalls (4), TestScaffoldPlanIdentityFields (2), TestRunVerifyIdentity (5), TestRenderPreviewIdentityProbe (2), test_scaffold_branch_forks_off_current_non_protected_branch, test_arbitrary_subject_succeeds_when_sha_matches (3 subTests)

## v3.1.28 — fix(draft_summary): persist refined session_summary, not mechanical scan

Free-mode bug fix surfaced at /xp-end-session validation. Step 1 has the agent author a refined past-tense `session_summary` event, but `write_history.py` (via `draft_summary._build_summary`) ignored that event and persisted the raw mechanical `[type] content` event-log dump instead. Effect: next kickoff's `### LAST_SESSION` block surfaced messy event-log lines (commit message bodies, `[status]`/`[concern]`/`[commit]` markers) rather than the refined narrative the agent had just written. The "Refine the CANDIDATES text into a 1-2 paragraph narrative" rule in SKILL.md Step 1 was effectively unenforced — the refined content existed in `events.jsonl` but never reached the layer the next session reads.

Intended design (per customer): `events.jsonl` and `session_history.json` both carry the SAME refined narrative. The mechanical synthesis only serves the `format_preload` CANDIDATES draft (raw material the agent reads BEFORE Step 1), never the persisted history layer.

`_build_summary` now fast-paths to the latest `session_summary` event content when one exists; synthesis remains as the fallback for the pre-Step-1 case.

End-to-end validation: simulated a session, ran the Step 4 pipe, confirmed the persisted `session_history.json` summary matches the agent-authored narrative verbatim — no `[type]` markers leak.

### Test contract correction

Integration test `test_two_layers_carry_distinct_payloads` explicitly enforced the OLD (incorrect) two-layer-distinct contract — rewritten as `test_history_carries_refined_summary_not_mechanical_scan`, plus a new `test_history_falls_back_to_mechanical_scan_when_no_summary` that guards the synthesis fallback (still load-bearing for the CANDIDATES preload).

### Refactors

`test_draft_summary.py` 775 → 833 lines with the two new tests, then split into `test_draft_summary_likely_addressed.py` (concern/debt → file_overlap → commit-hash audit-trail tests, 241 lines) and `test_draft_summary_carry_forward.py` (carry_forward surfacing tests, 166 lines). Original now 491 lines (under 500 target). Per project memory `feedback_proactive_file_splits`: split AT the commit that pushes the file over, not after.

### Test count

- Full suite: 4742 passed, 1 skipped (was 4739 in v3.1.27)
- New tests: trivial-summary-survives, latest-of-multiple-summaries, history-carries-refined-narrative, history-fallback-when-no-summary

## v3.1.27 — fix(_common): exclude session_summary from uncommitted_event_count

Free-mode bug fix surfaced at /xp-end-session. The honesty signal was structurally always >=1: Step 1 appends a session_summary event, Step 5 reports the count. Every session ended with the prompt "Consider committing before ending so the next session's probe has fresh data" even when there was no real outstanding work. The advice value of the signal collapsed to zero — the whole point is to flag forgotten user work, not to remind the user that /xp-end-session just did its job.

Filter SESSION_SUMMARY from `_common.uncommitted_event_count`. The count now points only at real outstanding work — events the user appended (decisions, concerns, status, etc.) that haven't been linked to a commit via a Resolves-Event trailer.

TDD red-first: 2 new tests in `test_draft_summary.py` cover the trivial trailing-summary case (commit + summary → 0) and the load-bearing realistic case (commit + decision + summary → 1, ensures the filter doesn't over-exclude and mask actual outstanding work).

### Test count

- Full suite: 4739 passed, 1 skipped (was 4737 in v3.1.26)

## v3.1.26 — sprint-080 (Milestone 3 docs refresh + sister-test SPIKE + probe sentinel cleanup)

Sprint-080 closes execution-plan Milestone 3 (top-level docs refresh against sprint-074..077 doctrine), redesigns the sprint-079 deferred sister-test validator as a project-generic SPIKE, and resolves a sprint-079 close-reviewer concern. **5/5 stories delivered**.

### Sister-test discovery SPIKE (story-001)

- **`docs/ideas/SISTER_TEST_DISCOVERY.md`** — design doc for project-generic sister-test discovery, replacing sprint-079 story-001's hardcoded Python+pytest validator. Covers four conventions (Python pytest, Go `_test.go`, JS/TS Jest, Rust Cargo) with marker-file detection, source→test mapping rules, and worked examples per language. Recommends a new top-level `test_layout` field in `system_context.json` with auto-discovery + customer override; honestly weighs the alternative of extending the existing `acceptance_surfaces` shape and concedes it as defensible. Specifies a pluggable `discover_sister_tests(source_path, layout, project_root)` validator API with a closed extractor registry, plus the wiring plan that routes `sprint_cli.py` mutating subcommands through `save_sprint.run()` (closing the dead-code defect that deferred sprint-079 story-001). Open-questions section captures three deferred decisions for the future implementation milestone.
- **AC4 self-assertion caveat** — the doc explicitly notes that "this doc is the only design source needed" is judged by the doc about itself; the implementation milestone should open with a doc-vs-reality pass and escalate if substantive gaps exceed three.

### Top-level docs refresh

- **`README.md`** — skills table dropped two agent-only rows misclassified as slash commands (`/xp-run-retrospective`, `/xp-housekeeping`); added `/xp-end-session`, `/xp-scaffold-acceptance`, `/xp-story-close`. New "Plugin Subagents (auto-invoked)" subsection lists all seven shipped subagents with their triggers. New "Token Budgets and Honesty Guards" subsection documents the byte-budget framework + 12-hex-ID grep guard with honest scope (plugin-shipped guides only; repo-level `docs/` is out of scope for design-window ID anchors). Hook table updated for `[release]`/`[chore]`/`[sprint-direct]` bypass prefixes, `.assign-pending` exemption, CLOSE_CYCLE_ACTIVE Stop block. Pillar caps now defer to `PROCESS_GUIDE.md §Pillars` (single source of truth).
- **`docs/ARCHITECTURE.md`** — hook map matches `hooks/hooks.json` row-for-row (added `close_cycle_stop_gate.py`; corrected `PostToolUse:Skill` → `Skill|Agent`; expanded SubagentStop with all four xp-* completion handlers). Re-attributed process-guide injection from SubagentStop to `PostToolUse:Skill|Agent` (`review_cycle_done.py`) — verified against the scripts before editing. New doctrine sections: Marker Write Locality, Sprint state vs sprint events, CLI teammates as sprint-default execution mode (with when-to-prefer-Agent-Teams contrast).
- **`docs/SMM_DESIGN.md`** — pillar caps now defer to `PROCESS_GUIDE.md §Pillars` (no inline numbers restated). New Mutable State Files (ring-buffer pattern) section documents `{version, entries[]}` atop `smm_store` atomic-write as the canonical shape for new mutable SMM state files (`session_history.py` named as the reference implementation). New Per-item content limits section points at `event_schema.CONTENT_BUDGETS` and `materialize._CUSTOMER_INPUT_TRUNCATE_LIMIT`. New SMM_DIR resolution section codifies `init.sh` + `CLAUDE_PLUGIN_DATA`. Closing principle: events.jsonl is transient; `system_context.json` owns stack config.
- **`docs/completed/CLI_TEAMMATE_DESIGN.md`** (sprint-direct) — documented `XP_TEAMMATE_FILTER_TIMEOUT` (default 600s, env override) per adopted retro Try `fc555090d81b`. Original draft prose claimed the filter "writes a hung-teammate report"; simplify caught the inaccuracy against the code (filter exits 1 with stderr diagnostic, no report on the timeout path) and the doc now matches.

### Probe sentinel cleanup (story-005)

- **`.probe-refresh` sentinel now consumed on first successful reload** (`scripts/resolves_probe.py`): closes sprint-079 close-reviewer concern `d7d2b2f7475d`. The sentinel file persisted indefinitely after first adopt, costing every probe call an extra `stat()`+ISO-parse and silently leaving probes marked stale if SMM_DIR was restored from backup with future-dated mtime. The cleanup fires after any successful `_common.load_events_with_resolutions` (covering both the staleness branch AND the cold-load `events=None` branch that production callers in `pre_tool_bash` and `pre_tool_skill` always take). Sentinel persists across reload failures so the next probe retries — silent cleanup would re-open the missing-event divert class sprint-079 closed.
- **Mid-review course-correction**: first cut gated the unlink on `if is_stale:` which narrowly satisfied the AC text but left the production path uncleaned. Reviewer caught it (concern `c130abd6d655`); the broader cleanup addresses the actual underlying defect. Honesty over clever-AC-reading.
- **`signal_probe_refresh` docstring rewritten** — old "self-clearing via fresher snapshots" wording was factually wrong post-cleanup. Now states the consume-on-success / persist-on-failure contract directly. Closes plan-review concern `14e0f07c6a4c`.

### Cross-story drift fixes (sprint-direct)

- README.md cross-story drift caught by sprint-close-reviewer: `PostToolUse` matcher updated `Skill` → `Skill|Agent` to match story-003's ARCHITECTURE refresh and trimmed to what `review_cycle_done.py` actually dispatches (housekeeper / `/xp-assign` nudge / security-review continuation — NOT sprint-review or close-reviewer routing). SubagentStop (Plan) row hedged with "fallback for Plan subagent flow when PostToolUse:Agent doesn't fire" so the two rows don't read as contradictory. "Two regression suites" → "Three" (off-by-one). 12-hex-ID grep guard scope claim narrowed to the actual test-coverage scope (plugins/xp-agents/ only, with explicit honest note that repo-level `docs/` is out of scope for design-window ID anchors).

### Refactors

- **4 duplicate `_seed_concern` test helpers consolidated** into a single `_ProbeTestHelpers` mixin in `tests/conftest.py` with optional `ts` arg. Two more no-ts variants (`TestFindProbeCandidates`, `TestFindProbeCandidatesDiscovery`) joined the mixin in the close-cycle fix; the two genuinely-distinct helpers (cycle_id metadata, custom default `ts`) stay in place.

### Test count

- Full suite: 4737 passed, 1 skipped (was 4734 in v3.1.25)
- New tests: TestSentinelCleanup (3 tests covering staleness-triggered reload, cold-load `events=None` production path, reload-raises persistence)

### New decisions

- `1b73873e5105` — SMM_DESIGN.md defers per-pillar cap numbers to PROCESS_GUIDE.md; aggregate item/token orientation cue stays in SMM_DESIGN as it has no PROCESS_GUIDE home
- `acae12b89b07` — Process-guide injection lives in `PostToolUse:Skill|Agent` (`review_cycle_done.py`), NOT SubagentStop — SubagentStop additionalContext is platform-dropped
- `280e6ece3c41` — Probe sentinel unlinked AFTER successful `load_events_with_resolutions` inside `find_probe_candidates`; persists across reload failures so signal isn't silently lost
- `3021cef2a074` — SPIKE design docs land in `docs/ideas/` until adopted; graduate to `docs/completed/` when the implementation milestone ships

## v3.1.25 — sprint-079 (signal ergonomics M-2 + adopted debts: probe sentinel freshness, always-run retro + seed fallback, prompt_nugget single locked read, branch_lifecycle extract)

Sprint-079 ships Milestone 2 (signal ergonomics) and folds in three sprint-077 adopted debts. **5/6 stories delivered**; story-001 deferred for project-generic redesign.

### Reliability + signal-quality fixes

- **Probe snapshot freshness** (`resolves_probe.py`): new sentinel-file mechanism (`marker_names.PROBE_REFRESH`) closes the fast-commit gap where the existing 5s wall-clock staleness threshold misses adopt+commit pairs landing within the window. `signal_probe_refresh()` is touched by writers (xp-work-selection's adopt path); the probe re-reads disk when sentinel mtime postdates the snapshot's `max_ts`. Targets the 100% `missing-event` divert class observed in sprint-078.
- **Always-run session retro** (xp-kickoff Step 1, xp-retrospective agent): made retro invocation unconditional. The `### RETRO_NEEDED` preload marker was easy to skim past, so retros got silently skipped on fresh projects. The agent now handles missing/sparse `.retro-input.json` (<5 events) by emitting a seed retro — Keep items framed around adopting XP, Try items framed as `try running <skill>`, zero Fix items. Supersedes the v3.1.24 action-hint band-aid.
- **prompt_nugget single locked read** (`scripts/prompt_nugget.py`, `smm/read_delta.py`): collapsed the read_delta + load_events_with_resolutions double-read into a single locked call via the new `read_delta.read_delta_full(smm_dir, agent_id) -> tuple[list[dict], list[dict]]`. Resolution chains stay complete across the watermark; full read happens under shared flock. `read_events_from(start_line=0)` short-circuits the offset-walk for the new hot-path caller.

### Refactors

- **`branch_lifecycle.py` extracted** from `branching.py`: `_is_merged_into`, `_fast_forward_if_safe`, `_merge_into_target`, `merge_branch`, `delete_branch`. branching.py 585 → 499 lines (back under the 500-line per-file target). Re-exports preserve every existing caller. Wisdom `ab40b12643ab` honored: shim-import smoke test landed first.
- **3 .py preload helpers trimmed** (sprint-077 cleanup): `render_history.py` 69→61, `triage_preload.py` 109→96, `format_preload.py` 45→43 — all under per-file budgets. New `tests/skills/test_format_preload.py` pins the 4-section stdout shape.

### Close-cycle hygiene fixes

- `question_answered.py`: replaced inline `read_text + unlink` with `markers.marker_consume(smm_dir, markers.QUESTION_GATE)` — symlink-safe, kills duplicate-literal anti-pattern.
- Sentinel filename moved into the canonical `marker_names.py` constants module + renamed `.probe_refresh` → `.probe-refresh` (kebab-case per convention).
- xp-retrospective agent: harmonized Seed branch trigger across opener + Guidelines (missing OR <5 events).

### Deferred

- **story-001** (sister-test auto-inclusion in save_sprint validator): implementation baked in xp-agents-repo conventions (`xp-` skill prefix strip, `tests/test_<x>.py` layout, `scripts/` dir). Branch + commits intact for next sprint; needs redesign with `system_context.json`-driven project-generic source→test mapping so the validator works for any plugin user, not only this repo.

### Test count

- Full suite: 4734 passed, 1 skipped (was 4701 in v3.1.24)
- New tests: TestProbeRefreshSentinel + TestAdoptSignalsProbeRefresh, TestRetrospectiveSeedPath, TestSingleLockedReadPath + TestPostWatermarkAppendPickedUpNextCall + TestResolutionChainCompleteness, TestBranchLifecycleShimImports + 5 behavioral classes in test_branch_lifecycle, test_format_preload contract suite

### New decisions

- `bcb882d63c85` — probe-refresh-sentinel-mechanism (sentinel-file mtime over events-table reread)
- `dcbc4a8f9764` — read_delta_full canonical helper for locked-read+watermark-advance hot-path consumers
- `371fb41cd334` — kickoff Step 1 unconditional gating
- `4b323bbe66d4` — probe-sentinel persistence is the freshness signal across multiple probe calls (no cleanup)
- `1a64e9ff2165` — skill→scripts coupling permitted when signaling a hook (probe_refresh case)
- `7ace060b9dc9` — sister-test overlap policy: validator stays loose, xp-assign overlap-check is the safety net (story-001 dep, but recorded for the eventual redesign)

## v3.1.24 — sprint-077 (token audit M-4: trim 14 preloads + check_session_needs + 3 top-level guides + close-pipeline shared md, ~9.1KB per-fire savings)

Sprint-077 closes Milestone 4 of the token-audit plan and folds in 5 sprint-076 retro/concern/debt fix-stories. **Per-fire savings on shipped surfaces: ~9,094 bytes (~2,200 tokens).** 11/11 stories done.

### Runtime byte savings (per-fire)

| Surface | Pre | Post | Saved | % |
|---|---:|---:|---:|---:|
| `_close_pipeline_shared.md` (cat'd by 4 close skills) | 9201 | 5777 | **-3424B** | -37% |
| `check_session_needs.sh` (every kickoff) | 4123 | 2723 | **-1400B** | -33% |
| `TEAMMATE_GUIDE.md` (every teammate session) | 3694 | 2991 | -703B | -19% |
| `xp-quality-review/preload.sh` | 2503 | 1887 | -616B | -24% |
| `xp-review-plan/preload.sh` | 1639 | 1080 | -559B | -34% |
| `XP_VALUES.md` (every SubagentStart) | 1545 | 1033 | -512B | -33% |
| `xp-accept/preload.sh` | 2476 | 2050 | -426B | -17% |
| `PROCESS_GUIDE.md` | 5745 | 5331 | -414B | -7% |
| `xp-sprint-start/preload.sh` | 1231 | 826 | -405B | -32% |
| `xp-sprint-review/preload.sh` | 966 | 658 | -308B | -31% |
| `xp-assign/preload.sh` | 908 | 690 | -218B | -24% |
| `xp-plan/preload.sh` | 794 | 685 | -109B | -13% |

XP_VALUES + check_session_needs are the highest-leverage cuts (every session/subagent fire).

### New test infrastructure

- `tests/hooks/test_preload_budgets.py` — 3 methods covering 15 preloads (subprocess byte-budget + surface-scan)
- `tests/test_guide_budgets.py` — 3 methods covering top-level guides (line-budget + 12-hex-ID grep)
- `tests/hooks/test_no_historical_ids_in_emitters.py` — sister to skill/agent ID guards (caught 4 real leaked IDs in shipped scripts)
- `tests/hooks/test_close_cycle_stop_gate.py` — regression for severity-bump fix
- Surface-scan validation now in BOTH `test_injection_budgets.py` (15 emitters) and `test_preload_budgets.py` (15 preloads) — catches new emitter/preload shipping unbudgeted

### Fix-stories

- **story-008** (closes c589e66f9a22): emitter scripts/ surface-scan + 4 LIVE unbudgeted emitters discovered (`pre_tool_skill`, `post_tool_exit_plan`, `kickoff_gate`, `bash_post_tool`) — fixtures + budgets added
- **story-009** (closes 6fc8450069c6): CLOSE_CYCLE_ACTIVE bypass severity bump (medium→high) + recovery nudge to both concern content and stderr — surfaces in xp-end-session high-severity watch
- **story-010** (closes 22b746e75653): teammate worktree exemption from `.assign-pending` gate — `pre_tool_write` now uses `identity.is_worktree_teammate()` to skip the marker check for teammates (sprint-076 soft-loss class fixed)
- **story-011** (closes 59e14037d671): 12-hex ID grep guard for emitters — caught 4 real leaked decision/concern IDs in shipped scripts and scrubbed them

### Bug fix landing in close cycle

- `_run_emitter` / `_run_preload` were popping `SMM_DIR` AFTER setting it (loop included it in `_LEAKY_GIT_ENV`), so all 30 budget measurements ran against the dev's live SMM not the seeded one. Caught by sprint-close-reviewer; fixed inline (pop first, set after). Test premise now matches its docstring.

### Honesty calls

- Story-002's first attempt only registered budgets without trimming — deferred and re-spawned with sharper prompt; v2 delivered the 37% trim on the dominant cost driver.
- Two teammates (003, 008) hung post-result event; killed and finished manually. Root cause filed as debt: `teammate_output_filter.py` reads all stdin into list before processing, blocks indefinitely if `claude -p` stalls before EOF.

## v3.1.23 — sprint-076 (token audit M-3: trim 11 hook-injection emitters, -8.4% lines; per-script byte-budget regression test)

Sprint-076 shipped 6/6 stories delivering Milestone 3 of the token-audit plan. The 11 hook-injection emitter scripts (`prompt_nugget`, `user_prompt_log`, `session_start`, `subagent_start`, `subagent_stop`, `pre_tool_write`, `pre_tool_bash`, `lint_check`, `review_cycle_done`, `retrospective`, `session_end_warning`) trim from 2748 → 2516 source lines (-232, -8.4%); a new `tests/hooks/test_injection_budgets.py` enforces per-script byte budgets at `ceil(measured * 1.125 / 100) * 100` (floor 100). The capstone shipped twice — the first version was caught as test-theatre by the sprint close-reviewer (silent-by-short-circuit, not silent-by-trim, because `_run_emitter` set `SMM_DIR` to a non-existent path and 9/11 emitters short-circuited at `get_validated_smm_dir`). The fix bootstraps a real seeded SMM via `seed_smm.py` directly + a git-repo cwd, recalibrates budgets to honest measurements, and amortizes one bootstrap across all 11 emitters per assert call. 4679 tests pass (+2 new).

### Runtime byte savings (per-fire, on prose-heavy nudges)

| Emitter | Pre-trim B | Post-trim B | Δ |
|---|---:|---:|---|
| `subagent_stop` plan-reviewer nudge | 280 | 156 | **-124B (-44%)** |
| `retrospective` preload | 607 | 514 | **-93B (-15%)** |
| `session_end_warning` | 157 | 135 | **-22B (-14%)** |

### Honest framing on the budget test

The capstone test is an **empty-SMM baseline regression guard**, not a load measurement. With seeded-but-empty SMM and a git-repo cwd:
- `subagent_start` (4096 B), `session_start` (1793 B): always-on XP_VALUES.md framing
- `subagent_stop` (248 B), `lint_check` (235 B), `review_cycle_done` (110 B), `session_end_warning` (81 B): always-emit nudges
- `prompt_nugget`, `retrospective` (0 B): no signals to nugget on empty SMM
- `pre_tool_write`, `pre_tool_bash` (0 B): sprint-state-gated, silent without sprint
- `user_prompt_log` (0 B): returns None by design

The test catches: growth in always-on framing; new unconditional output sneaking into a previously-silent emitter; regression past per-script budgets on the four always-emit nudges. The test does NOT catch: growth in dynamic per-event content (rendered SMM, file paths, signal counts) — those scale with SMM size and are validated by the per-script unit tests in `tests/hooks/`.

### Behavioral changes (verified safe)

- `pre_tool_write.check_tdd_order` dropped its `tool_name` parameter — three layers of redundancy collapsed (`_WRITE_TOOLS` frozenset + `if tool_name not in _WRITE_TOOLS` branch were dead given `hooks.json` matcher pins `Write|Edit|MultiEdit` and `_common.extract_file_path` already gates the `run()` path). 7 test sites updated; the dead-branch test removed.
- `retrospective.run()` return type changed from `str | None` to `tuple[str, int] | None` — eliminates a regex-round-trip-our-own-prose anti-pattern at the CLI; drops `import re` from the SessionStart hot path. Verified safe: only production caller is the same-file `__main__`.
- Dead `(?:events|stories)` regex branch removed in `retrospective.py` CLI — its former producer (`sprint_retro_detection.py`) is gone.

### Process notes

- The sprint close-reviewer caught the test-theatre on the cumulative diff after the per-story close-reviewers had already passed it (twice). Per-story reviewers see the test framework cohere internally; cross-cutting reviewer caught it lying about what it tests. Confirms the value of the dual-review pipeline.
- Story-005 dropped two `test_retrospective.py` lines (signature update for the tuple return) and story-003 dropped 22 lines from `test_pre_tool_write.py` (signature update for the dead-branch removal). Both were file_domain drift within K=1 tolerance and necessary collateral of the production refactor.
- Investigation deliverable: discovery `66385dde8b25` quantified the teammate-commit-event gap that triggered debt `55039b905824`. Actual post-May-1 miss rate is ~6%, not the implied ~100% the original concern suggested. The historical ~62% comes from April when the bash_post_tool wiring wasn't reliably active. 97084b28 (the smoking gun) was misattributed: its merge is `9a5fe47b`, not `83ddb486`. Concrete leads filed for next sprint.

### Open follow-up debts (deferred to next sprint)

- `59e14037d671`: 12-hex-ID grep guard for emitter scripts (parity with skill/agent shipped-md guards)
- `c589e66f9a22`: Capstone AC1 enforces fixture↔budget cross-check but doesn't scan `scripts/` directory; a new emitter could be silently unbudgeted
- `04d6e605509e`: branching.py at 585 lines — extract `branch_lifecycle.py`
- `ac06c0a67f34`: New event types pay 3-entry tax across 3 modules; refactor with EVENT_CATEGORY enum

### Next milestone

M-4: Preload.sh audit + budgets (14 preload.sh files). Final milestone of the token-audit plan.

---

## v3.1.22 — sprint-075 (token audit M-2: trim 7 agent .md, -13%; SessionStart marker sweep; teammate-commit-event bug filed)

Sprint-075 shipped 5/7 stories delivering Milestone 2 of the token-audit plan (4/4 milestone stories at 1.0 velocity; 2 ad-hoc carry-forward Try items deferred). The 7 agent prompts that fire on every commit/close/plan/kickoff trim from 1248 → 1083 lines (-13%); a new capstone test enforces per-agent line budgets at `round(trimmed * 1.125 / 10) * 10` and a 12-hex-ID grep prevents historical references from creeping back in. The shared budget+ID test scaffolding consolidates into three `conftest.py` helpers (`assert_md_budgets_match`, `assert_md_under_budgets`, `assert_no_12hex_ids_in_md`) used by both the new agent tests and the existing skill tests. A new "trim-restoration criteria" constraint codifies the lesson surfaced across stories 001 and 002: trim work must preserve concrete calibration anchors (char counts, before/after numerics) alongside the negative-directive principle from sprint-074. Story-005 ad-hoc landed a SessionStart sweep that clears stale `CLOSE_CYCLE_ACTIVE` and `.accept` markers — but the sweep is gated to fresh-start sources only after close-reviewer caught the original implementation would silently wipe load-bearing markers on `/compact` or `/resume`. 4678 tests pass (+6 new).

### Token savings

| Story | Files | Lines saved | % |
|---|---|---|---|
| story-001 | 3 high-freq reviewers: `xp-code-reviewer` (84→83), `xp-close-reviewer` (137→127), `xp-plan-reviewer` (187→157) | -41 | 10% |
| story-002 | 2 kickoff agents: `xp-housekeeper` (229→192), `xp-retrospective` (246→219) | -64 | 14% |
| story-003 | 2 bulk-review agents: `xp-sprint-reviewer` (81→73), `xp-system-analyzer` (284→233, biggest agent) | -60 | 17% |
| story-004 | capstone: `tests/agents/test_agent_budgets.py` + `test_no_historical_ids_in_agents.py`; refactored shared helpers into conftest | locks the gains | — |
| **Total** | **7 trimmed + helpers consolidated + capstone tests** | **-165** | **-13%** |

### Sprint-075 / stories 001-003: agent .md trims (parallel teammates)

Stories 1-3 dispatched as parallel CLI worktree teammates with non-overlapping `file_domain`. Each independent close-reviewer cycle caught real over-trims that fix-cycle commits restored:

- `xp-close-reviewer.md`: example bullet was self-referential `[event_id: <hex-id>]`; replaced with literal placeholder `xxxxxxxxxxxx` (non-hex so the new 12-hex regex stays green) — commit `86581069` resolves `d41a664e26bb`, refined to `xxxx` form in commit `d917389c` to dodge the regex.
- `xp-housekeeper.md` + `xp-retrospective.md`: restored two calibration anchors lost in trim — the 116-char bad-paraphrase example next to the good 38-char TDD example, and the ~360 vs ~860 char Fix-bullet calibration. Commit `89cbd40f` resolves `cac2afcad308, 37676ae36b09`.
- `xp-system-analyzer.md`: restored the `add-decision` example dropped from Step 5; first attempt used wrong field schema (`content` vs file's documented `topic`/`decision`/`rationale`), caught by simplify code-quality agent against the file's own JSON template at line 178. Commit `43aa6a5b` resolves `dcd9601e8752`.

### Sprint-075 / story-004: capstone enforcement + helper consolidation (commit `d917389c`)

- **`tests/agents/test_agent_budgets.py`** — `AGENT_BUDGETS` dict caps each of the 7 agent .md files at `round(trimmed * 1.125 / 10) * 10` (close=140, code=90, housekeeper=220, plan=180, retro=250, sprint=80, system-analyzer=260). Two test methods mirror the proven SKILL.md pattern.
- **`tests/agents/test_no_historical_ids_in_agents.py`** — same `\b[0-9a-f]{12}\b` regex from the SKILL.md sister test.
- **`tests/conftest.py`** — extracted `assert_md_budgets_match`, `assert_md_under_budgets`, and `assert_no_12hex_ids_in_md` helpers. `tests/skills/test_skill_budgets.py` and `test_no_historical_ids_in_skills.py` refactored to call the helpers (eliminates pre-existing duplication per refactor-before-adding wisdom). Reuse-agent recommendation surfaced exactly when the second mirror appeared.
- New decision `shipped-md-prose-guards`: each shipped .md directory pairs a budget dict + 12-hex-ID grep, both built on shared conftest helpers. Future M-3 hook-injection audit should mirror this shape.

### Sprint-075 / story-005: SessionStart marker sweep (commits `ffb165eb` + `ea0b720d`)

Two stuck-marker classes seen across recent sprints — `CLOSE_CYCLE_ACTIVE` leaks when a close-skill aborts before the reviewer fork; `.accept` leaks after teammate-worktree close-cycle Edits — generalized into `markers.sweep_stale_session_markers(smm_dir)` reusing the existing `marker_consume` primitive. Initial implementation ran the sweep on every SessionStart source, which xp-close-reviewer caught as a Block: `resume`/`compact` are mid-session continuations where these markers may be load-bearing (e.g. `/compact` mid-close-skill would wipe `CLOSE_CYCLE_ACTIVE` and defeat the resumed conversation's stop gate). Fix-cycle gated the sweep on `_is_fresh_start(source)` — only `startup`/`clear` sweep; `resume`/`compact` preserve. Resolves `5b8e455efbdd, 2b3a4413b5b0, f3196e38ac33, d874e1210e92, 4d565bf753b5, e69e29188af0, 74e88928ccad`.

### Stories deferred (carry-forward Try items)

- **story-006** (heredoc apostrophe-safety): adopted Try item turned out to be already shipped — commit `97084b28` from sprint-074's session resolved the underlying concern `f30412be6059` before this kickoff's retro analyzed the data. Decision `story-006-already-fixed` records the no-op.
- **story-007** (probe-ranking adoption): adopted Try item references decision `1a3b807c8e85` which was compacted out of `events.jsonl`. Investigation of `find_probe_candidates` and `build_nudge_lines` showed both already do what the Try summary describes (rank by score+ts, emit content prefix). Decision `probe-ranking-already-implemented` records the no-op.

### Honesty signal: teammate-worktree commit events missing from events.jsonl

Diagnosing the story-006 false positive surfaced a real bug in the resolution pipeline: commit `97084b28` carried `Resolves-Event: f30412be6059` trailer but never produced a `commit` event in `events.jsonl` — only the orchestrator's subsequent merge commit was recorded. The `PostToolUse:Bash` hook that scrapes `Resolves-Event:` trailers and records the event apparently doesn't fire for individual teammate-worktree commits. Effect: teammate-commit resolves trailers silently lost; concerns stay "open" forever in subsequent kickoff preloads and retro Fix lists. Same root family as the marker-leak class (hook didn't fire / state didn't propagate). Filed concern `a43fc9577867` (severity high) + investigation debt `55039b905824` queued for next sprint with a 5-step playbook: empirical reproduction, instrumentation, root-cause fix, historical backfill, retrospective contradiction-detection.

### New constraints

- `shipped-md-prose-guards` — pair budget dict + 12-hex grep for every shipped .md directory; share helpers via conftest.
- `trim-restoration-criteria` — broaden the negative-directives restoration principle from sprint-074 to cover quantitative calibration anchors (char counts, before/after numerics).
- `marker-sweep-gating` — `sweep_stale_session_markers` is gated at the call site (not inside the helper) on `_is_fresh_start(source)`; resume/compact preserve in-flight markers.

### Bottom line

7 agent .md → 1083 lines (1442 → 1083 raw, **-25%** by `wc -l`; 1248 → 1083 by milestone count, **-13%**). Capstone tests prevent regrowth. SessionStart sweep clears two classes of stuck markers (gated correctly after reviewer Block). Conftest helper consolidation eliminates pre-existing duplication. Real bug filed against teammate-worktree commit-event recording — investigation queued.

## v3.1.21 — sprint-074 (token audit M-1: trim 16 SKILL.md files, ~8636 tokens, ~25%)

Sprint-074 shipped 4/4 stories (1.0 velocity) delivering Milestone 1 of the new 3-milestone token-usage audit plan. 12 of the 16 shipped SKILL.md files were trimmed (4 were already at the ~700-token floor); 2 new pytest-enforced tests now lock the gains so re-growth fails commits. The trim discipline applies six lenses: paragraph-length "why X" rationale prose, historical story/sprint/12-hex IDs in shipped guidance, non-actionable cross-references, dead-branch logic for preload-prevented states, defensive prose restating bash semantics, and repetition of `PROCESS_GUIDE.md` / `CLAUDE.md` content. Every functional step, bash invocation, conditional on a real runtime state, and error handler is preserved verbatim. 4672 tests pass (+3 new). M-2 (Agents audit) and M-3 (Hook-injection audit) remain planned for future sprints.

### Token savings

| Story | Files | Tokens saved | % |
|---|---|---|---|
| story-001 | 4 biggest logic-heavy: `xp-scaffold-acceptance` (422→401, -35%), `xp-story-close` (342→240, -37%), `xp-accept` (312→267, -37%), `xp-sprint-start` (225→200, -22%) | -5,801 | 34% |
| story-002 | 5 medium: `xp-assign` (213→178), `xp-plan` (202→186), `xp-work-selection` (176→170), `xp-kickoff` (169→158, -30% tokens), `xp-free-close` (169→126) | -1,910 | 17% |
| story-003 | 3 smaller: `xp-sprint-close` (149→116), `xp-plan-close` (137→125), `xp-end-session` (127→114). `xp-quality-review` (94) and `xp-system-context` (24) deliberately left at baseline — already at the token floor | -925 | 16% |
| story-004 | capstone: 2 tiny skills (`xp-sprint-review`, `xp-review-plan`) verified already minimal; new enforcement tests committed | locks the gains | — |
| **Total** | **12 trimmed + 4 at floor + 2 new tests** | **~8,636** | **~25%** |

### Sprint-074 / story-001-003: SKILL.md trims (parallel teammates)

Stories 1-3 ran as parallel CLI worktree teammates (non-overlapping `file_domain`, no inter-story deps); each merged to the sprint branch via `/xp-story-close`'s auto-merge gate after independent close-reviewer cycles. Five reviewer concerns were caught and fixed in-cycle (decision recorded `skill-trim-restoration-pattern`: when a trim removes a NEGATIVE directive — "Do NOT X", "never Y" — restore it explicitly; surrounding flow does not encode negative imperatives reliably):

- `xp-end-session/SKILL.md` Step 3: restored `git show <hash>` operational hint (commit `cb2578e8`, resolves `559cc9ba5804`).
- `xp-kickoff/SKILL.md` Step 2.4: restored "Do NOT record a dismissal" on the migrate branch (commit `9136d381`, resolves `bcc7648a2801`).
- `xp-plan/SKILL.md` Step 1: restored "sources are inputs / plan must stand on its own" guidance (same commit, resolves `200aa34f704a`).
- `xp-scaffold-acceptance/SKILL.md` Step 2: aligned `assess-tool` heredoc example with the apostrophe-safety advisory below (`--tool '<tool>'` → `--tool="<tool>"`) (commit `97084b28`, resolves `f30412be6059`).

### Sprint-074 / story-004: capstone enforcement tests (commit `ed25199a`)

- **`tests/skills/test_skill_budgets.py`** — `SKILL_BUDGETS` dict caps each of the 16 SKILL.md files at `round(trimmed_lines * 1.125 / 10) * 10`, giving ~10-15% headroom before failure. Two test methods: `test_every_skill_has_budget_entry` (drift check — new skills can't sneak in unbudgeted) and `test_no_skill_exceeds_its_budget` (regression check). Mirrors `tests/smm/test_append_schema.py:TestContentBudgets`.
- **`tests/skills/test_no_historical_ids_in_skills.py`** — regex scan for 12-hex SMM event IDs (`\b[0-9a-f]{12}\b`) in shipped SKILL.md prose. `story-NNN`/`sprint-NNN` deliberately excluded (pedagogical placeholders in JSON template examples), mirroring the same exclusion in `tests/integration/test_no_project_local_ids.py`.
- New decision `skill-md-budgets`: SKILL.md per-file budgets enforced by `tests/skills/test_skill_budgets.py` (`SKILL_BUDGETS` dict). Adding a new skill requires computing and adding the budget entry; re-trim if over budget; bump deliberately if not.
- New decision `skill-budget-test-shape`: budget tests use the two-method form (drift + regression) — same pattern recommended for M-2 (agents) and M-3 (hook injections).

### Sprint-074 close-reviewer: cross-skill alignment (commit `9a807d0d`)

The sprint-mode close-reviewer caught two consistency drifts that emerged because stories 1-3 trimmed independently:

- **Close-skill intros** had three variants of "Use these values verbatim" (full sentence, short, dropped). Settled on dropped uniformly across all four close skills — the variable list itself is the imperative.
- **Step 7 merge-chain prose** had three fidelity levels for the same shared `close_common.py` contract. Settled on uniform "Any failing step aborts the chain — source intact for retry. Conflicts are never auto-resolved." `xp-plan-close` keeps its archive-specific note ("plan stays unarchived").

### Notes for future sessions

- Stuck `.accept` marker concern recorded (`8b5b0b80a59c`): the post-close fix-cycle Edit on a teammate worktree re-armed `.accept`, and `/xp-accept`'s preload skip-when-no-reviewing-stories path didn't consume it — blocking `update-story <id> done`. Workaround: `rm .accept` manually. The suppression check in `pre_tool_write` may need to extend to teammate-worktree paths during `closing` state.
- M-2 priority: trim agent .md files starting with the always-on reviewers (`xp-code-reviewer`, `xp-close-reviewer`) since they fire on every commit/close. Same three-phase rhythm (trim → measure → budget at trimmed*1.125).
- M-3 introduces measure-by-execution: subprocess fixtures rather than `wc -l`, since hook injection payloads vary by input.



Sprint-073 shipped 2/2 stories (1.0 velocity) plus a post-sprint free-session bug fix discovered during `/xp-end-session`. Headline: `CLOSE_CYCLE_ACTIVE` marker arming moves from LLM-prose in `_close_pipeline_shared.md` to deterministic preload writes via the existing `_preload_base.sh:write_marker` helper — the prose path was unreliable when the LLM skipped/reordered the invocation or invoked `/security-review` standalone. Plus YAGNI removal of `xp-story-close`'s dead conditional Step 4 security-review branch (no codepath produces a story-without-sprint), 3-tier→2-tier collapse of `SECURITY_REVIEW_DOCTRINE.md`, and a bug fix where the `/xp-end-session` LIKELY_ADDRESSED probe emitted SMM commit-event ids labeled as "commit IDs" (not git refs — `git show` correctly rejected them). 4669 tests pass (was 4680; -2 from removing dead conditional tests, +2 new regression tests, net of 4 fixture updates).

### Sprint-073 / story-001: YAGNI removal of conditional Step 4 in xp-story-close (commit `9f593bc6` + fix-cycle `477cb10b`, `7f069756`)

- **`xp-story-close/SKILL.md`** — deleted entire `## Step 4: Conditional Security Review` section (40 lines). The branch defended a hypothetical the codebase doesn't support: kickoff binds session mode at Step 2; `/xp-accept` only fires inside an active sprint; `xp-assign` only creates story branches in sprint mode. Step 3 now flows directly to Step 4.5; added a `**Step 4 (Security Review) does not apply to story-close.**` bold-inline note explaining why the `4.5` numbering is preserved (cross-skill ordering pin in `test_plugin_integrity.py::TestCloseSkillStepOrdering`).
- **`tests/integration/test_xp_story_close_security_gap.py`** — entire 261-line file deleted (3 test classes, 13 tests defending the removed conditional).
- **`tests/_close_fixtures.py`** — `_Step4SecurityIncludeTests` mixin docstring updated to drop story-close from the applicable-skills list.
- **`tests/hooks/test_plugin_integrity.py`** — dropped story from `_CLOSE_SKILL_MDS` dict; updated docstrings (4→3 close skills); added bidirectional cross-ref paragraph to `TestCloseSkillStepOrdering` naming the SKILL.md citation site so future renamers update both ends.
- **`docs/SECURITY_REVIEW_DOCTRINE.md`** — collapsed 3-tier model to 2-tier (old Tier 2 was the removed conditional). Renumbered old Tier 3 → Tier 2. Fixed pre-existing Step 4.5→Step 4 numbering drift (M-2 sprint-063 reordered Security to Step 4 but the doctrine still said 4.5). Updated principle, findings recording, trade-offs, "How Skills Use This Doctrine", and implementation references end-to-end.
- **`scripts/_close_pipeline_shared.md`** — dropped story-close from Step 4 scoping line + close-mode enum (reviewer-flagged drift fix; story-close's preload cat's this file, would have shown LLM "Step 4 fires from story-close itself" pointing at deleted prose).
- Mid-sprint scope spillover recorded as decision `6cb7a32fe8f3` per constraint `4f64e8fb4584`; story-001 file_domain updated to match actual edits. Two close-reviewer concerns (`fb1174349972` stale docstring, `fd7c81b2fd71` Step 4.5 numbering note) fixed in the fix-cycle commit.

### Sprint-073 / story-002: hook-driven CLOSE_CYCLE_ACTIVE marker write (commit `88e44c8a` + cluster-cleanup `ae995e32`)

- **`xp-{free,sprint,plan}-close/scripts/preload.sh`** — each preload now calls `write_marker CLOSE_CYCLE_ACTIVE ""` (uses the existing `_preload_base.sh:write_marker` helper) after the `CLOSE_CYCLE_ID` echo and before `emit_hook_guidance`. xp-story-close preload unchanged — story-close never runs Step 4 (sprint-close covers it).
- **`scripts/_close_pipeline_shared.md`** — deleted the prose `python3 markers.py write CLOSE_CYCLE_ACTIVE` block from Step 4 (Security Review). Replaced with a 5-line note pointing at the preload scripts as the canonical write location.
- **`tests/integration/test_close_preloads_emit_shared.py`** — rewrote `test_emits_step4_close_cycle_active_marker_write` to assert (a) preload source contains `write_marker CLOSE_CYCLE_ACTIVE` BEFORE the `cat _close_pipeline_shared.md` line, (b) marker file lands on disk after preload runs (idempotency: `write_marker` → `marker_write` → `write_text_atomic` → `os.rename`). Added inverse-pin override on `TestStoryClosePreloadEmitsShared` (story-close NEVER arms the marker — both halves pinned: source absence + disk absence). Imports `markers` module to compute `marker_path()` durably.
- **Cluster cleanup** (`ae995e32`) — dropped dead `Bash(python3 */scripts/markers.py *)` grants from all 4 close-skill SKILL.md frontmatters (no shipped close skill invokes markers.py CLI directly anymore — preloads use `write_marker` which spawns `python3 -c`, not the CLI). Deleted 2 stale tests in `test_plugin_integrity.py` that defended the prose-driven write contract; replaced 67-line block with 3-line breadcrumb pointing at the new behavioral pin. Rewrote `test_close_cycle.py` module docstring + 2 inline comments — production write path now correctly attributed to the preload helper; `markers.py` CLI is exercised here only as a fixture / argparse + allowlist regression catcher.
- New decision `marker-write-locality`: lifecycle markers driving Stop hooks MUST be written by preload scripts via `_preload_base.sh:write_marker`, not LLM prose.

### LIKELY_ADDRESSED commit-hash fix (commit `e22c41d9`)

- **`skills/xp-end-session/scripts/draft_summary.py`** — `commits[]` now carries `metadata.commit_hash` (resolvable by `git show`) via `event_schema.METADATA_KEY_COMMIT_HASH` constant, not the SMM commit-event id (the prior bug: `git show <smm-event-id>` correctly rejected as not a git ref). **Filter-at-source** (don't fall back to event id): if a commit event lacks `commit_hash`, skip it; if no overlapping commit has one, skip the whole concern from `likely_addressed`. Empty list is honest; wrong refs are not.
- **`SKILL.md`** prose updated to "git commit hash(es)" with `git show` guidance (was "commit ID(s)" / "Read events.jsonl by id" semantics). `format_preload.py` variable rename `commit_id` → `commit_hash`. Module docstring example schema + agent-fetch guidance updated to git-hash contract.
- **Test coverage** — 2 new tests in `test_draft_summary.py` (canonical-path pin + filter-behavior pin); 5 existing fixtures across 3 files updated to set `metadata.commit_hash` so they exercise the canonical path, not just the fallback. `COMMIT_HASH` class constant added to `test_end_session_pipeline.py` alongside `COMMIT_ID`; LLM-simulation step now writes the git hash in `resolved_by_commits`, not the SMM event id. Closes concern `3fbfdbe49bb4` (HIGH, Honesty — fallback re-introduced same bug class). Producer-side gap (`commit_hash` not schema-required) tracked as `e4dd53de7376` for next-session triage.

## v3.1.19 — free session: 4 retro Trys + 4 concerns/debts shipped in 8 commits

Free session executing the four adopted retro Trys from sprint-072 plus four reviewer-flagged concerns/debts that landed alongside. Headline: `/xp-end-session` Step 3 now auto-judges LIKELY ADDRESSED concerns instead of asking the user (mirrors `/xp-story-close` Step 5b). Plus drift-signal restoration, per-invocation env-var reads, schema-doc derivation, close-cycle bypass instrumentation, probe-divert NO_CANDIDATES bucket, and TDD-red metric tagging. 4680 tests pass (was 4669; +11 net). Solo mode throughout. One concern (`c7600936cd55` security stop-gate) dropped as already-addressed by the existing `CLOSE_CYCLE_ACTIVE` marker — the discovery-by-checking saved a redundant implementation.

### Drift signal restoration (commit `2c32700b`)

- **`smm/sprint_cli.py:_cmd_validate_domain`** — moved `XP_FILE_DOMAIN_DRIFT_TOLERANCE` env-var read from module-import time into the function so per-sprint or per-story overrides can slot in without reshaping callers (closes concern `047c2769a5a2`). Added `drift (within K=N): N file(s): <files>` stderr emission when `1<=len(drift)<=tolerance` so retros and quality-review can see what slipped past the K-budget instead of silent absorption (closes `04fee892ac2c`). Stdout reports `absorbed:` rather than `clean:` when drift was absorbed — honest signal for callers parsing stdout.
- **`xp-story-close/SKILL.md` Step 1b** — capture stderr and record `file_domain_drift` concern in BOTH over-budget (rc!=0) AND within-K (rc==0 with stderr matching `^drift`) cases. Producer-without-consumer gap caught by `xp-quality-review` reviewer mid-cycle.

### `/xp-end-session` LIKELY ADDRESSED auto-judge (commits `dd47fca4` Phase A + `e5c09dcd` Phase B)

- **Step 3 rewrite** — replaces `AskUserQuestion` "Drop these N items?" with per-item agent judgement. Auto-resolves when commit message wording matches the concern's stated problem AND the concern's `files` are the obvious target AND no remaining work is implied; defers when uncertain (no event, re-surfaces next kickoff). Reports a one-line summary instead of prompting (closes concern `2668d4b09cfd`).
- **Audit trail** — new `METADATA_KEY_RESOLVED_BY_COMMITS` constant (Phase A standalone schema commit) populated on the `end_session_drop` status event alongside the canonical `metadata.resolves` STRONG link. Retro tooling can distinguish bulk end-session drops from organic resolutions and trace which commit(s) informed each auto-judge.
- **`draft_summary.likely_addressed` shape change** — `list[str]` → `list[{id, commits: [str]}]` carrying only IDs (no truncated content). Agent fetches concern + commit content from conversation history (solo) or via Read on events.jsonl (teammate-authored commits). Keeps the preload minimal — the agent's judgement is the contract, not a pre-rendered string.
- **`format_preload.py`** renders `- <concern_id>` at top-level with overlapping commit IDs indented beneath.
- **New `STATUS_ACTION_END_SESSION_DROP` constant** — added to event_schema's status-action vocabulary alongside the existing review-cycle and tool-action sets. `_LLM_PRODUCERS` set lifted out of `_DOCTRINE_GAPS` in the action-vocab canary per the existing TODO ("when 2nd LLM-producer constant lands, lift to `_LLM_PRODUCERS`") — keeps `_DOCTRINE_GAPS` single-purpose (debt IDs only).
- **Test coverage** — pipeline integration test now asserts new preload format + `resolved_by_commits` metadata round-trip; new deferral re-surface test (`test_pipeline_deferred_concern_resurfaces_in_next_draft`) calls `draft_summary.run()` twice and asserts the deferred concern re-surfaces, proving the contract holds across session boundaries (reviewer reframe of the original "skip step 5 = no-op" assertion).

### `architecture_overview` budget bump 600 → 750 (commit `c26e1878`)

- User-requested headroom for larger repos: 600 was tight on plugins with 5+ persistent state files. `system_context_schema.FIELD_MAXLENGTH["architecture_overview"]` bumped + matching update to `xp-system-analyzer` agent prompt's Step 4 JSON template ("max 750 chars").
- **`TestSystemAnalyzerPromptMaxlengthSync` test class** added — pins both `architecture_overview` and `product` budgets to `FIELD_MAXLENGTH` constants. A future schema bump that forgets the markdown (or vice versa) now fails loudly. Reviewer-flagged drift risk closed.

### Schema budget derivation + enum drift fix (commit `dc87c6d4`)

- **`smm/schema.json` content description** — replaced hand-maintained per-type budget enumeration (`status=200, decision=400, ...`) with `"see CONTENT_BUDGETS in smm/event_schema.py for current values"`. The schema is a doc artifact (no Python loads it for validation); the truth is `event_schema.validate_event` reading `CONTENT_BUDGETS`. Closes debt `dd336aa81092`.
- **Enum drift fix (reviewer-caught while in the file)** — `schema.json` `type.enum` was missing `session_summary` (added to `VALID_TYPES` and `CONTENT_BUDGETS` but never to the enum). The hand-enumerated `test_schema_has_16_types` was complicit. Replaced with `test_schema_type_enum_matches_valid_types` that auto-syncs to `VALID_TYPES` — drift class eliminated.
- **`scripts/_common.py` event-type constants** — replaced literal strings (`COMMIT = "commit"`, etc.) with delegations (`COMMIT = _es.EVENT_TYPE_COMMIT`). Comment claiming "mirrors smm/schema.json enum" was a lie (same missing `session_summary`); now the source of truth is `event_schema.py` and the unprefixed aliases stay for caller ergonomics. Closes concern `7853b810062a`.

### Close-cycle bypass instrumentation (commit `3b91bbf3`)

- User reported a real failure: agent ended mid-`/security-review` with `CLOSE_CYCLE_ACTIVE` marker still set. Root cause: `close_cycle_stop_gate.py` deferred on `stop_hook_active=True` (Claude Code's loop-prevention flag), letting the agent escape the gate by ignoring one block. Implementation contradicted the docstring's intent ("Review-cycle/teammates deferrals are intentionally NOT applied").
- **Picked option #2 of three**: keep the defer (avoid infinite loop if the agent literally cannot follow the directive) BUT record a concern + emit stderr on every bypass while the marker is set. We will see how often it happens.
- **Restructured `run()`** to resolve `smm_dir` + check the marker BEFORE the `stop_hook_active` branch, so both branches share the marker check. On bypass: stderr-first (minimum reliable signal), then a medium-severity concern with `metadata.kind = CONCERN_KIND_CLOSE_CYCLE_BYPASS` (new vocabulary constant). Uses `identity.resolve_agent_id` for correct teammate attribution (reviewer-caught real bug); dropped redundant try/except since `_common.append_safe` already swallows `LockTimeoutError` and logs to `hook_errors.jsonl`.
- Concern `c7600936cd55` (filed as "add `SECURITY_REVIEW_ACTIVE` Stop-gate marker") was dropped earlier in the session as already-addressed — the existing `CLOSE_CYCLE_ACTIVE` mechanism does what the concern asked for. This commit closes the silent-escape gap that the original mechanism missed.

### Probe-divert `DIVERT_REASON_NO_CANDIDATES` bucket (commit `e0198426`)

- Sprint-072 retro flagged 9 consecutive sub-50% probe-adoption periods where every observed divert had empty candidates but bucketed under per-event reasons (`NEWER_THAN_SNAPSHOT`, `PROBE_SELECTION_MISS`), hiding the candidate-gen gap. Closes concern `c727ba5bab99`.
- **`DIVERT_REASON_NO_CANDIDATES` constant** in event_schema.py alongside the other 6 DIVERT_REASON_* values. Probe-level signal (the candidate set itself was empty), not event-level miss.
- **Short-circuit at the call site** in `retro_metrics._compute_probe_adoption` — when `candidate_ids` is empty, bucket as `NO_CANDIDATES` BEFORE invoking `_classify_divert_reason` (which is event-level by contract). Reviewer-flagged dead computation moved into the else branch.
- **Decision recorded** with topic `divert-reason-classifier-layering` documenting the probe-level vs event-level separation so the superseded-decision detector flags any future drift.

### TDD-red metric tagging (commit `b6552e46`)

- `consecutive_test_failures` conflated red TDD steps with regressions. Sprint-072 retro flagged 5 consecutive failures as a Fix item — all of them legitimate RED steps where the agent had committed failing tests and was iterating to make them pass. Closes concern `d4262732af65`.
- **Producer (`bash_post_tool`)**: when the most recent commit event in `events.jsonl` had only test-layer files (per `is_test_file` — covers `test_*.py`, `tests/`, `conftest.py`, etc.), tag the next `test_run_complete` event with `metadata.tdd_red=True`. Conservative: a single non-test file in the prior commit kills the tag (default to "treat failures as regressions" when in doubt). Empty file lists / no prior commit → no tag.
- **Consumer (`work_signals`)**: in the `consecutive_failures` counter, skip events where `metadata.tdd_red=True`. Same treatment as `parser_status=parser_failed` — the run carries no regression signal, don't increment, don't reset.
- **`METADATA_KEY_TDD_RED` constant** in event_schema.py centralizes the spelling; producer, consumer, and `_event_fixtures.tests_run_status`'s new `metadata_extra` param all reference it.

### Reviewer-flagged secondary fixes folded in mid-cycle

- `/xp-end-session` Step 3 honesty: stdout no longer claims "clean" when drift was absorbed (`2c32700b`).
- `xp-story-close` SKILL.md producer-without-consumer gap on within-K drift signal (`2c32700b`).
- `_emit_stderr` helper extraction skipped: would create inconsistency with 5+ existing `print(..., file=sys.stderr)` callsites in the same file.
- Stop-gate constant `STATUS_ACTION_END_SESSION_DROP` placed in correct grouping (with other `STATUS_ACTION_*`) per reviewer mid-flight refactor (`e5c09dcd`).
- Producer-guard removal in `draft_summary.py` (trust `validate_event` upstream guarantee, fail-loud doctrine) — reviewer-flagged.
- Schema constant comment block tightened to honest "5 persistent state files" count after reviewer probed the "SMM quartet" claim (`c26e1878`).

## v3.1.18 — sprint-072: /xp-end-session kickoff render (M-3, 6/6 velocity) + drift K=1 default + retro-Try follow-throughs

Sprint-072 ships milestone M-3 of the `/xp-end-session` execution plan — kickoff preload now surfaces the most recent session_history entries as a `### LAST_SESSION` block — closing out the three-milestone arc (M-1 skill scaffold sprint-070; M-2 persistent layer sprint-071; M-3 consumption sprint-072). Plus three retro-Try follow-throughs converted into ad-hoc stories: probe-snapshot fix verification, file_domain drift-tolerance K=1 default with env override, and a 6-test-failure cluster investigation that unmasked a metric misclassification (red TDD steps counted as regressions). 6 planned / 6 delivered, 4669 tests pass (was 4664; +5 net). Solo mode throughout — mixed story sizes (3 small/investigation, 3 implementation) made teammate fan-out coordination cost not worth the wall-time savings.

### Kickoff render (story-001 + story-002)

- **`skills/xp-kickoff/scripts/render_history.py`** — pure-stdlib script that reads `session_history.json` via `session_history.load_history`, prints `### LAST_SESSION` block with the last 1–2 entries (`summary` + `carry_forward` `note`/`recommendation`). Event ids in `references` are NEVER rendered — the docstring states intent rather than enumerating exception classes (close-reviewer fix). Fail-quiet: catches `ValueError`/`OSError` and returns `""` so the kickoff preload never breaks on a malformed history file. `_RENDER_LIMIT = 2` and `_SECTION_HEADER = "### LAST_SESSION"` extracted as module constants.
- **`check_session_needs.sh` insertion** — calls `render_history.py` between the system-context check and the execution-plan check. Subprocess gated on `[ -f "${SMM_DIR}/session_history.json" ]` so first-session and abandoned-history kickoffs don't pay the Python cold-start cost (close-reviewer-recommended hot-path optimization, ~50–100ms saved). Decision recorded with stable topic `preload-cold-start-gating` so any future preload renderer follows the same pattern.
- **`make_session_history_entry` test fixture** extracted to `tests/_event_fixtures.py` mirroring the `make_event` pattern, re-exported through `conftest.py` (per /simplify finding — shared between unit and integration tests).
- **Drift-guard sync** — `skills/xp-kickoff/scripts` added to both `pyrightconfig.json` files (root + plugin-local) atomically; the integration test caught the missing entry on first commit.

### PROCESS_GUIDE entry (story-003)

- **`PROCESS_GUIDE.md` "Session close" entry** under "When to Run XP Skills" so the agent recommends `/xp-end-session` organically when wrapping up. Initial terse one-liner ("populates next kickoff") was flagged by close-reviewer as failing AC-1 (which required naming the artifacts: `session_summary` event + `session_history.json` + user-invoked nature). Customer-confirmed resolution: bump `test_process_guide_token_budget` from 1000→1100 tokens and expand the entry to satisfy AC verbatim. The expanded entry implicitly addresses prior partial-address concerns about the bare SMM state-file enumeration on PROCESS_GUIDE.md:48 — `session_history.json` now has a lifecycle anchor earlier in the doc.
- **"Commit gate blocks if skipped" phrase restored** after a budget-trim attempt was flagged by close-reviewer as load-bearing (referenced in README, TEAMMATE_GUIDE, security doctrine docs).

### Probe-snapshot verification (story-004, code-free)

- Verified the probe-snapshot fix from retro-adopted Try `bfb21bb80604` shipped via two commits: `c0479a18` (telemetry — `METADATA_KEY_PROBE_SNAPSHOT_MAX_TS` + `TAIL_TS` recorded at `resolves_probe.py:369-371`) and `0bf92479` (`snapshot_max_ts` pinned BEFORE staleness re-read at `resolves_probe.py:360-362`). Sprint-071 retro confirms newer-than-snapshot diverts dropped from 3 (sprint-067) to 1 (sprint-071).
- Empty-candidate diverts traced to filter at `resolves_probe.py:382-405`: when a commit has no file-matching concerns/debts AND no in-sprint-batch siblings AND all candidates score 0, the list is genuinely empty — but the divert classifier flags this as `probe-selection-miss`. Recorded a follow-up concern recommending a separate `DIVERT_REASON_NO_CANDIDATES` bucket so retros can distinguish "filter excluded everything" from "agent picked wrong candidate".

### Drift-slot tolerance (story-005)

- **`smm/sprint_cli.py:FILE_DOMAIN_DRIFT_TOLERANCE`** — module-level constant `int(os.getenv("XP_FILE_DOMAIN_DRIFT_TOLERANCE", "1"))` permits K out-of-domain files per story before `validate-domain` flags drift. K=1 default reflects that shared fixtures, drift-guard configs, and other plumbing files often live outside a story's owned-code file_domain — penalizing the common case generated noise across sprints 067–071. Single-source-of-truth audit (Step 0 of plan) confirmed only `sprint_cli._cmd_validate_domain` computes drift; no parallel logic to keep in sync.
- **Reframed for plugin-genericness** — the original retro Try named project-local fixture files (`_common.py`, `_bases.py`); customer flagged that as constraint `f7920cf86da0` violation. Final shape is a generic K-file budget with no hardcoded names baked into shipped code.
- **`run_cli` gains `extra_env` parameter** mirroring `_bases._run_preload`'s established pattern. `conftest.py` strips `XP_FILE_DOMAIN_DRIFT_TOLERANCE` from test subprocess env (close-reviewer catch — same class of leak as `GIT_DIR`/`SMM_DIR`/`XP_TEAMMATE_NAME`).
- **Tests cover K=0 strict / K=1 default within tolerance / K=1 over budget + AC4 e2e (two-story sprint, same diff seen through two file_domains)**. Existing strict-mode tests pin `XP_FILE_DOMAIN_DRIFT_TOLERANCE=0` via the new helper.
- **`xp-story-close/SKILL.md` Step 1b updated** to describe the tolerance behavior + env override (close-reviewer doc-drift catch).

### Test-cluster investigation (story-006, code-free)

- Investigated the 6-test-failure cluster flagged in sprint-070 + sprint-071 retros. Locus: `scripts/work_signals.py:87-106` — the `consecutive_test_failures` counter increments on any `test_run_complete` event with `test_passed=false`, regardless of whether the failure was a deliberate red TDD step (test written first, not yet implemented) or a genuine regression. Sprint-071 events confirm the cluster came from teammates' TDD cycles, not regressions; not an end-session pipe-boundary issue. No smoke fixture added per plan.
- Recorded a follow-up concern recommending `test_run_complete` events be tagged with `metadata.tdd_red=true` when the prior commit was a test-file-only commit, so the counter can distinguish red TDD from regressions.

### Customer decisions captured

- **K=1 default vs K=0 default** — plan-reviewer pushed back recommending K=0 (preserve strict alarm); customer confirmed K=1 default to immediately loosen the noise across all sprints, accepting the global signal-loosening tradeoff. Decision `b942fad28c3d` resolves the blocking question.
- **PROCESS_GUIDE token budget bump** — customer chose budget bump over further entry-trimming when the close-reviewer's AC-1 + load-bearing-phrase concerns coupled together to push over 1000 tokens. Bump to 1100 satisfied both axes.

### Honesty notes for next retro

- Two commits skipped the `/xp-quality-review` cycle pre-commit (story-003 docstring fix, story-005 AC4 fix); QR ran retroactively each time but the cycle should land before the commit, not after.
- One Block fix landed directly on the sprint branch without the `[sprint-direct]` prefix the gate documents — this changelog entry uses the correct `[release]` prefix.

## v3.1.17 — sprint-071: /xp-end-session persistent layer (M-2, 5/5 velocity) + branch cleanup hardening

Sprint-071 ships milestone M-2 of the `/xp-end-session` execution plan: a persistent `session_history.json` ring-buffer (last 5 session summaries) with `carry_forward` items that auto-prune via `resolution.compute_resolutions` STRONG/WEAK cascade when their referenced events resolve. Plus an ad-hoc story-005 hardening `branching.delete_branch` against the worktree-teammate orphan-branch failure mode that left 4 dead refs from sprint-070. 5 planned / 5 delivered, 4654 tests pass (was 4619; +35 net). 3-way teammate fan-out for stories 001/002/005 (disjoint file domains), then solo for stories 003 + 004 (chained deps). Per-story close-reviewer caught 11 concerns inline; cumulative sprint-close caught 3 more (2 fixed inline, 1 deferred to debt for next sprint).

### Storage module (story-001)

- **`smm/session_history.py`** — pure-stdlib module mirroring `smm_store.py` / `system_context_store.py`: `load_history` returns `empty_history()` when missing (`{version: 1, entries: []}`), `save_history` validates + atomic-writes via `_append_impl.write_text_atomic`, both reject symlinks at the target path. `append_entry(smm_dir, entry, *, max_entries=5)` evicts oldest beyond cap. `prune_resolved(smm_dir, resolutions)` walks each entry's `carry_forward` and drops items where every `references` id appears in `resolution.collect_all_resolved_ids` — saves only when at least one item dropped (no-op writes avoided).
- **Schema inline** — `validate_session_history(data)` lives in the same module, not a sibling `*_schema.py`. Schema is `{version, entries: [{ts, summary, carry_forward[]}]}` with the `references` shape pinned (the field `prune_resolved` reads); `note`/`recommendation` left loose for forward compat per inline comment. Plan reviewer concern `389b77dc1df7` flagged premature split — resolved by inlining.

### Producer (story-002)

- **`draft_summary.run()` gains `carry_forward`** — list of `{note, references, recommendation}` items. Open questions get `recommendation="triage"` (next session decides); open high-severity concerns NOT in `likely_addressed` get `recommendation="watch"` (visible until resolved/downgraded). Notes route through `_common.truncate(content, 100)` so persisted ring-buffer entries stay compact (full content recoverable via `references`). Five existing return keys (`summary`, `open_questions`, `likely_addressed`, `uncommitted_count`) preserved.
- **Recommendation differentiation decided in close-review** — initial implementation hardcoded `"triage"`; reviewer flagged the design context anticipated `"watch"` for high-severity concerns. User confirmed differentiation; now lets future kickoff UIs route the two carry_forward classes without re-deriving severity.
- **Tests extended in-place** in `test_draft_summary.py` rather than a parallel `test_end_session_draft_summary.py` (resolves plan reviewer concern `52b32723587b` about duplicate test files for one module).

### CLI + skill wiring (story-003)

- **`skills/xp-end-session/scripts/write_history.py`** — thin CLI reads draft JSON from stdin (the dict shape produced by `draft_summary.run()`), builds a `{ts, summary, carry_forward}` entry, calls `session_history.append_entry` then `prune_resolved` against current `events.jsonl` resolutions. Uses `_common.load_events_with_resolutions` helper rather than re-implementing the parse+compute pair. **Fail-loud on missing required draft keys** (KeyError raised, not silent default-fill — defaults would mask a producer regression). `main()` wraps `run()` in try/except for `(KeyError, ValueError, OSError)` printing one-line `write_history failed: <msg>` to stderr instead of letting raw tracebacks escape (sprint-close-reviewer fix).
- **SKILL.md gains Step 4** — pipes `draft_summary.py | write_history.py` after Step 1's append, documents N=5 retention + the schema. Renumbers the existing "Honesty signal" Step 4 → Step 5; intro updated "four steps" → "five steps". Step ordering rationale corrected after first close-reviewer pass: "AFTER Step 1" exists so Step 1's session_summary event is in events.jsonl when Step 4's mechanical scan runs — not because the persisted summary matches the agent narrative (the two layers are intentionally distinct).
- **Two-layer design decision** — `session_summary` event (Step 1, agent-refined narrative) and `session_history.json` entry (Step 4, mechanical scan) are decoupled by design. `draft_summary._SUMMARY_TYPES` deliberately excludes `session_summary` so summaries never recurse on prior summaries.

### Capstone (story-004)

- **`tests/integration/test_session_history_pipeline.py`** — renders M-2's done-state into a two-session pytest. Session 1 seeds open Q + open high-severity concern → pipe → asserts 1 history entry with carry_forward refs to both. Session 2 appends answer + status with `metadata.resolves` → pipe again → asserts 2 entries AND session-1's carry_forward got pruned (cascade across the prior-session boundary). Plus 7-invocation eviction (= 5 chronological), corrupt-file rejection, symlink-rejection through the pipe (integration-level coverage of `save_history`'s symlink guard, not just unit), and two-layer payload distinction (separate sentinel markers prove the layers carry different data).
- **AC-5 reconciliation in test docstring** — sprint.json AC-5 said "session_summary events AND session_history.json both reflect the same canonical narrative without divergence" but story-003's two-layer design intentionally diverges. Test docstring honestly names the gap and points readers at the story-003 decision.
- **No-traceback contract pinned** — corrupt + symlink tests now `assertNotIn("Traceback", r.stderr)` and `assertIn("write_history failed", r.stderr)` to defend the clean-stderr behavior against future regressions.

### Branch-cleanup hardening (story-005, ad-hoc)

- **`branching.delete_branch` -D fallback** — adds optional `merge_target` kwarg. When `git branch -d` refuses (worktree-teammate case: local tip differs from upstream tracking ref even when fully merged to integration target), falls back to `git branch -D` ONLY when `git merge-base --is-ancestor <branch> <merge_target>` proves the merge. Backward compatible: legacy callers without `merge_target` see the unchanged False-on-refusal contract. `close_common.cmd_merge` passes `merge_target=args.target` so the close pipeline benefits across story/sprint/plan/free-close. Resolves the kickoff-detected concern `0552b1919480` that surfaced 4 orphan branches from sprint-070.
- **`_is_merged_into` helper** — extracted from the inline ancestry check in `_fast_forward_if_safe` (rule-of-three honored).
- **`_branching_fixtures.diverge_tracking_ref`** — shared test helper that reproduces the worktree-teammate diverged-ref state via `git update-ref refs/remotes/origin/<branch>` to an older commit + `--set-upstream-to`. Triggers git's "merged-into-upstream" check that refuses `-d` even when HEAD contains the no-ff merge.
- **Live impact next sprint** — sprint-071 itself ran on the cached v3.1.16 plugin (pre-fix), so its own merges still hit the orphan failure and required manual `git branch -D`; v3.1.17 closes the loop for sprint-072 onward.

### Real bug fixes (close-reviewer cycle)

- **AC5 coverage half-implemented** (story-002 close) — E2E subprocess test added `"carry_forward"` to the expected key set but kept the old single-question event seed; never asserted populated `carry_forward` over the wire. Fix: extended seed to include resolved concern + open high-severity concern + commit; asserted exactly 2 expected refs.
- **draft_summary defensive defaults** (story-003 close) — `draft.get("summary", "")` masked producer regressions. Replaced with explicit `_REQUIRED_DRAFT_KEYS` check that raises `KeyError` listing missing keys.
- **SKILL.md ordering rationale** (story-003 close) — claimed "summary text in the event matches the entry on disk" — false. Rewrote to explain the actual reason (Step 1's event must be in events.jsonl when Step 4's scan runs) and the intentional content distinction.
- **Existing test pinned 4 steps** (story-003 close) — `test_skill_md_has_four_documented_steps_in_order` failed after Step 4 added (renumbered to 5). Updated regex + assertion to expect 5.
- **PROCESS_GUIDE.md missed new artifact** (sprint close) — `session_history.json` wasn't in the SMM_DIR file list. Added bare filename within the 1000-token budget cap; richer consumer-side docs deferred to M-3 (kickoff preload story) when the file gains a reader.

### Deferred (carry forward to next sprint)

- **`branching.py` over 500-line target** (debt `04d6e605509e`) — file was 567 lines on main pre-sprint; story-005 added 18 → 585. Extract `branch_lifecycle.py` covering `delete_branch` + `merge_branch` + `_is_merged_into` + `_fast_forward_if_safe` in a near-term sprint. Deferred at sprint-close to avoid high-risk refactor at the wire — the cascade across many call sites needs proper TDD scope.

## v3.1.16 — sprint-070: /xp-end-session foundation (M-1, 4/4 velocity)

Sprint-070 ships milestone M-1 of the `/xp-end-session` execution plan: a user-invoked skill that drafts a narrative session summary, force-closes/defers open questions, bulk-drops likely-addressed concerns/debts, and prints an honesty-signal count of SMM events not yet linked to a commit. 4 planned / 4 delivered, 4619 tests pass (was 4589; +30 net). Per-story review caught 11 close-reviewer concerns inline; the cumulative sprint-close review caught a missing `Bash(python3 */smm/smm_cli.py *)` allowed-tools glob that per-story coverage missed — the kind of cross-cutting gap the sprint-level safety net is for.

### Schema (story-001)

- **`EVENT_TYPE_SESSION_SUMMARY` (budget=2000)** — new event type registered in 4 sister allowlists: `event_schema.VALID_TYPES` + `CONTENT_BUDGETS` + `_VALIDATE_NO_TYPE_RULES`, `materialize._BUCKET_INTENTIONALLY_ABSENT` (housekeeper sibling, not a curated pillar), `compact._COMPACT_INTENTIONALLY_ABSENT` (M2's `session_history.json` will own persistent retention), and `schema.json` content description. The 3-allowlist tax for new event types is now recorded as debt (`ac06c0a67f34`) for a future `EVENT_CATEGORY` enum refactor.
- **Helper extraction** (rule-of-three honored) — `_TempRepoTestCase._read_events` / `_clear_events` / `_events_file` consolidated from `test_append.py` + `test_session_summary_event.py` (+ `test_append_safety.py` migrated in the close-reviewer fix cycle).

### Helper (story-002)

- **`skills/xp-end-session/scripts/draft_summary.py`** — pure-stdlib CLI emits JSON `{summary, open_questions, likely_addressed, uncommitted_count}`. Reads events.jsonl from the prior `session_end` boundary forward; tail-preserving truncate (drops OLDEST lines on overflow with `...\n` prefix) so the LLM sees the most recent activity, not the oldest. `_NO_BOUNDARY_TAIL_CAP=200` fallback for backfill / corruption-recovery / first-session paths.
- **Sister-helper extractions** — `resolution.collect_all_resolved_ids()` consolidates the `*_ids` suffix scan that had landed in 3 call sites (draft + triage_preload + concern_triage); `_common.prior_session_end_ts()` and `_common.uncommitted_event_count()` join `current_session_start_index` as third + fourth members of the boundary-scan family.

### Skill scaffold (story-003)

- **`SKILL.md`** — 4-step body (draft → append → AskUserQuestion-driven question close + concern bulk-drop → honesty signal). Friction-free per design (no confirm prompt before Step 1). Uses `smm_cli.py question close --won-fix --event-id <id> --rationale ...` for the question-drop branch (canonical helper, idempotent for already-resolved questions); status events with `metadata.action=end_session_drop` for concern bulk-drops so retro tooling distinguishes them from organic resolutions.
- **`preload.sh` + `format_preload.py`** — sourcing `_preload_base.sh`, delegates to a sibling `format_preload.py` that does an in-process import of `draft_summary` (matches the `xp-quality-review` / `xp-work-selection` / `xp-accept` / `xp-sprint-review` precedent of separate `.py` from `preload.sh`; rejected an earlier python heredoc that had no precedent).

### Capstone (story-004)

- **`tests/integration/test_end_session_pipeline.py`** — renders milestone M-1's done-state into an executable pytest. Seeds tmp SMM with realistic events, runs preload subprocess, simulates the LLM by direct subprocess invocation of the 4 CLI calls SKILL.md instructs (session_summary append + answer event + smm_cli question close + end_session_drop status), then re-parses events.jsonl + asserts `compute_resolutions` surfaces both questions in `answered_question_ids` and the concern in `resolved_concern_ids`. Mutation-pass verified: temporarily zeroing `draft_summary.open_questions` filter fired red on both tests; reverted.
- **`_IntegrationTestCase._run_smm_cli`** — third call site for `python3 smm_cli.py` subprocess wrapping joined `_run_append` on the integration base.

### Real bug fixes (close-reviewer cycle)

- **No-boundary cap missing** (story-002 close) — long backfilled log + first session would funnel every historical event through summary truncate and discard recent signal. Fix: `_NO_BOUNDARY_TAIL_CAP=200` fallback when `prior_session_end_ts` is empty; tail-preserving truncate.
- **`smm_cli.py question close` flag form** (story-003 → story-004 close) — earlier SKILL.md draft used `question close <id> --won-fix` positional form; the CLI requires `--event-id <id>` flag form. Capstone test correctly followed the CLI; SKILL.md was the wrong source. Fixed.
- **Allowed-tools glob missing** (sprint close) — Step 2 won-fix branch invokes `python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py ...` but `allowed-tools` only declared `Bash(*/append.sh *)` / `Bash(*/skills/*/scripts/*)` / `Bash(*/init.sh)` — the LLM would have hit a permission prompt mid-skill. Added `Bash(python3 */smm/smm_cli.py *)` (matches `xp-kickoff/SKILL.md` precedent).

## v3.1.15 — free-session: probe instrumentation + 8 cleanup items

Free session bundling 9 user-adopted items from sprint-069 retrospective: 4 retro Trys, 1 debt, and 4 concerns including a real solo-mode bug. 8 implementation commits, all TDD with full review cycle (`/simplify` + `/xp-quality-review`) per commit. 4589 tests pass (was 4561; +28 net). Free-close added security review + cross-cutting close-reviewer pass — both clean before merge.

### Probe signal-quality (Trys #3 + #4)

- **Snapshot/tail-ts telemetry** — `find_probe_candidates` gains an opt-in `out_meta` kwarg (only `pre_tool_bash` opts in initially); captures `probe_snapshot_max_ts` (caller's snapshot newest ts, pinned BEFORE the staleness reread) and `probe_tail_ts` (newest ts after the check). When they differ, the probe re-read disk between caller-snapshot and probe-time. `emit_probe_status` now writes even on zero candidates when `probe_meta` is provided — the zero-candidate emit is the most diagnostic case for `newer-than-snapshot` diverts (33% of recent diverts). Refactored `_is_events_snapshot_stale` to return `(is_stale, max_ts)` so callers don't iterate events twice; extracted `_events_max_ts` helper.
- **Candidate widening for in-batch close-mode siblings** — adds 6th scoring axis: when `in_sprint_batch == 1 AND close_mode == 1 AND file_overlap == 0`, score +1 and emit `SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP`. Targets the `outside-file-domain` divert observed at 33% of recent diverts (close-mode multi-resolves where a legitimate sibling fell off the top-5 cap because `file_overlap=0` starved its score). Vocabulary cap test bumped 5→6 with the deliberate-review checklist followed.

### Code consolidation (Try #1 + #2 + debt)

- **`UNDER_ACCEPTANCE_STORY_STATUSES` extraction** — `pre_tool_write.py` and `sprint_stop_gate.py` both hand-wired the "reviewing OR closing" check (inverted vs direct). New frozenset constant + `has_under_acceptance_stories(_data)` helpers in the `sprint_schema`/`sprint_status`/`sprint_store` triad, mirroring the existing `IN_MOTION` pattern. Both call sites collapse to one predicate. Strictly better at the hot paths: one iteration with set-membership check vs the prior code's two `any()` calls in worst case.
- **`IN_MOTION_STORY_STATUSES` docstring drift fix** — claimed it drives the orphan-branch active-set, but `list_orphan_story_branches` actually reads `ACTIVE_STORY_STATUSES`. Docstring corrected to redirect readers. Also fixed pre-existing `select_in_motion_stories` docstring drift ("under acceptance" was the wrong scope — returns IN_MOTION which includes in-progress).
- **`sprint_store.__all__`** — replaced 18 per-line `noqa: F401` with a complete module-level `__all__` enumerating all 37 public names (18 re-exports + 19 module-defined). Partial `__all__` would mislead pyright/import-* consumers.

### Real bug fixes (concerns)

- **JIT-next dep race** — `/xp-story-close` Step 8 ran BEFORE `/xp-accept` Step 4 marks the just-closed story `done`. With the dep gate requiring `done`, solo dep-chained sprints stalled: the next story was invisible to `next-scheduled` until the orchestrator round-tripped back. Sprint-069 hit this — "sprint complete" printed wrongly while 6 scheduled stories remained. Fix: `--treat-as-done STORY_ID` (repeatable) on both `next-in-progress` and `next-scheduled` subcommands; xp-story-close Step 8 passes `--treat-as-done "$STORY_ID"` so the dep check counts the just-closed (mid-merge) story as satisfied. Symmetric application across both subcommands is defensive.
- **CAS-guard for `reviewing→closing`** — the AC1 promise that the singleton-lock transition was CAS-guarded was unimplemented in production. xp-accept Step 1.5 called bare `update-story`, leaning on "single-threaded orchestrator" as the safety argument. New `update-story-if` CLI subcommand wraps the existing `update_story_status_if` helper with rc=0/1/2 contract (success/CAS-mismatch/validation-error). xp-accept Step 1.5 prose updated to call the CAS subcommand and to act on rc=1 (race-loss, skip story) vs rc=2 (validation error, halt) distinctly.
- **Worktree-registry tearDown** — `_IntegrationTestCase` previously leaked `.claude/worktrees/worktree-story-X` registry entries into the next test, breaking reuse-by-id. Sprint-069's capstone hand-picked unique ids (story-A1/B1/C1/D1/E1/E2) as workaround. Per-test tearDown now prunes worktrees via the existing `cleanup_test_worktrees` helper. Fast-path skip when no worktrees were created saves ~10s of subprocess overhead across the full suite. `try/finally` so `super().tearDown()` always runs.
- **`closing-state-lifecycle` decision event** — emitted with stable `--topic closing-state-lifecycle` so any future divergent decision trips the superseded-decision detector.

## v3.1.14 — sprint-069 add 'closing' story state (7 stories, 7/7 velocity)

Sprint-069 inserts a new `closing` state between `reviewing` and `done` in the story lifecycle. Resolves the long-standing `xp-story-close` multi-reviewing race (risk a1244ea46e52): concurrent teammate finish-bursts no longer stall the close pipeline because `reviewing` is now plural-safe and `closing` is the sprint-singleton in-pipeline lock. 7 planned / 7 delivered, 4561 tests pass (was 4528; +33 net).

### Lifecycle reshape (stories 001/002/003)

- **Schema constants** (story-001) — `VALID_STORY_STATUSES` and `IN_MOTION_STORY_STATUSES` extended with `closing`. `ACTIVE_STORY_STATUSES` (`VALID − TERMINAL`) auto-absorbs. Sweeps four docstrings + one CLI help text in `sprint_state.py`/`sprint_cli.py`/`sprint_status.py`/`sprint_store.py` to honestly describe IN_MOTION as "in-progress, reviewing, or closing".
- **Store/state helpers** (story-002) — `has_closing_stories`/`has_closing_stories_data`/`select_closing_stories` mirror the existing `reviewing` family. `count_by_status` and `transitive_active_dependents` auto-extend through their schema-constant keys; explicit regression tests pin both. New `SPRINT_CLOSING_ONLY` test fixture in `conftest.py` for downstream story-005 reuse.
- **`worktree.py` architectural pivot** (story-003) — `find_closing_teammate_worktree` now keys on `status == "closing"` (was `"reviewing"`). The singleton multi-match raise migrates to `closing` so multiple `reviewing` stories with live teammate worktrees no longer trip it. Five sibling tests across CLI wrapper/preload/multi-story integration updated to seed `closing` and explicitly call `update_story_status` to mirror the production `xp-accept` Step 1.5 wiring.

### Hook + helper alignment (stories 004/005)

- **Orphan-branch active-set** (story-004) — `list_orphan_story_branches` switched from a 4-call `list_stories(status=...)` concat to a single set comprehension over `ACTIVE_STORY_STATUSES`. `closing` (and any future status) auto-included; `branching_cli` docstring + help text aligned. Pin tests cover closing-status branch exclusion and the `scheduled`-with-`branch_name` protection.
- **`pre_tool_write` re-arm + `sprint_stop_gate` suppression** (story-005) — `.accept` re-arm and the stop-gate accept cascade both now fire on `closing` in addition to `reviewing` (interrupted close cycles still nudge to `/xp-accept`). Hot-path optimization: `pre_tool_write` switched to a single `read_sprint_content` + `_data` predicate calls, eliminating 3-disk-read regressions on every Write/Edit/MultiEdit.

### Skill prose wiring + capstone (stories 006/007)

- **Step 1.5 reviewing→closing transition** (story-006) — `xp-accept` SKILL.md gains a Step 1.5 between concern triage and `/xp-story-close` dispatch using bare `update-story` (orchestrator is single-threaded across `/xp-accept`; spawn_teammate's CAS pattern doesn't apply because no concurrent writer races this transition). Step 2/3/merge-failure prose updated to read "closing" where it describes the close-window state. Revert path covers both reviewing and closing source states. Cascade-deferral now mentions all 3 in-motion statuses. `xp-story-close` SKILL.md gains a "story state expectation" preamble. PROCESS_GUIDE.md lifecycle line updated to 6-state with `closing` as the singleton lock; stop-gate generalized to "in-motion stories". `xp-kickoff` + `xp-story-close` orphan-set enumeration sweeps + `acceptance_types.py` docstring align. `test_two_teammate_incremental_flow` fence re-tightened from BEFORE the closing-promote to AFTER (story-005's closing suppression makes the truer in-pipeline placement work).
- **End-to-end capstone** (story-007) — New `tests/integration/test_closing_state_end_to_end.py` (5 tests, AC-mapped 1:1) verifies the closing-state architecture end-to-end: state isolation, worktree match, orphan exclusion, pre_tool_write suppression, and the singleton-lock `ValueError` invariant on multi-`closing`+live. Verification-only — first-run pass confirms stories 001-006 actually delivered the contract. Drives `make_teammate_worktree` promotion from per-class duplicates in `test_preload_markers.py` + `test_quality_review_preload.py` to `_worktree_fixtures.py` (refactor-before-add prevented a 3rd duplicate).

### Doc fix from cumulative review

- **`xp-work-selection` SKILL.md `four-state lifecycle` phrase** — predated story-002's `reviewing` addition; now contradicts both PROCESS_GUIDE.md 6-state and the schema. Fixed inline at sprint-close.

## v3.1.13 — free-session debt burndown + CI fix

Free session addressing debt items adopted at kickoff and a CI-only test failure. Seven commits, no new features. Full pytest suite (4528 tests) green throughout.

### CI fix

- **`TestMechanicalPromote` inherits `_SMMTestCase`** — three tests in `test_spawn_teammate.py` failed on GitHub Actions because they hardcoded `--smm-dir /tmp/smm` and that path doesn't exist on CI runners (`worktree.write_story_assignment` → `tempfile.mkstemp` raised `FileNotFoundError`). Local `/tmp/smm` persisted across runs, hiding the failure. Migration to `_SMMTestCase` (which provides a real per-test tempdir, `events.jsonl`/`events.lock`, and SMM_DIR env pin) replaces hand-rolled scaffolding the test was already groping toward.

### Real bug fix

- **`spawn_teammate.py` preserves `prompt_file` on subprocess failure** — the `finally` block unconditionally unlinked `args.prompt_file` even on `CalledProcessError`, breaking re-spawn after a transient teammate failure (hit live in sprint-068). Move the unlink to the success path; combined-prompt file (regenerated each spawn) keeps its `finally` cleanup. New unit + integration tests pin both contracts; the prior integration test was inverted from `_deleted_after_failed_spawn` to `_preserved_after_failed_spawn` since it had pinned the buggy behavior.

### Refactors (debt burndown)

- **`flock_with_timeout` helper extracted** — five near-identical SIGALRM+flock+`os.fdopen` scaffolds (~25 lines each) duplicated across `_append_impl.py` (`read_with_lock` LOCK_SH, `append_event`, `bulk_append`, `replace_events_file` LOCK_EX) and `sprint_store._sprint_lock` (LOCK_EX) collapse to one `@contextmanager`. The helper unifies subtle drift: routes ALL sites through `_safe_open_nofollow` (closing the symlink gap two sites had bypassed), wraps every `LOCK_UN` in `contextlib.suppress(OSError)` (so a flaky release never masks an in-flight exception or blocks `close`). Mode is parameterized. Three new `TestFlockWithTimeout` tests pin the helper's contract directly so the next refactor inherits the spec instead of having to rediscover it.
- **`_PLUGIN_ROOT` centralized across 26 test files** — sprint-068 added a 28th recompute site as a regression after the canonical export at `tests/_bases.py:32` was already in place. Sweep replaces both pattern variants (`Path(__file__).parent.parent.parent` and `.resolve().parents[2]`) with `from _bases import _PLUGIN_ROOT`. Two scaffold tests using `_REPO_ROOT / "plugins" / "xp-agents"` (different semantic — repo root, not plugin root) intentionally skipped. `test_branching_team_scenarios.py` reorders its import so it follows its own `sys.path.insert` for direct-run safety.
- **`_NormalizePathIdentityMixin` promoted to `_worktree_fixtures.py`** — the mixin already lived inline in `test_retro_metrics.py:42`, but `test_probe_adoption.py` (manual setUp) and `test_resolves_probe.py` `TestCountFileOverlaps` (manual attribute swap) each rolled their own variant. Canonical home parallels existing `_lint_fixtures.py`, re-exported from `conftest.py`. Renamed for `_LintTmpDirMixin` consistency (Mixin suffix), lambda parameter `_c` → `_cwd` to mirror the production `normalize_path(path, cwd)` signature. Consolidation pin (`test_single_normalize_path_identity_mixin_definition`) prevents future re-inlining. Five remaining inline `worktree.normalize_path` patches stay inline intentionally — three are non-identity stubs that strip prefixes to assert canonicalization behavior, two are scoped `with patch(...)` blocks where the setUp-mixin shape doesn't fit.

### Doc fixes

- **Worktree prefix typo** — `CLAUDE.md` and `docs/ARCHITECTURE.md` both said the teammate worktree prefix is `teammate-` but `identity._TEAMMATE_PREFIX` is `worktree-story-`. Stale doc misled a `/simplify` reviewer in sprint-068.
- **`xp-plan` SKILL Discovery elevated** — Discovery was already referenced inside the Change Zones and Impact Zones bullets of the "For each milestone" list but not as a step on its own. Planners reading top-down would skip the discovery pass described in the paragraph above. Promote Discovery to its own bullet positioned between Sources and Change Zones.

## v3.1.12 — sprint-068 retro burndown (6 stories, 6/6 velocity) + close-cycle hook fixes

Sprint-068 burns down sprint-067 retro: probe nudges, spawn cleanup, file_domain redesign, test/code hygiene. 6 planned / 6 delivered, all spawned as parallel teammate worktrees. Plus two free-mode bug fixes from mechanics surfaced live during the sprint's close cycles.

### Sprint-068 — signal quality + cleanup (stories 001/002/003/004/005/006)

- **Hoist preload-marker constants** (story-001) — `_XP_ACCEPT_PRELOAD` + `_XP_STORY_CLOSE_PRELOAD` deduplicated into `tests/integration/conftest.py`; `test_conftest_consolidation_pin` enforces the single-site invariant. Drive-by: integration `conftest.py` imports `_PLUGIN_ROOT` from canonical `_bases` instead of re-computing.
- **spawn_teammate proper import + CAS TOCTOU close** (story-002) — `sprint_store.update_story_status_if(expected, new)` adds atomic compare-and-swap holding an exclusive `sprint.lock` flock around load-check-write. `spawn_teammate.py` swaps the racy `get_story` + `update_story_status` pair for the CAS helper, eliminating the silent-demote window. Sys.path bootstrapping consolidated from two sites in `spawn_teammate.py` to one in `worktree.py` — under no-pip constraint, runtime path manipulation is the canonical pattern; partial-resolution recorded for marketplace-cache import test follow-up.
- **Probe selection_reasons in nudge + snapshot freshness** (story-003) — `resolves_probe.build_nudge_lines` appends `(why: <reasons>)` per candidate so the agent sees WHY each was suggested (probe-selection-miss=4 fix). `find_probe_candidates` reloads `events.jsonl` from disk when the caller-supplied snapshot is >5s older than `now_ts` (newer-than-snapshot=3 fix). `_is_events_snapshot_stale` uses ISO-8601 lex-compare for max-ts scan; fail-safe degrades to "trust caller" on missing/malformed input.
- **Verification grep tightening — Wisdom + audit** (story-004) — Wisdom item added: "Bare verification greps only — inspect every hit. Sprint-067 'grep -v test_' masked orphan test refs after ACCEPT_ACTIVE removal." Audit of `plugins/xp-agents/{skills,scripts,smm,hooks}` for `grep -v test_` patterns — zero hits. SMM-only story exposes a corner case in close pipeline (no commits = no merge) — recorded for follow-up.
- **file_domain redesign — discovery-pass + cwd kwarg** (story-005) — Path A chosen via decision event before coding. `triage.extract_file_domain_paths` gains `cwd: Path | str | None = None` kwarg; `xp-plan/SKILL.md` Step 3 documents the discovery pass that greps call-sites of declared symbols and unions them into `change_zones`/`impact_zones` (>20-callers throttle: count + sample). Close-reviewer follow-up tightened `extract_file_domain_paths` to raise `ValueError` on glob-without-context (no implicit-cwd fallback), and `sprint_status.scheduled_file_domains_overlap` dropped its `cwd=Path('.')` cosplay.
- **Fold _normalize_file_set cwd=None affordance** (story-006) — `_normalize_file_set`, `_classify_divert_reason`, `_compute_probe_adoption`, `_compute_resolves_link_rate` cascade-tighten to require `cwd: str` (no None default). Test affordance branch removed; `_PatchNormalizePathIdentity` mixin shared within `test_retro_metrics.py`; broader 8+-copy dedup deferred.

### Free-mode bug fixes from sprint-068 close cycles

- **`pre_tool_bash` honors `git -C <path>`** — sprint-branch protection hook misread `git -C <wt> commit ...` as committing on orchestrator's cwd branch, false-positive-warning every fix-cycle commit to a teammate worktree. `commits.parse_effective_cwd` already handled `git -C` and `cd <path> && git ...` precedence; wired into the branch-check site. Added a substring fast-path so the strip+two-regex scan is skipped for the 99% of Bash calls that can't match either pattern (PreToolUse:Bash fires per-call).
- **`/xp-quality-review` preload narrow TEAMMATE_CWD auto-detect** — preload reported "no changed files" when orchestrator edited a teammate worktree directly (close-cycle fix pass). Re-introduced auto-detect with two narrow guards reversing the prior over-broad heuristic (decision 798a27b425a7): skip if orchestrator has any uncommitted change (hijack guard); auto-set only when EXACTLY one teammate worktree has changes (ambiguity guard). Worktree enumeration matches `worktree-story-` prefix per `identity._TEAMMATE_PREFIX`. xp-accept SKILL prose updated: explicit `TEAMMATE_CWD` pass-through preferred when known, auto-detect is fallback.

## v3.1.11 — sprint-067 incremental teammate accept (5 stories, 5/5 velocity) + CI ordering fix

Sprint-067 ships M-3 (Accept lifecycle ergonomics): incremental teammate accept with **structural elimination of the `ACCEPT_ACTIVE` marker** via close-then-done reorder. 5 planned / 5 delivered.

### Lifecycle reshape (stories 001/002/003/004)

- **`has_reviewing_stories` predicate + Stop-gate widening** (story-001) — `sprint_status.has_reviewing_stories` and `has_in_motion_stories` (consumes `IN_MOTION_STORY_STATUSES` schema constant) join the predicate family with `_data` siblings (single sprint-dict load per Stop hook). `sprint_stop_gate._compute_block_message` Option A: reviewing alone fires the accept gate even without `.accept` marker — teammates self-promote in-progress→reviewing on clean exit, so reviewing-state IS the canonical "needs acceptance" signal.
- **xp-accept reviewing-first dispatch + close-then-done reorder** (story-002) — preload counts reviewing FIRST, falls back to in-progress; `SELECTED_STATUS=` routes the SKILL prose. SKILL.md restructured: `/xp-story-close` runs FIRST (story stays in `reviewing`), decisions recorded next, mark-done as the FINAL step after merge. Merge-failure leaves story in reviewing for retry. `select_in_motion_stories` widens concern-triage + acceptance-types to the full in-motion set.
- **`/xp-story-close` discovery flips done→reviewing** (story-003) — `worktree.find_closing_teammate_worktree` keys on `status == "reviewing"` (not `done`). Inverse-regression pins (`test_returns_none_when_done_with_worktree`, `test_empty_stdout_when_only_done_status`) guard against a future flip back. Story stays in `reviewing` while close runs; mark-done is the FINAL step.
- **`ACCEPT_ACTIVE` marker deleted entirely + mechanical teammate promote** (story-004) — close-then-done makes the marker structurally moot. `pre_tool_write` re-arm predicate uses `has_reviewing_stories` directly. Removed from `markers.py`, `marker_names.py`, `_preload_base.sh`, 4 close-skill preloads, `xp-kickoff` defensive cleanup, and `xp-quality-review` preload's auto-detect heuristic (per decision 798a27b425a7: explicit `TEAMMATE_CWD` env-passthrough only). `spawn_teammate.py` mechanical-promote: post-rc=0 calls `sprint_store.update_story_status(story_id, "reviewing")` with an in-progress guard against silent demotion. PROCESS_GUIDE + `_TASK_CREATION_NUDGE` updated for the incremental loop pattern.

### Capstone (story-005)

- **End-to-end composition pin** — `tests/integration/test_incremental_teammate_accept.py` walks the full two-teammate flow (mechanical promote, reviewing-first dispatch, `pre_tool_write` non-arming during the close window, A close-then-done via `xp-story-close` + `merge_teammate_branch`, B identical flow, final-state checklist) plus `test_merge_failure_leaves_reviewing` for the source-survives + no-auto-rollback contract. Helper extractions to `_branching_fixtures.py` (`create_teammate_worktree_with_commit`, `merge_teammate_branch`, `git_log_oneline_at`) consolidate verbatim duplication with `test_multi_story_accept_flow.py`; `branch_exists` adoption replaces inline `git rev-parse --verify` subprocesses.

### CI ordering fix

- **Workflow installs ruff before tests** — story-007's `_staged_ruff_findings` invokes ruff at test time via `lint_check.run_linter_batch`. The pre-existing `tests.yml` ran tests BEFORE `pip install ruff` (ruff was installed only for the trailing lint step), so commit-gate tests failed in CI with "ruff not on PATH" while passing locally. Move install ahead of the test step.

## v3.1.10 — sprint-066 R1 signal-quality hardening (8 stories, 8/8 velocity, 8 parallel teammates)

Sprint-066 ships 8 stories at 1.00 velocity / zero carryover — first sprint where every story spawned to its own teammate worktree and shipped in parallel. Six items from R1 feature-requests (#2, #3, #4, #6, #7, #8) plus four sprint-065 retro adoptions (probe_divert classifier blind spot, validate-domain glob drift, run_linter_batch fail-open, /xp-quality-review preload TEAMMATE_CWD routing). M-1 marked delivered.

### Probe + reviewer signal-quality (stories 001/002/003/004/005)

- **Probe candidates include `type=discovery`** (story-001) — `resolves_probe.find_probe_candidates` widens its candidate filter on both file-overlap and in-sprint-batch sibling axes; commits closing a discovery now surface as ranked trailer candidates instead of forcing hand-edits. Drive-by extracted `_count_file_overlaps` shared helper; raw `"concern"` string fixed to `_common.CONCERN`.
- **Plan-reviewer NEW-file rule + trace reclassification + AC2 loop pin** (story-002) — `xp-plan-reviewer.md` §10c rejects plans whose story description names new-file verbs (`extract`/`introduce`/`add module`/`create helper`) but omits the implied path from `file_domain`; matches on whole-word verb + NEW-file context token (path-like, `module`, `helper`, `file`, `to its own`) in same sentence so bare `"extract value from X"` doesn't false-trigger. §11 reclassifies "verified-clean trace" emissions to `type=decision` (or `type=status,category=trace`) so the unresolved-concern metric stays clean. AC2 pin runs the rule loop directly against synthesized in-memory plans.
- **Code-reviewer debt resolves-link + new-pattern decision nudge** (story-003) — `xp-code-reviewer.md` gains §3a (resolve-and-replace via `metadata.resolves` — the universal resolution link, NOT `smm_cli update-item` (pillar-scoped) NOR `metadata.supersedes` (decision-only per `concerns.py` pattern #5)) and §3b (advisory nudge to emit `type=decision` event with stable `--topic <slug>` when a commit introduces a new architectural pattern, so pattern #5 can later detect divergence as supersession). `duplicate_debt_probe.build_advisory_concern` content rewritten to direct anchor relocation rather than hint at duplication.
- **Superseded-decision detector → session window** (story-004) — `concerns.py` pattern #5 slices events from the most recent `SESSION_END` forward via canonical `_common.current_session_start_index`, eliminating cross-session false positives on stable topics (execution-mode, css-prefix-convention, retro-try-resolves-trailers). Already-accepted-topics resolution stays scoped to the window.
- **Probe divert classifier names all sprint pairs + file-overlap normalization** (story-005) — `retro_metrics._classify_divert_reason` extends bucket set with `MISSING_EVENT` (rejected ID has no backing event) and `PROBE_SELECTION_MISS` (in-domain candidate the probe missed); all 8 sprint-065 paired-divert fixtures now classify non-`unknown`. File-overlap canonicalization via `worktree.normalize_path` plumbed through `retrospective._compute_resolves_link_rate → _compute_probe_adoption → _classify_divert_reason`.

### Cascade analysis (story-006)

- **`extract_file_domain_paths` glob expansion** — `smm/triage.py` gains optional `candidate_files` kwarg with a `**`-aware glob translator (LRU-cached) that handles `tests/hooks/**/*.py` semantics `fnmatch.translate` can't express. Wired at the cascade-analysis callsites (`story_metrics._attribute_commits`, `story_metrics.resolve_dominant_story`, `concern_triage.find_concerns_for_story`) so glob entries in `file_domain` no longer flag legitimate in-scope edits as drift. Path.glob fallback for callers without candidate files. Resolves 6 sprint-065 historical drift concerns retroactively.

### Linter contract + parser hygiene (story-007)

- **`run_linter_batch` fail-closed + scaled timeout** — `pre_tool_bash._staged_ruff_findings` raises `BlockedError` when any staged `.py` path is missing from the batch result map (timeout, missing binary, partial run); unverified F401/F811 cannot ship. Batch timeout scales `min(10, 5 + 0.05*N)` so single-file batches degrade as fast as `run_linter`'s 5s per-file path while large batches cap at 10s. `LINTER_BASE_TIMEOUT_S` / `BATCH_TIMEOUT_PER_PATH_S` / `BATCH_TIMEOUT_CAP_S` constants extracted for single-source-of-truth.
- **`bash_post_tool` single-scan parser hygiene** — `git_commits._strip_quoted` promoted to public `strip_quoted`; `is_git_commit` and `commits.parse_effective_cwd` accept optional pre-stripped `scan_target` arg. `bash_post_tool.run` strips the command ONCE per Bash and threads the result into both helpers, eliminating the redundant `re.DOTALL` heredoc scan that fired twice on every commit-shaped Bash. Pinned by `TestStripQuotedSingleScan` (call-count == 1).

### Preload teammate-cwd routing (story-008)

- **`xp-quality-review` preload routes diff capture to `TEAMMATE_CWD`** — `skills/_preload_base.sh` `dump_diff` and `get_changed_files` now run via `_git()` which prefixes `git -C "$TEAMMATE_CWD"` when set, otherwise plain `git`. Default behavior unchanged for every existing caller. `xp-quality-review/scripts/preload.sh` auto-detects fix-cycles: when `ACCEPT_ACTIVE` marker is present and exactly one in-motion (`in-progress`/`reviewing`) story has a live teammate worktree, sets `TEAMMATE_CWD` to that worktree path. Explicit `TEAMMATE_CWD` always wins; ambiguous matches fall back to orchestrator cwd. Without this, `/xp-accept` teammate fix-cycles fed the reviewer the orchestrator's incidental edits and missed the teammate's actual changes.

### Process firsts

- **First all-parallel sprint** — 8 teammate worktrees spawned simultaneously via `/xp-assign`, each running its own TDD plan-cycle (red → green → /simplify → /xp-quality-review → commit) in isolation. No solo fallback; no chained sequential work.
- **Per-story close-reviews caught and addressed inline**: 10 reviewer concerns surfaced across 8 stories; 6 fix-routed (false-trailer re-open + new debt tracker, direct unit test addition, conftest re-export, regex tightening, false-positive guards, prompt restructure to bulleted subsection); 4 ASK-routed (tracked debts or retro signals).
- **Mechanism honesty correction** — story-003 AC1 literal wording named `smm_cli update-item` and `metadata.supersedes`; verification during /xp-quality-review proved both wrong (update-item is pillar-scoped, supersedes is decision-only). Pivoted to `metadata.resolves`; AC1 intent (consolidate, don't duplicate) satisfied; AC literal-text drift surfaced for retro.



Sprint-065 ships 19 stories at 1.00 velocity / zero carryover — burns down all 5 sprint-064 carry-forwards plus 4 retro Tries, 5 adopted debts, and 5 adopted concerns. Two silent production bugs caught + pinned mid-sprint (ruff 0.15+ output-format change had killed the F401 deferral pipeline; `run_linter_batch` would have silently let F401/F811 through commit gate on hung-ruff timeout). Wave-2 ran 4 parallel CLI teammates; Waves 1+3 solo serial. Friction #4 (`.accept` marker re-arm) reproduced live and captured for next sprint.

### Type-quality `_required` convention (stories 002/003/004)

Three sibling helpers eliminate the per-site `assert x is not None` pyright-narrowing crutch that had spread to 53 call sites:
- `_AssertNotNoneMixin._assert_not_none(value) -> T` on `tests/_bases.py` (mixed into `_SMMTestCase` + `_IntegrationTestCase` + 2 standalone unittest.TestCase subclasses); 38 site migration across `tests/hooks/` and `tests/integration/`.
- `execution_plan_store.load_plan_required` + `sprint_store.load_sprint_required` (latter promoted from existing private `_load_required` with internal callers renamed); 11 site migration. `compute_story_analysis_required` was added then dropped during review — zero migration-candidate callers (retrospective.py legitimately handles None).
- `event_schema.get_required_budget(event_type) -> int` raises ValueError for unknown types OR known-but-uncapped (None); 6 site migration. The concerns.py site is a small reliability win — original `assert _budget is not None` strips under `python -O`; the new ValueError raise is unconditional.

Each helper has a no-bare-narrowing pin scoped to its callsite tree. Convention documented in CLAUDE.md.

### Silent production bug fixes (stories 018/020)

- `lint_check._RUFF_LINE_CODE` only matched ruff's legacy concise output; ruff 0.15+ defaulted to multi-line "full" format with `-->` arrows. The entire story-007 F401/F811 deferral pipeline was silently dead in production — only "passing" via mocked unit tests. Fix: `--output-format=concise` pin in `_LINTER_COMMANDS["ruff"]` plus `_PYFLAKES_CODE_SHAPE` widened to `[A-Z]+\d{3,4}`. New AC4 E2E pin (`test_replace_all_e2e.py`) drives Edit→Edit→git commit through the real hook chain so a regression here trips the test.
- `lint_check.run_linter_batch` would have returned `{p: []}` on `subprocess.TimeoutExpired` — silent "all clean" that bypasses the F401/F811 commit gate. Fix returns `{}` so callers fall back to other gates; pin test asserts the empty-vs-per-path-clean distinction.

### Test fixture consolidation (story-020 bundle, story-016)

- `_MixinBase` (3 inline copies → `tests/_test_typing.py`)
- `_LintTmpDirMixin` (1 inline + 13 hand-rolled `mkdtemp/ruff.toml` triples → `tests/_lint_fixtures.py`)
- `_split_frontmatter_body` (2 copies → `tests/_md_helpers.py`)
- `_MARKERS_PY` (2 sites → `tests/_bases.py`)
- `_assert_text_ordering` (3 inline triplets → `tests/_close_fixtures.py`)
- `make_fake_copy_failing_on_backup_restore` (2 sites → `tests/scaffold/_helpers.py`)

Each consolidation has a no-duplication pin in `test_conftest_consolidation_pin.py`.

### Probe + reviewer doctrine (stories 006/008/009/017)

- `probe_divert_details` now classifies divert reasons (`newer-than-snapshot`, `outside-file-domain`, `cross-story`, `wrong-type`) at retro-time so retros surface the dominant failure mode.
- `session_end._sweep_stale_concerns` emits NEW concern with `references=[root_id]` + `metadata.flagged_stale=True` (cascade via WEAK references; not a status hack). `xp-retrospective.md` got a Stale-Flag Concerns section directing the agent to surface them in the Fix lens.
- All 4 reviewer agents (close, code, plan, sprint) + retrospective got the `references=[root_id]` cascade-link doctrine paragraph; `test_retro_flag_cascade.py` pins both the prose presence (frontmatter-aware grep) and the cascade-close behavior end-to-end.
- `xp-plan-reviewer.md` Section 10b: AC-command/file_domain coherence check at plan time. Catches `acceptance_execution.command` pointing at files outside the story's `file_domain` (the sprint-065 story-006 incident — AC was green without testing anything the story added). Covers pytest, `python -m unittest discover`, and direct `python <path>` / `bash <path>` invocations.

### Hook hardening (stories 007/014)

- `parse_effective_cwd` (in `scripts/commits.py`) now strips quoted/heredoc bodies via `git_commits.strip_quoted` before scanning for `cd <path>` / `git -C <path>` tokens. Meta-commit messages quoting `cd /tmp` no longer retarget cwd. Pinned by `TestParseEffectiveCwdHeredoc`.
- ruff F401/F811 hook checks deferred from edit-time to staging-time so multi-file `replace_all` migrations (import added in file A, consumed in file B mid-edit) don't trip stale-F401 false positives.

### Other

- `verify_acceptance.py` stderr now names `commands[N] failed` for multi-command AC; single-command keeps `command failed` (story-001).
- Phase 6 capstone replaced its synthetic-fence test with a real stranding-vector test (`test_real_stranding_vector_when_marker_unconsumed`) that drives the marker write through the `markers.py` CLI (story-005).
- Repo-root `pyrightconfig.json` (post-sprint chore): mirrors plugin-local config with path prefixes; closes IDE language-server discovery gap. Sync-invariant test in `test_pyrightconfig_extrapaths.py` catches drift between the two configs.

### Doc reorg

- `docs/ideas/3` split into doc 8 (incremental teammate acceptance via reviewing self-promote) + doc 9 (`.accept` marker re-arm investigation). Execution plan M-3 reframed from "defensive preload widening" to "producer-attests-green incremental acceptance" referencing R8 + R9.

## v3.1.8 — sprint-064 deferral burndown + type-quality cleanup

Sprint-064 burns down 10 of 15 deferred stories from sprint-063 plus retro-Try aged debt. No new milestone — explicit "deferred-only sweep" carrying 5 stories forward to sprint-065. Two long-standing 7+ session aged debts close (`events_of_type` 184-site consolidation; `assertEqual` vocab pin 36-site migration). Mix of solo-mode (story-002, story-003) and 7-teammate parallel execution (story-004/005/006/007/013/014/015) with full close-cycle review per story.

### `events_of_type` helper (story-002)

NEW `smm/event_helpers.py` exposes `events_of_type(events, type_name) -> list[dict]` with defensive `.get("type") == type_name` matching the prevailing call-site pattern. Migrated ~120 sites across 24 test files from `[e for e in events if e.get("type") == X]` (and `next(...)` generator-fetch variants converted to `events_of_type(events, X)[0]` for full pattern uniformity). Docstring documents intentional exclusions (chained filters, content-based filters, non-event iterables in test_validation*). Resolves aged debt `0de25f1600df` (7+ sessions stale; re-proposed across 3 retros).

### `assertEqual` vocab pin (story-003)

NEW `tests/hooks/test_assertequal_vocabulary_pin.py` is the sister to `test_event_vocabulary_pin.py`. Walks AST for `assertEqual(event["type"], "literal")` / `assertEqual(event.get("type"), "literal")` (and reversed-arg + assertNotEqual variants) where the literal is a bare string in `event_schema.VALID_TYPES`. Migrated 36 event-domain sites across 11 test files; ALLOWLIST mirrors the sister pin's SMM-domain exclusions (`test_smm_store.py`, `test_smm_cli.py`) since the SMM pillar `type` field uses `smm_schema.VALID_INTENT_TYPES`, a vocabulary distinct from event_schema. Resolves aged debt `04393723d6f5`.

### Shared pin helpers (sprint-direct cleanup)

NEW `tests/_pin_helpers.py` extracts `files_to_scan(root, exclude_self)` + `rel(path, repo_root)` from the two AST vocab pins. Each pin keeps its own `_scan_file` walker (different violation shapes) but shares the file-discovery boilerplate. Helper at `tests/` root matches sibling `_*.py` modules.

### Type-quality cleanups (stories 004/005/007)

- `pre_tool_write.check_tdd_order` widened from `file_path: str` to `str | None` — body always handled None; signature now matches runtime contract; drops `# type: ignore[arg-type]` in tests.
- `_LintTmpDirMixin` adopted the `_MixinBase = TestCase if TYPE_CHECKING else object` pattern already used in 2 sibling files. Pyright sees TestCase, runtime sees object (so pytest doesn't auto-collect the empty mixin surface). Drops `# type: ignore[misc]` from `super().setUp/tearDown`.
- `fake_write **kw` relaxed from `str` to `Any` so the test double doesn't silently shadow future non-str kwargs added to `write_text_atomic`.

### Drift guards (stories 006/014/015)

- NEW `tests/integration/test_pyrightconfig_extrapaths.py` reconciles `pyrightconfig.json:extraPaths` against `skills/*/scripts/` in both directions (dead entries + missing entries).
- NEW `tests/integration/test_execution_plan_ac_sync.py` walks `execution_plan.json:milestones[*].acceptance_execution` and asserts every delivered-milestone command resolves to >0 collectable tests via `pytest --collect-only`. Closes a real false-green hole — M-2's AC referenced `test_stop_close_marker.py` which never existed; pytest exits 0 when no tests collect, so the milestone gate silently passed. Pin skips planned milestones (verified at ship time).
- NEW `tests/hooks/test_hooks_json_strict.py` asserts `hooks/hooks.json` parses with strict `json.load` (no trailing commas). Paired with `ruff.toml` `extend-exclude = ["**/hooks.json"]` + `force-exclude = true` — the latter is required so the exclude fires when `ruff format <file>` is invoked explicitly (verified empirically: ruff DOES corrupt hooks.json without the exclude).

### `STEP_4_5` → `STEP_4_SECURITY` token rename + cross-file sweep (story-013 + sprint-direct)

M-2 (sprint-063) reordered `/security-review` from Step 4.5 to Step 4 in close-skill prose but kept the literal `STEP_4_5` LLM-match token to avoid prose churn. Story-013 closes the loop: token renamed to `STEP_4_SECURITY` ("Step 4 IS the security review") in `xp-story-close/SKILL.md` (6 occurrences) + `tests/integration/test_xp_story_close_security_gap.py`. Cross-file follow-up renamed `_Step4_5SecurityIncludeTests` mixin + 4 sibling `TestXxxCloseStep4_5` classes to drop the `_5`. Sprint-direct sweep of "Step 4.5" prose drift across 7 more files (`TEAMMATE_GUIDE.md`, `PROCESS_GUIDE.md`, `agents/xp-retrospective.md`, `scripts/pre_tool_bash.py` comment, 3 test files) — doctrine now consistent across shipped guides, agent docs, production code, and test scaffolding.

### Carry forward to sprint-065

5 deferred stories: `story-008` (verify_acceptance multi-cmd failure naming), `story-009` (`_assert_not_none` helper), `story-010` (`_required` loader variants), `story-011` (`get_required_budget` — also fixes a real None-deref at `concerns.py:271`), `story-012` (Phase 6 capstone real stranding-vector test). Plus one new follow-up concern from story-014 close-reviewer: fixture-based AC-sync pin that always runs (today's pin skips when SMM unresolvable).

### Process discoveries

- Probe candidate snapshot story (originally story-001) was DROPPED mid-plan after exploration revealed the probe already runs live at commit time in `pre_tool_bash.py:251` — no work-selection-time snapshot exists. Recorded as discovery for next sprint to characterize the actual divert root cause.
- Two `validate-domain` false positives this sprint (story-002, story-003) reported `tests/**/*.py` glob expansions as drift. The script doesn't expand globs; file_domain glob entries should match prefix or be enumerated.
- `ruff format` does corrupt `.json` files (verified MD5 change); `force-exclude = true` is required alongside `extend-exclude` for the exclude to fire on explicit file args.

## v3.1.7 — close-cycle security-review stall fix (M-2)

Sprint-063 ships M-2 of the 3-milestone plan from `docs/ideas/2-security-review-swap.md` — eliminates the close-cycle stall where `/security-review` would complete and the agent would forget to invoke `xp-close-reviewer` next, leaving the close cycle hung until the user typed "continue". Resolves Risks-pillar concern `633d3082139d` (recurring across 3+ sessions). Three stories shipped via two parallel CLI teammates plus a solo capstone, with a [sprint-direct] cleanup landing the close-reviewer's quality findings before merge.

### Marker-gated Stop hook (`close_cycle_stop_gate.py`)

New presence-only marker `CLOSE_CYCLE_ACTIVE` (`smm/marker_names.py` + `scripts/markers.py`) plus a new Stop hook `scripts/close_cycle_stop_gate.py` registered in `hooks/hooks.json` between `sprint_stop_gate` and `housekeeping_stop_gate`. While the marker is present, the hook blocks Stop with the message *"Close cycle mid-flight. Run /security-review then invoke xp-close-reviewer (Agent tool); then continue Steps 5-7."* Defers on `ASKING_USER` so `AskUserQuestion` dialogues complete cleanly. Review-cycle/teammate deferrals are intentionally omitted — the close cycle wants to block mid-cycle by design (the whole point is to keep attention in the close pipeline until close-reviewer runs).

### Marker consumption: `subagent_stop._handle_close_reviewer_done`

New helper in `scripts/subagent_stop.py` consumes `CLOSE_CYCLE_ACTIVE` when an `xp-close-reviewer` subagent completes (matches both bare `xp-close-reviewer` and the namespaced `xp-agents:xp-close-reviewer` agent_type). **Wired into `run()` BEFORE the `is_xp_agent` early-exit** — xp-close-reviewer is xp-* and would otherwise be silently bypassed, leaving the Stop gate blocking forever. Comment at the call site documents the trap so a future re-order surfaces a deliberate review.

### Step-order swap across 4 close skills

`/security-review` now runs FIRST in the close pipeline (Step 4, was 4.5) and `xp-close-reviewer` runs LAST (Step 4.5, was 4) across `xp-{free,sprint,plan,story}-close/SKILL.md` and the shared `scripts/_close_pipeline_shared.md`. The new Step 4 prose instructs the LLM to write the `CLOSE_CYCLE_ACTIVE` marker via the generic `markers.py` CLI before invoking `/security-review`, so the Stop hook holds the agent in the close cycle until close-reviewer completes. Why the swap: PostToolUse:Skill nudge fires at skill-LOAD time, not skill-COMPLETION — by the time SECURITY_COMPLETE arrives, the resume nudge has scrolled out of attention. Inverting the order pairs with the marker-gated Stop so attention naturally lands on close-reviewer last, then proceeds to merge. Used Option A (keep step numbers, swap content) to minimize diff churn through cross-references. Story-close preserves the literal `STEP_4_5: APPLIES`/`STEP_4_5: SKIP` LLM-match tokens unchanged in its conditional gate's bash echo lines.

### Generic `markers.py` CLI (allowlisted)

`python3 scripts/markers.py --smm-dir <DIR> write|consume <NAME>` gives close skills (and any future caller) a uniform way to drive marker state without per-marker CLI proliferation. The CLI is intentionally restricted by `_CLI_ALLOWLIST = frozenset({"CLOSE_CYCLE_ACTIVE"})` via `argparse choices=sorted(_CLI_ALLOWLIST)` — every other non-agent-scoped MarkerDef (KICKOFF, ASSIGN_PENDING, ACCEPT_ACTIVE, PLAN_AWAITING_REVIEW) has its own deterministic writer in a hook or skill; the CLI is NOT a back door for those flows. Pattern mirrors `smm/event_schema.py:VALID_SEVERITIES`. argparse imported lazily inside `main()` because `markers.py` is loaded by every Stop / PreToolUse / PostToolUse / SubagentStop hook on every tool invocation.

### E2E integration capstone

`tests/integration/test_close_cycle.py` exercises the full marker lifecycle in two tests: (1) positive flow — write marker → close_cycle_stop_gate blocks → seed SECURITY_COMPLETE event → STILL blocks (the gate watches markers, not events — the load-bearing architectural invariant) → drive `subagent_stop.py` with `agent_type=xp-close-reviewer` → marker consumed → gate releases (no stall demonstrated). (2) negative sidestep — bare `/security-review` outside a close cycle never trips the gate (manual invocations stay cheap). AC #4 (per-skill ordering pin) was deliberately not duplicated here — `_Step4SecurityIncludeTests` mixin in `tests/_close_fixtures.py` already covers it across all four close-skill test classes; restating in the capstone would add a third place to update.

### Sprint-close polish

Two close-reviewer findings landed in the same release via [sprint-direct]: `markers.py` CLI was originally permissive (any non-agent-scoped MarkerDef via getattr), tightened to `_CLI_ALLOWLIST`; `close_cycle_stop_gate.py` block message originally claimed `/security-review just completed` but the marker is written BEFORE the security review fires, so the wording was misleading on early-stop edge cases — reworded to *"Run /security-review then invoke xp-close-reviewer..."*. Dead `if marker.agent_scoped` check removed (now unreachable since the allowlist contains only non-agent-scoped markers).

### Carry-forwards

12 ad-hoc stories were adopted into sprint-063 from retro Tries + open debts/concerns/questions but not scheduled in the M-2 wave: probe-snapshot at commit time, two aged-debt vocab refactors (164-site `_events_of_type` helper + 44-site `assertEqual` pin), multi-command AC dogfood, six pyright/type-narrowing cleanups, fake_write narrowing, Phase 6 capstone real-vector test. All deferred — they carry forward to the next sprint via `/xp-sprint-start`'s "Deferred Stories from Previous Sprint" mechanism with full design context preserved.

## v3.1.6 — workflow plumbing: multi-AC schema + worktree-aware trailer (M-8)

Sprint-062 closes M-8 — addresses the four close-cycle frictions surfaced by sprint-061's retro: worktree commits silently broke `Resolves-Event:` auto-link, single-string acceptance schemas couldn't enforce multi-command verification, plus two friction points (xp-accept preload missing `reviewing` stories + `.accept` marker re-arm whack-a-mole) deferred to a follow-up sprint. Five stories shipped via four parallel CLI teammates plus a solo capstone composing the behavioral changes end-to-end.

### Multi-command `acceptance_execution` schema + new `verify_acceptance.py` CLI

`acceptance_execution` now accepts `commands: list[str]` (run in order, fail on first non-zero) xor the back-compat `command: str` (single command). Both shapes validate; existing single-command stories continue to work unchanged. New `scripts/verify_acceptance.py --story <id> --smm-dir <path>` CLI iterates commands, exits non-zero on first failure with the failing command in stderr. Story-001 of sprint-061 had hit this trap — its acceptance gate ran pytest-only while a separate AC grep was unverified.

### Worktree-aware trailer extraction (`commits.parse_effective_cwd`)

The PostToolUse:Bash trailer-extract hook used to read HEAD from `input_data.cwd`, but `cd <wt> && git commit && cd -` caused the hook to fire AFTER the cd-back — wrong repo, wrong HEAD, silent `Resolves-Event:` auto-link break. New `commits.parse_effective_cwd(command, fallback)` parses bash command text for `git -C <path>` (highest precedence) and `cd <path>` segments, validates with `is_dir()`, and feeds the resolved cwd through to `commits.{get_committed_files,get_head_commit_hash,get_commit_message_body}` PLUS `_resolve_story_id` and `lint_resolution.{resolve_lint_on_commit,sweep_orphan_lint_concerns}`. xp-code-reviewer caught the propagation gap mid-story (concern fa4eb693f334) — same root cause, same one-line fix per call site. Heredoc commit-message edge case deferred as debt ac4e50100b34.

### PreToolUse:Bash warn-only matcher for `cd <worktree> && git`

Belt-and-suspenders for the worktree-cd footgun. `pre_tool_bash.py` matches `cd <wt> && git (commit|add|merge|push)` patterns — including chained shapes like `cd <wt> && pytest && git commit` — and emits an `additionalContext` warning suggesting `git -C <wt>`. Warn-only, never blocks. The first-attempt regex used nested non-greedy quantifiers and pathologically backtracked on a 20-segment chain; redesigned to a single non-greedy `[^\n]*?` (linear, no nesting). `WORKTREE_PATH_FRAGMENT` initially exported from `pre_tool_bash.py`, then consolidated to `identity.py` as the canonical home (sprint-close cleanup) — `pre_tool_bash.py` and `worktree.py` now re-export from there.

### `git -C` + `verify_acceptance.py` doctrine in close skills + TEAMMATE_GUIDE

Doc-only Tier-2 reinforcement: `_close_pipeline_shared.md` (Step 5c fix-cycle classify), `xp-accept/SKILL.md` (debug-and-rerun branch), and `TEAMMATE_GUIDE.md` (Commit Conventions) all now document `git -C <worktree>` as the correct pattern + `verify_acceptance.py --story <id>` as the before-flipping-to-reviewing checkpoint. Pin tests in `test_plugin_integrity.py` use the existing frontmatter-stripping helper and co-locate the timing phrase within ±2 lines of the CLI mention so a future edit can't drop the timing.

### Cross-cutting M-8 capstone

`tests/integration/test_milestone_08_capstone.py` exercises stories 001-003 end-to-end: real git worktree fixture under the canonical `WORKTREE_PATH_FRAGMENT`, opens a concern with a known event id, drives the bash hook pipeline for both commit shapes (`cd <wt> && git commit` and `git -C <wt> commit`), and asserts auto-resolution + worktree-SHA in `metadata.commit_hash` + warning-emission asymmetry. AC1+AC2 share a parametrized helper after the simplify+reviewer pass caught duplication.

### Sprint-close polish

Two sprint-coherence gaps caught by the close-reviewer landed in the same release: `xp-accept/SKILL.md`, `xp-plan/SKILL.md`, and `xp-sprint-start/SKILL.md` now teach the `commands: list[str]` shape (not just `command`); `WORKTREE_PATH_FRAGMENT` consolidated to `identity.py` as the single source of truth (was awkwardly housed in `pre_tool_bash.py`).

### Declarative doctrine reorganization

Post-merge cleanup established a clearer convention: `/docs/` holds declarative subsystem references (present-tense "X works like Y"), `/docs/completed/` holds design lineage (migration plans, "before" framings, status histories). `BRANCHING_DOCTRINE.md` lightly trimmed; `ACCEPTANCE_TESTING_DOCTRINE.md` moved from `/completed/` to `/docs/` with stale-reference fixes (commit loop no longer cites the deleted per-commit security step; schema mentions both `command` and `commands`); new `SECURITY_REVIEW_DOCTRINE.md` written as a declarative tier-model description (the original v3.0 cutover narrative preserved at `/docs/completed/SECURITY_REVIEW_MIGRATION.md`). `ARCHITECTURE.md` gains a "Subsystem Doctrines" section linking the three.

## v3.1.5 — pyright cleanup of tests/ + M-6b pin-coverage extension (M-7)

Sprint-061 closes M-7 — clears 25 pyright errors + 372 warnings out of `tests/` so the directory can be re-included in `pyrightconfig.json`'s `include` list. Six stories shipped via 5 parallel CLI teammates plus a solo capstone (story-005) that absorbed 55 residual errors after the parallel batch landed. Net effect: `tests/` is back in pyright's strict-check scope, and the M-6b vocabulary pin gained three coverage extensions that close gaps the original walker missed.

### M-6b vocab pin: kwarg form + `_*.py` helpers + Attribute matching

Story-001 extended the pin walker added in M-6a with three coverage gaps the original missed:
- **Gap 1** — `make_event(event_type='concern', ...)` kwarg form. Original pin only walked positional args.
- **Gap 2** — `_*.py` helper modules (`_event_fixtures.py`, etc.) were excluded from the walk; sweep + re-include.
- **Gap 3** — `ast.Attribute` matching (e.g., `helper.make_event(...)`) tightened to known fixture modules so non-fixture aliases don't false-trigger.

Plus per-file ALLOWLIST mechanism for legitimate bare literals (e.g., SMM intent dicts where `'goal'` is data, not vocabulary).

### tests/ pyright cleanup (Optional narrowing)

Stories 002/003/004 swept `tests/` directory-by-directory — 80+ Optional-narrowing assertions added (`assert x is not None`), pyright errors cleared in scaffold/integration/smm/hooks subtrees. Story-005 capstone re-included `tests/` in `pyrightconfig.json` and absorbed 55 residual errors the parallel batch missed. Pure refactor-mode work; no behavior changes; test count unchanged.

### RHS sweep on test fixture literals

Stories 002/003 also swept the right-hand side of comparisons — `e['type'] == 'concern'` style — for the same EVENT_TYPE_* substitution treatment. Concrete coverage across small-dirs cleanup (story-002) and the hooks-batch-A subagent/lifecycle clusters (story-003).

## v3.1.4 — event-type vocabulary sweep + Pillars doctrine (M-6a)

Sprint-060 closes M-6a — the test-suite vocabulary sweep that replaces bare event-type string literals (`'concern'`, `'status'`, `'goal'`, etc.) with `EVENT_TYPE_*` named constants across the entire `tests/` tree, plus a doctrinal pin test that forbids future regressions. Seven stories; final coverage spans 22+ files. Story-006 added a `## Pillars` section to PROCESS_GUIDE.md so the four-pillar SMM (Intent / Constraints / Risks / Wisdom) has a single canonical reference inside the shipped guide.

### Vocabulary sweep across tests/

Stories 001/004/005 swept the SMM, common, and Bash-hook test clusters; story-003 added the doctrinal pin test that fails CI if a bare event-type literal lands in `tests/` going forward. Each batch was a refactor-mode commit (no behavior changes) — `make_event('concern', ...)` → `make_event(EVENT_TYPE_CONCERN, ...)`. The sweep removes the entire class of typo bugs where a literal like `'concren'` would silently pass tests because no static check caught the typo.

### `## Pillars` section in PROCESS_GUIDE.md

Story-006 added a canonical four-pillar reference (Intent / Constraints / Risks / Wisdom) directly to the shipped process guide. Curator agents (`xp-housekeeper`) and consumers (anyone reading the guide) now have a single source of truth for what each pillar holds. Story-007 added a pin test asserting the section's presence so a future trim can't silently drop it.

### Doctrinal pin: no bare event-type literals in tests/

Story-003 added an AST-based test (`tests/hooks/test_event_vocabulary_pin.py`) that walks every `make_event(...)` call site in `tests/` and fails on bare string literals. Allowlist mechanism for legitimate cases (e.g., SMM intent dicts where the literal is data, not a vocabulary marker). The pin closes the loop on the sweep — the codebase can't drift back to the pre-sweep state without a test failure.

## v3.1.3 — branching.py coherence + retro-link integrity (M-4)

Sprint-059 closes M-4 (branching.py coherence + xp-kickoff Step 2.4 prose) and adds two stretch stories addressing retro-link integrity. Five stories, all delivered solo (story-002's branching.py touch made parallel teammates unsafe). Net effect: every stage-aware entry point now goes through the auto-promote chokepoint, the `_log_hook_error` cross-module symbol drops its private prefix, the high-zero-decision-rate signal finally fires in production, and `metadata.resolves` malformations get caught at write time instead of silently iterating string characters.

### `get_primary_branch` routes through `get_branching_stage`

The auto-promote side-effect (Stage 1 → 2) lived inside `get_branching_stage` per the v3.1's single-chokepoint constraint, but `get_primary_branch` was reading `_load_branching_strategy` directly and bypassing the chokepoint. Stage 1 reads of the primary branch silently left the project at Stage 1 until some other caller went through `get_branching_stage`. Routing `get_primary_branch` through `get_branching_stage` closes the bypass — every stage-aware entry path now fires the promotion. New `test_create_story_branch_promotes_stage_1_e2e` mirrors the existing sprint-branch test to pin the contract on the story path too.

### `BRANCH_MIN_STAGE` honesty: story/free/scaffold bumped to 2

Stage 1 is dead code under v3.1's auto-promote — any read of `get_branching_stage` upgrades 1 to 2 before any caller observes 1. Keeping `BRANCH_MIN_STAGE["story"]=1` / `["free"]=1` / `["scaffold"]=1` lied about the floor: the values said "this branch type works at Stage 1" but Stage 1 no longer exists for any practical caller. All three bumped to 2; same-file docstrings on `create_scaffold_branch` and `create_free_branch` reworded from "stage < 1" to "below the plugin floor (stage < 2)" so a reader of `branching.py` sees consistent stage references throughout.

### Plugin-wide project-local-ID sweep + tripwire test

Constraint f7920cf86da0 says shipped plugin code stays project-generic — no `M-N` milestone IDs or `spike-N` references in `.md`/scripts that other projects would inherit. Sweep across `branching.py`, `scaffold_post.py`, `scaffold_cli.py`, `post_tool_use.py`, `event_schema.py`, and `xp-story-close/preload.sh` substitutes behavior-describing prose ("plugin floor", "scaffold-acceptance doctrine", "deterministic-event vocabulary") for the project-local artifacts that introduced each one. New `tests/integration/test_no_project_local_ids.py` walks the shipped surface with regex `\b(M-\d+|spike-\d+)\b` and fails loud with `file:line` offenders + the constraint event ID for context. `story-NNN`/`sprint-NNN` intentionally excluded — low-numbered forms are pedagogical examples in CLI help that distinguishing-by-regex would false-positive on; historical refs to specific sprints handled by manual sweep.

### `_log_hook_error` → `log_hook_error` (drop private prefix)

The function was prefixed with underscore (signaling "private to `_common.py`") but was already called from `branching.py` and tests. Concern 23b88f387da2 flagged the doctrine drift: cross-module use demands a public name. Eight call sites flipped (definition + 4 internal callers + 1 cross-module call + 2 tests). The cross-module call site keeps the module prefix `_common.log_hook_error(...)` so origin is explicit at the callsite. Pure rename — no behavior change. Same v3.1.3 pattern applied to `_is_iso8601` → `is_iso8601` in `smm_schema.py` (story-003 needed cross-module use).

### `xp-kickoff` Step 2.4 sticky dismissal

The Step 2.4 Stage 2 floor migration prompt was re-firing every kickoff for explicit Stage 0 projects with no way to dismiss. New `branching_strategy.stage_prompt_dismissed_at` schema field stores a UTC ISO timestamp; when set, Step 2.4 skips the prompt with a brief note that includes the timestamp AND the re-opt-in command (so users can undo without grep'ing the SKILL). Migration path explicitly does NOT record dismissal — migrate is the non-dismissed branch. Schema validates: optional, accepts `null` (encodes "never dismissed"), rejects non-string + over-budget + non-ISO-format strings. Implementation rides on two new CLI verbs `system_context_cli.py edit-branching-field <name>` / `get-branching-field <name>` that mirror the existing `edit-stack-field` / `get-stack-field` pair (same load → mutate → schema-validated save semantics).

### `metadata.resolves` schema validation

Decision 311a2af6fce7 (sprint-058) emitted `metadata.resolves='1c07b15d3326'` (string scalar) instead of `['1c07b15d3326']` (list). `resolution.py:128` then iterated the string char-by-char, found nothing, and STRONG resolution silently failed — the stale-question concern detector then correctly flagged the question as unanswered. The cascade-didn't-fire framing was a red herring; the upstream gap was schema validation. New validator at `event_schema.py:validate_event` rejects scalars, non-list types, non-string elements, and malformed IDs at write time. Eight schema tests cover the matrix; one e2e test in `tests/engine/test_resolutions.py` writes a blocking question + decision-with-list-resolves and asserts the question lands in `answered_question_ids` AND `concerns.detect_conflicts` emits zero stale-question flags — pins the original bug surface end-to-end. Defensive read-side wrap in `resolution.py` deliberately dropped from scope per audit (only 1 historical scalar exists; manual one-off fix to that record is the simpler path).

### `retrospective.py:139` `events=` wiring

Story-004 of sprint-058 added the `high_zero_decision_rate` signal in `retro_flags.py:215`, gated on `events is not None`. `retrospective.py:139` then called `evaluate_flags` without `events=` — the gate was never satisfied, the flag silently never fired in production. Three separate reviewers logged the gap (3e5f9cc3172e, d52ae1fb10c8, e3475d0fd5f1) but the wire-up itself deferred to this sprint. One-line fix adds `events=events,` to the call. Per decision 3aebbd3df455, SessionStart retro passes the full events list (multi-sprint cumulative view). Two tests pin the threshold behavior: positive (4/5 = 80% explicit_zero → flag fires) and regression-guard (1/4 = 25% → silent).

### `xp-kickoff` Step 2.5 prose: stage >= 2 (plugin floor)

Sprint-close-reviewer caught that `SKILL.md:86` still gated free-branch auto-create on `stage >= 1` while story-001 raised `BRANCH_MIN_STAGE["free"]` to 2. Functionally equivalent today (auto-promote always upgrades 1 → 2 before branching code reads stage), but the prose lied about the floor — same coherence-drift charge story-001 fixed in code. Updated to `stage >= 2` with an inline note that Stage 1 auto-promotes inside `branching.py stage`. Same factual behavior, prose now matches the plugin-floor narrative.

## v3.1.2 — close-skill safety + process polish (M-3 + M-5)

Sprint-058 ships eight parallel-dispatched stories: M-3 closes the close-skill safety holes (Step 4.5 coverage edge + Step 6 e2e), M-5 ships four process-polish improvements, plus two adopted items (probe-divert fix + preload path-space contract). All stories landed via teammate worktrees with the new `ACCEPT_ACTIVE` marker and implicit teammate-cwd discovery from v3.1.1 holding stable across the whole sprint.

### `/xp-story-close` Step 1b: surface file_domain drift at commit time

New `sprint_cli.py validate-domain <story-id> --base <TARGET_BRANCH>` subcommand diffs a story's actual git changes against the declared `file_domain` set. `/xp-story-close` invokes it as Step 1b before the close-reviewer fork. Drift records a `concern` event (severity=medium, `metadata.kind=file_domain_drift`) and continues — the retro is the right place to surface drift trends, not per-story interruption. This catches in-domain courage moves (small quality fixes outside strict scope) and surfaces them as audit signal without bottlenecking the close cycle.

### `/xp-story-close` Step 4.5 conditional security review

Story-close historically skipped Step 4.5 with a blanket exclusion, relying on sprint-close's cumulative `/security-review` to cover each merged story. That assumption fails when no sprint envelope wraps the close — orphan story branches and free-mode-style story-close on tip got only Tier-1 commit-time coverage. Step 4.5 now fires from story-close when `sprint_cli.py exists` returns false OR `branching.py list-story-orphans` includes `<CURRENT_BRANCH>`. Gate uses an `echo "STEP_4_5: APPLIES (...)"` / `echo "STEP_4_5: SKIP (...)"` literal-stdout protocol so the LLM can match verbatim across tool-call boundaries (a bash variable would be unreadable across steps).

### Step 6 abort-default e2e + shared close-cycle test fixtures

`tests/integration/test_close_preloads_emit_shared.py` gains an end-to-end test that writes real xp-close-reviewer Block + Step 4.5 security concerns via `append.sh` (no mocks) and asserts `count-concerns --severity high --cycle-id X` returns the expected count under cross-cycle isolation. The metadata-shape helpers (`_quality_meta`, `_security_meta`, `_record_quality_block`, `_record_security_block`) are extracted from per-file definitions to `tests/_close_fixtures.py` — single source of truth for the close-reviewer metadata contract.

### `retro_flags` high-zero-decision-rate signal

`evaluate_flags()` gains an optional `events=` parameter and a new `high_zero_decision_rate` Honesty-lens signal that fires when the rate of decision events with `metadata.action="explicit_zero"` exceeds 50% across a window. Surfaces "we keep declining to record decisions" as a flag once `/xp-accept`'s decision-nudge starts producing explicit_zero events at scale. Wiring at `retrospective.py:139` deferred to a follow-up; window-semantics spec recorded as a decision event.

### `smm_cli question close --won-fix` subcommand

Aging questions accumulate across sessions when there's no terminal disposition for "close as won't-fix" — only an answer event resolves them. New subcommand emits a status event with `metadata.action='question_close'`, `metadata.disposition='wont_fix'`, `metadata.resolves=[Q]`. Mirrors the triage disposition shape from `work_selection_decide.py`; `resolution.py` already routes any `metadata.resolves` on a question to `question_answers` regardless of resolver event type. Idempotent on already-resolved questions; rejects non-question event-ids fast. Future-proof dispatch via `question_action` subparser so a future `question reopen` won't silently route to close.

### `/xp-work-selection` FORCE-CLOSE gate on Try adoption

A plain `defer` is now refused once the same Try has been deferred 3+ times — carrying it further is dishonest (per wisdom item 97efcb0d53f6, the META-Try that landed after 5 retros). Caller must escape with `--force-adopt <topic>`, `--force-drop`, or `--force-defer-with-date <YYYY-MM-DD>`. Force flags are mutually exclusive at the argparse level. `--force-defer-with-date` validates ISO format AND requires the date >= today (past dates would silently launder the Try past the gate).

### `resolves_probe` in-sprint sibling axis

`_score_candidate` gains a 5th axis `SELECTION_REASON_IN_SPRINT_BATCH`. Closes the probe-divert gap from sprint-057: when xp-close-reviewer files a batch of N concerns sharing `close_cycle_id`, agents picked sibling concerns the existing 4-axis selector missed because they had no file_overlap or keyword tie to the fix commit. The new axis is purely additive — same ranking math, +1 score and a 5th reason whenever a candidate's `metadata.close_cycle_id` matches the active cycle. Active cycle is the `close_cycle_id` of the newest concern within `_RECENCY_DAYS` carrying the metadata key. Newest-wins tie-break under concurrent teammate cycles is documented as a known non-determinism (probe candidates are a hint, not a contract); future scoping path via `metadata.source_branch` is named in the docstring. `find_probe_candidates` no longer early-returns on empty `commit_files` — empty-stage commits with an active cycle still surface siblings.

### `branching_cli` tab-delimited teammate-discovery emit

`list-teammate-worktree-paths` and `find-closing-teammate-worktree` now emit tab-separated fields. Removes implicit dependency on the "git refs cannot contain spaces" invariant that prior bash consumers were leaning on, and unblocks the LLM-side parse in `xp-accept/SKILL.md` (which would have split a spaced path wrong under the old space-delimited form). Both `xp-story-close/scripts/preload.sh` and `xp-accept/scripts/preload.sh` parse the new format. Honest framing: the original bash split happened to work because git refs reject spaces; the load-bearing fragility was the LLM-facing prose, not the bash. Tab-delimit ships either way for self-documenting clarity.

### Mid-sprint courage: 6 fix-cycles inline

The close-reviewer raised 16 concerns across 8 stories during the close cycle; 5 BLOCKs/concerns were addressed inline before merge rather than deferred:
- story-001: Step 4.5 conditional invocation wired into xp-story-close
- story-005: future-proof question subparser dispatch
- story-006: list all gated refs in FORCE-CLOSE message + reject past `--force-defer-with-date` dates
- story-007: drop early-return on empty `commit_files` so in-sprint axis surfaces siblings on amend-no-files commits
- sprint-close fixes: validate-domain wired into xp-story-close Step 1b (closes BLOCK b6c1eeac62c1: story-003 commit-message claimed a caller that didn't exist), `METADATA_KEY_CLOSE_CYCLE_ID` substituted in smm_cli, Step 4.5 gate uses literal-match stdout protocol

## v3.1.1 — teammate-workflow correctness gaps closed (M-2)

Sprint-057 / M-2 closes the two teammate-workflow correctness gaps surfaced by sprint-056. Three stories merged into the sprint branch; the capstone E2E uncovered + fixed three additional production bugs in flight.

### ACCEPT_ACTIVE cleanup symmetry across all four close skills + xp-kickoff

The `ACCEPT_ACTIVE` marker is now consumed by `/xp-plan-close`, `/xp-free-close`, and `/xp-story-close` preloads on entry — not just `/xp-sprint-close`. New `clear_accept_active_marker()` helper in `_preload_base.sh` is the single source of truth across all five callsites (the four close skills + the new defensive cleanup in `xp-kickoff/scripts/check_session_needs.sh`). Kickoff's cleanup is gated on `in_progress_count==0` so an active acceptance session resumed mid-flight is never clobbered. Closes the cross-session strand hazard where the marker silently persisted across sessions when an alternate close path fired (or when the user crashed/quit before `/xp-sprint-close`).

### `/xp-story-close` discovers teammate worktree implicitly

When `/xp-accept` dispatches `/xp-story-close` for a teammate story, the orchestrator sits on the SPRINT branch — not the story branch. The preload now pairs live teammate worktrees against `sprint.json` status (the `done`-status story whose live worktree still exists) and emits `TEAMMATE_CWD` + overrides `CURRENT_BRANCH` from the worktree's HEAD. No new marker, no `/xp-accept` context-passing — fully implicit derivation. New `worktree.find_closing_teammate_worktree(smm_dir, cwd)` helper + `branching.py find-closing-teammate-worktree` CLI subcommand. `_iter_live_teammate_worktrees` now yields `(path, branch)` tuples — branch read from porcelain instead of N extra `git -C rev-parse` spawns per dispatch. Multi-match raises `ValueError` (broken `/xp-accept` iteration); the preload propagates it (`set -euo pipefail`, no `2>/dev/null || echo ""` swallow). Steps 1/2/3 of `/xp-story-close` route `close_common.py` at `${TEAMMATE_CWD:-.}` for preflight, push, and PR creation.

### Three production bugs fixed by the capstone E2E

The story-003 capstone test (a 7-phase E2E walking the full M-2 lifecycle with real git, real merge, real cleanup) caught three bugs that the per-story unit tests missed:

1. **Step 7 routing**: story-002 originally routed merge at `TEAMMATE_CWD`, but `git merge` checks out the target branch which is held by the orchestrator's worktree → fails with `'<target>' is already used by worktree`. Step 7 reverted to `--cwd .` (orchestrator cwd); merge correctness restored. Steps 1/2/3 still use `TEAMMATE_CWD` (no checkout, branch-local operations).
2. **`close_common.py` skip-delete**: `cmd_merge` aborted the chain on delete-source failure. For teammate stories, the source branch is held by the teammate worktree → delete fails → chain aborts → Step 7b cleanup never ran → orphan worktree + branch in production. Fixed: skip delete + return 0 when `worktree.branch_held_by_worktree` is True. `cleanup_teammate.py` (Step 7b) now owns deletion via worktree removal.
3. **`worktree.remove_worktree` HEAD-derivation**: deleted by worktree dir name (`worktree-story-001`), but production branch is `<user>/story-001-<slug>` → orphan branch leak after every teammate cleanup. Fixed: derive actual branch from worktree HEAD via `identity.get_current_branch(wt_path)` before removal; falls back to dir name on detached HEAD or rev-parse failure (preserves legacy test contract).

### New helpers + shared test fixtures

`worktree.branch_held_by_worktree(cwd, branch)` parses `git worktree list --porcelain` for any worktree holding the given branch (substring-match defense via exact line equality). Shared `_branching_fixtures.get_current_branch_at()` and `seed_sprint_with_stories()` test helpers eliminate three near-identical inline helpers across `test_worktree.py`, `test_branching_cli_detection.py`, `test_story_close.py`, and `test_multi_story_accept_flow.py`.

## v3.1.0 — security review migration to close skills

Sprint-055 / M-8 ships the security review architecture migration. `/security-review` now fires from main-agent context inside each close skill, not from the misfiring subagent context where the PostToolUse:Skill hook didn't reliably emit `SECURITY_COMPLETE`. Six stories merged into the sprint branch.

### Migrated: `/security-review` now lives at close-skill Step 4.5

The shared close-pipeline reference (`scripts/_close_pipeline_shared.md`) gains a new **Step 4.5: Security Review** block applied by `/xp-{free,sprint,plan}-close` (story-close skips — sprint-close's cumulative diff already covers each story). Each close skill invokes `/security-review` against the cumulative close diff, parses the prose, and files Block findings as `severity=high` concerns and Concern findings as `severity=medium` — both with `metadata.kind=security`, `metadata.close_cycle_id`, and `metadata.close_mode`. The Skill tool runs in main-agent context, so `PostToolUse:Skill` fires correctly and emits `SECURITY_COMPLETE`.

### Deleted: Tier 2 (xp-accept Step 1c) and Tier 3 (xp-close-reviewer Step 3.5)

The xp-accept Step 1c and xp-close-reviewer Step 3.5 paths are removed entirely. `/xp-accept` no longer runs `/security-review` per story (cumulative coverage shifts to the next `/xp-sprint-close`). xp-close-reviewer is now quality-only across all modes — `Skill` dropped from its frontmatter tools list and no Skill invocations remain in the body. `Skill` also dropped from `xp-accept` frontmatter (no Skill invocations remain there either). v3.0.1 + v3.0.2 deterministic Tier-1 patterns at commit time are retained as defense-in-depth.

### Step 6 abort-default uses deterministic event count

The shared Step 6 abort-default flag now derives from `smm_cli.py count-concerns --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>` (new subcommand). Both quality blocks (from xp-close-reviewer) and security blocks (from each close skill's Step 4.5) land at `severity=high`, so a single deterministic count covers both. The prior text-keyword prose-match check is dropped per the canonical-event constraint. `--severity` is constrained by `argparse choices=sorted(VALID_SEVERITIES)` so a typo (e.g. `--severity High`) errors up-front instead of returning a silent zero — a silent zero on a security gate would default the merge confirmation away from "Abort" exactly when it shouldn't. `CLOSE_START_TS` now emitted by all four close-skill preloads (was only in story+free).

### Doctrine sweep

Stale "Tier 2 fires at /xp-accept" / "Tier 3 at close-reviewer" references swept across `PROCESS_GUIDE.md`, `TEAMMATE_GUIDE.md`, `agents/xp-retrospective.md`, `smm/seed_smm.py` (wisdom seed), `scripts/review_cycle_done.py` (`_SECURITY_CONTINUATION_NUDGE` text + comment), `scripts/pre_tool_bash.py` (comment), `skills/xp-story-close/SKILL.md` (security-exclusion addendum reframed away from Step 3.5), and several test docstrings. Reviewer-prompt prose for `/xp-plan-close` lost the obsolete "security posture" focus bullet (it was telling the reviewer to do work the reviewer didn't actually do).

### Schema is additive

New `metadata.kind="security"` on close-skill security concerns and the new `smm_cli count-concerns` subcommand are additive — no event-schema break. Negative-pin tests (`TestAcceptHasNoTier2` in `test_accept_lifecycle.py`, `TestCloseReviewerHasNoTier3` in `test_xp_close_reviewer.py`) pin the migrated prose absent so it cannot silently re-emerge. The reviewer-prompt scope detection in `_close_fixtures.py` uses paren-depth walking (not naive `find(")")`) so a security leak in the Instructions block can't slip past the close-reviewer-prompt-clean test.

## v3.0.3 — Stage 2 floor + reviewing lifecycle + teammate cwd-drift fix

Sprint-054 / M-7 ships ahead of M-8's v3.1.0 because its content delivers user-facing value independently. Nine stories merged into the sprint branch, plus one chore courage-fix that resolved a silent-failure inversion the close-reviewer caught mid-sprint.

### Stage 2 is the new plugin floor

Branching doctrine restructured around two supported tiers (Stage 2 enforced, Stage 3 optional) with Stages 0/1 reframed as legacy/migration. Existing Stage 1 projects auto-promote transparently the next time `branching.py` resolves the project's stage — `_maybe_auto_promote` mutates `system_context.json` in place, emits a one-time decision event, and returns the new stage. Stage 0 declarations get a kickoff-time migration prompt (Step 2.4) before sprint setup. Free sessions remain available at every stage as the low-ceremony escape hatch.

### `reviewing` story status closes the .accept marker re-arm gap (single-story sprints)

The story lifecycle gains a fifth state: `ready → scheduled → in-progress → reviewing → done/deferred`. xp-accept's per-story Step 1.0 promotes the story to `reviewing` before running its acceptance command; AC-fail-debug reverts to `in-progress`. This carves the reviewed story out of `has_in_progress_stories`, so `pre_tool_write` no longer re-arms the `.accept` marker on fix-cycle Edits in single-story sprints. Multi-in-progress sprints still re-arm because OTHER stories trigger the gate — that follow-up is filed for the next release (ACCEPT_ACTIVE marker pattern).

### Teammate cwd-drift fix

Sprint-054 dogfooding hit the same bug three times: lead-written prompts hardcoded absolute paths starting with the main-repo root, and teammates followed those paths into the wrong tree before self-recovering. `spawn_teammate.py` now prepends a worktree-context preamble to every teammate's stdin naming the worktree absolute path explicitly and instructing path re-rooting. Companion fix in `xp-accept` SKILL.md: worktree-acceptance commands wrap in a subshell `(cd <abs-path> && <command>)` so the parent shell's cwd never persists into subsequent Bash calls.

### TaskCreate nudge moves to /xp-assign with mode-aware text

The post-skill TaskCreate nudge previously fired after `/xp-review-plan`, but mode (solo vs teammates) isn't decided yet at plan-review time. Moved to `/xp-assign` with text that addresses both shapes: solo gets per-step tasks, teammate mode gets coordination tasks for waiting + accept + close per story. Adds `STATUS_ACTION_ASSIGN_COMPLETE` canonical event.

### TEAMMATE_GUIDE asymmetric file-domain rule

Reviewer-suggested cross-domain edits are now KEPT by default if they're small in-domain quality improvements (raise concern only when large or off-topic). Teammate-initiated cross-domain work still requires raising a concern. Distinguishes mechanical-collision risk from accountability-loop value.

### Schema courage fix

`_maybe_auto_promote`'s exception handling narrowed from `(OSError, ValueError)` to `OSError` only. Schema-validation ValueErrors now propagate loud — they signal corrupt input or a code bug, both of which deserve to crash rather than silently mask the contract. Test fixture (`_branching_fixtures.write_system_context`) rewritten to write a fully-valid doc via the canonical `valid_doc` helper. Two obsolete "skips at stage 1" tests deleted; six tests migrated to `stage=2` (the new floor).

## v3.0.2 — extend /security-review continuation nudge to Tier 3 close-reviewer

v3.0.1 shipped the `additionalContext` continuation nudge but landed it behind a recursion-prevention skip in `review_cycle_done.py` that returns early for any caller whose `agent_type` starts with `xp-`. The Tier 3 close-reviewer (`xp-close-reviewer`) is exactly that — an xp-* subagent invoking `/security-review` from `/xp-free-close`, `/xp-sprint-close`, and `/xp-plan-close`. The skip suppressed the nudge AND the canonical `STATUS_ACTION_SECURITY_COMPLETE` event for every Tier 3 close, observed empirically when the v3.0.1 release's own free-close stopped after the security report instead of producing the close-reviewer's mode-aware Keep/Concern/Block summary. v3.0.2 carves out `/security-review` as the one exception to the recursion-prevention skip: target detection now runs first, then the skip applies only to non-security-review targets. The other four targets (`/simplify`, `/xp-quality-review`, `/xp-review-plan`, `xp-housekeeper`) keep the existing xp-* skip — they have per-commit flag side-effects or lifecycle counter implications that genuinely should not fire for subagent activity.

## v3.0.1 — Unblock orchestrated /security-review + record story design decisions

Two surgical fixes targeting wear in the v3.0 tiered-review workflow, both adopted from the sprint-053 retro.

### PostToolUse:Skill nudge unblocks orchestrated /security-review

The built-in `/security-review` skill ends its reply with a "report only" stop clause that is correct for direct user invocations but halts the Tier 2 (`/xp-accept`) and Tier 3 (close-skill) orchestrations mid-flight, forcing a manual re-prompt each time. `scripts/review_cycle_done.py` now appends an `additionalContext` advisory after `/security-review` runs, telling orchestrated callers to continue past the stop clause; direct invocations still see the stop because the calling agent decides whether the override applies.

### /xp-accept records design decisions per story

Four consecutive retros flagged "too few decisions recorded with significant work." `/xp-accept` now has an explicit Step 2b.i that fires before `/xp-story-close`: for each accepted story, record qualifying design decisions OR an explicit-zero status event ("no design decisions to record"). The criterion is intentionally demanding — architectural choices and contracts, not refactor sequences or lint-driven cleanups — and the explicit-zero path includes friction so retros can distinguish ran-and-found-none from skipped. Step 1c's Block-override path also gained a decision event alongside the existing severity-high concern: concern records the risk, decision records the architectural choice to ship despite the Block.

## v3.0.0 — Tiered security review (breaking)

The headline change of v3.0 is the migration from per-commit LLM security review to a three-tier model. The full design lives in `docs/ideas/security_review_doctrine.md` and shipped across sprint-048 → sprint-053; this entry summarizes what changed for users and which usage patterns are now broken.

### The three tiers

- **Tier 1 — deterministic regex at commit time.** A pattern set in `scripts/security_patterns.py` scans the staged diff before every commit and blocks on literal secrets (AWS access keys, GitHub tokens, PEM private-key headers, `password|passwd|pwd` literal assignments) and dangerous-call shapes (`subprocess.<call>(... shell=True ...)`, any `os.system(`, any `eval(`/`exec(`, and `http(s)://user:pass@` URLs). Per-line `# noqa: secret` suppression. Near-zero false-positive in this codebase's idiom; new test fixtures cover each pattern positive case + false-positive resistance. No LLM, no token cost — fires every commit.
- **Tier 2 — LLM `/security-review` at `/xp-accept`.** Before a story transitions from `in-progress` to `done`, the accept skill computes the cumulative story diff (story branch vs sprint base) and invokes the built-in `/security-review` against it. Block findings stop the transition; Concern findings file as SMM events. Free-mode skips Tier 2 (no story container) — Tier 3 covers it.
- **Tier 3 — LLM `/security-review` at close.** The `xp-close-reviewer` agent invokes `/security-review` against the cumulative close diff for sprint, plan, and free close modes. Findings fold into the existing Keep / Concern / Block summary; Block findings cause the merge confirmation to default to Abort. Story-mode close skips Tier 3 because Tier 2 already covered the same diff.

### Breaking changes

- **Review cycle is now `/simplify → /xp-quality-review → commit`.** The `/xp-security-triage` step is gone. The pre-tool gate no longer enforces `security_review_done` per commit; security review fires at story and close boundaries instead. Agents that scripted the old four-step cycle need to drop the `/xp-security-triage` call.
- **`/xp-security-triage` skill deleted.** For mid-flight security checks (e.g. ad-hoc review of a draft change), call `/security-review` directly — that's the built-in skill the wrapper used to invoke. The wrapper added no value once the per-commit gate was removed.
- **`xp-security-reviewer` agent deleted.** The forked subagent that backed `/xp-security-triage` is gone alongside its skill; nothing references it.
- **Internal markers + constants removed.** `SECURITY_TRIAGED` marker, `security_review_done` flag in `REVIEW_CYCLE`, `STATUS_ACTION_SECURITY_TRIAGE_*` constants, and `security.has_staged_code_files()` are all gone. `STATUS_ACTION_SECURITY_COMPLETE` stays — Tier 2/3 still emit it. The retro now tracks tier coverage instead of per-commit adherence (count of `security_complete` events per story-window / close-window).

The migration was hard-cutover at v3.0 by design: M-1 through M-3 added the tiers additively (new and old coexisted across sprint-048 → sprint-050), M-4 flipped the switch (sprint-051), M-5 deleted dead code (sprint-052), and this M-6 release closes the migration. The long-running concern that "security triage was skipped on some commits" is resolved at the doctrine level — the tiered model removes the failure mode rather than adding more enforcement around it.

### Related fix in this release

Story-002 of sprint-053 repaired a silent post-commit hook bug that was invalidating `Resolves-Event:` auto-close discipline. The detector regex `\bgit\s+commit\b` only matched bare `git commit`; it missed `git -C <path> commit ...` (the form agents adopt to avoid cd-poisoning Stop hooks) and `git merge` (also commit-producing). When the hook never fired, four mechanisms went silent at once: review-cycle gate, branch protection, commit-event recording, and review-cycle marker reset. Confirmed via transcript inspection that 14 commits + 1 merge in a recent free session landed with zero corresponding events. Fix is a shared `GIT_PREFIX = r"\bgit(?:\s+-\S+(?:\s+\S+)?)*\s+"` regex covering all global option shapes (`-C`, `-c`, `--git-dir=`, `--work-tree=`, `--paginate`), plus `(?:commit|merge)\b(?!-)` to track merges and reject `commit-tree`/`merge-tree` plumbing false positives. Same `GIT_PREFIX` reused in `commits.py` for the parallel `git add` / `git commit -a` detection that had the identical bug. 13 new unit tests + 5 multi-commit integration tests including verbatim real-world fixtures from the failed session.

---

Earlier entries (pre-v3.0.0) are archived in [`changelog_pre_v3.md`](./changelog_pre_v3.md).

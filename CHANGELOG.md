# Changelog

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

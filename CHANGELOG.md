# Changelog

History prior to v4.0 lives in [`changelog_pre_v4.md`](changelog_pre_v4.md).

## v4.19.0 — The recorded branch namespace is now the one in force

**Minor, not patch: branch names can change on upgrade.** `branching_strategy.user_namespace`
was inert. `identity.user_namespace()` derived the branch prefix from the git
`user.email` local-part and never read the recorded field, so `system_context.json`
could say `alice` while every branch was cut as `a-smith/...` — with nothing
reporting the disagreement. This repo hit exactly that: the analyzer recorded the
prefix already on 200+ merged branches, the git email had since changed, and the
next branch was cut under the new one.

The recorded value now WINS, falling back to git identity when absent or unusable.
It is user-editable via `system_context_cli edit-branching-field`, so it was always
meant as an override; an override nothing reads is a lie.

**What changes for you on upgrade.** If your recorded `user_namespace` disagrees
with your git-derived slug, new branches switch to the recorded prefix — and your
EXISTING branches stop matching `list_user_branches`, which backs kickoff's
orphan-branch triage and free-close discovery. One-time, and visible: check
`branching_strategy.user_namespace` in your rendered system context before
upgrading, and either edit it to the prefix you actually use or delete the field to
keep deriving from git.

The field is also now validated as a git ref segment, at the same two points
`integration_branch` already was: rejected at write time (`user_namespace_error`),
healed to "no override" at use time (`healed_user_namespace`). It reaches `git
branch` and `git checkout` as argv, so a leading dash would have arrived as a FLAG.
Values already on disk are grandfathered per-field, so a load/mutate/save
round-trip of a config that predates the rule does not crash — and a grandfathered
`integration_branch` cannot smuggle a brand-new unusable `user_namespace` through
the same save.

`xp-system-analyzer`'s prompt now states the rule it was already following
(prefer the prefix in use on existing branches, else the git email local-part, one
segment) — prompt and behavior had drifted, which is how an unmatched value got
recorded in the first place. The rendered system context marks a stored namespace
that is not usable, the way it already marked `integration_branch`.

`system_context_schema.py` had reached 560 lines against a 500 cap; the
branching-strategy validators moved to `system_context_branching_validators.py`
and are re-exported by identity, leaving the schema at 371.

## v4.18.0 — Remove machinery that could not fire

**Minor, not patch: this removes shipped surface.** `scripts/backfill_story_id.py`
(an operator-invocable script, still named in `changelog_pre_v4.md`) and the
exported `event_schema.STATUS_ACTION_ITERATION_COMPLETE` constant are both gone.
Anything invoking the script, or importing that constant, breaks on upgrade —
which is a breaking change however small, and this project gives those a minor
bump.

`backfill_story_id.py` was a one-shot reconciler. Before Tier-0 attribution,
commit events could carry a missing or wrong `metadata.story_id`; v2.28.1 made
the `[story-NNN]` commit prefix authoritative for new commits, and this script
existed to retrofit the old ones. Measured across every project event log
available: of 1067 commit events, **0** still disagree with their prefix. The
migration is complete everywhere it could apply, and new commits cannot regress
into the old state. Removed, with its test — 268 lines.

It surfaced from an audit asking which shipped machinery has ever actually
executed: 14 of 35 `metadata.action` constants have never appeared in 5065 real
events. Most of that list is dormant *by design* rather than dead — retirement
paths that fire only when a cap binds, schema-migration insurance, and a
regression pin that names a deleted agent precisely to keep it deleted. This was
the only entry that was finished rather than waiting.

**Also removed: the `iteration_complete` event and its `iterations_completed`
metric.** The emission lived in `sprint_save.run()`, which its own docstring
scopes to *structural* mutations (`create`, `add-story`). An iteration actually
completes on `update-story`, which calls `store.update_story_status()` and never
enters that function — so the event could not fire when it claimed to, and its
only reachable path would have announced "Iteration complete" during sprint
*creation*. Zero firings in 5065 events across 11 projects, while
`retro_metrics` fed a permanent `0` into every retrospective input.

Its tests passed the whole time: they call `sprint_save.run()` directly, proving
the function works without proving anything about whether the trigger fires.

The **sprint-complete nudge** in the same block went with it, for the same
reason plus one more: it additionally required no ready or in-progress story,
which no freshly created sprint has, so it was unreachable twice over. The live
"Sprint complete — run /xp-sprint-review" prompt is the stop gate's. Only the
`.accept` unlink is kept, and only because it *is* reachable — as a fallback for
a marker that outlived both its normal clearers (xp-accept's preload and the
SessionStart sweep).


## v4.17.0 — Archive robustness, and diagnostics that tell the truth

**Milestone 5 plus four adopted backlog items.** Two threads run through this
release. The first is retry-safety around the destructive parts of a close: an
archive that overwrites, or a sprint-close that deletes before it archives,
loses work exactly when you most need it back. The second is a class of bug this
project keeps finding in its own gates — a diagnostic that reports something
subtly other than what happened, and so sends the next investigation somewhere
useful-looking and wrong. Two stories here were re-scoped mid-flight when
measurement falsified their opening premise, and one of those falsified premises
had already cost a session's worth of misdirected debugging.

**Behavior changes (read these):**

- **A failed teammate spawn now leaves its evidence on disk.** When the output
  filter ends with no result event, it writes the raw capture to
  `.teammate-stream-<name>.log` beside the teammate report (head and tail kept
  past a 500-line cap), names that path in the error, and says explicitly whether
  the stream hit EOF or the progress timeout. Previously those lines were
  captured, counted, and discarded.

- **The filter no longer claims unparsed output is stream-json.** Its no-result
  message reported the raw line count as "stream-json lines" whether or not
  anything parsed, and silently dropped any non-JSON line that did not match a
  known error signal. It now surfaces unrecognized lines (bounded, elided with a
  count) and reports the parsed count and the total separately. This is the fix
  for a real misdiagnosis: two spawn failures emitted seven lines of spawn-side
  output that were thrown away and reported as protocol output, sending the
  investigation at the pipe instead of the gap in the reporting.

- **A cut-short lint run is no longer reported as a hang.** When the shared
  commit-gate budget is partly spent, a linter killed at its narrowed slice said
  "timed out after Ns". It now reports the slice it got against its own ceiling
  and the shared budget remaining at the start, and says it may have been cut
  short rather than hung — while asserting nothing about which linter spent the
  clock, because the code cannot observe that. The block itself is unchanged and
  still fails closed.

- **The auto-merge gate stops counting other teammates' transient concerns.** A
  concurrent teammate's TDD red-step concern, carrying no close-cycle id, was
  counted against a sibling story's clean close and false-aborted it. Caught live
  during this sprint's own close.

- **`/xp-assign` refuses a stale plan path** rather than pairing the wrong plan
  with a story.

**Robustness:**

- Archiving is collision-safe through one shared `archive_json` helper, and
  sprint-close archives *before* the destructive delete, so a retried close no
  longer races its own cleanup.
- The cross-language leak test now detects hardcoded per-linter rule-code tables,
  not just file-extension predicates — the coverage half of the guardrail that
  previously only human review caught.
- The MAYBE-ADDRESSED annotation has a single formatter instead of divergent
  copies.

**Deferred:** one story was dropped after its debt was validated stale against
current code — the gate it described already reads correctly, and the proposed
fix would have reintroduced a misidentification the current design prevents.

## v4.16.0 — Gate-logic and honesty repairs, continued

**Milestone 7, finished.** Where v4.15.0 took M7's first pass, this closes the
remaining twelve gate-and-honesty holes — each one a place where a gate or a
rendered surface reported something subtly other than what the code did. Every
story here was measured before it was coded; three of the twelve reversed their
own opening premise once the measurement came in. Minor bump: several change
behavior you may depend on.

**Behavior changes (read these):**

- **The teammate stop gate honors the review cadence.** The third and last leg of
  a cadence contradiction the prior release fixed only in part. A dirty-tree
  teammate was told to run `/xp-quality-review` before stopping even under story
  cadence — where per-increment review is deferred to the merge and the session's
  own configuration says to skip it. The gate now branches: under story cadence it
  demands only the commit, with a message that never claims a review completed;
  under commit cadence its output is unchanged.
- **The retro batch-size flag measures one agent's own work.** It counted every
  agent's events in a single global stream, so during a parallel sprint its
  "commit more often" advice was unactionable — no one agent could move a number
  fed by a dozen others — and its label described something the counter never
  measured. It is now partitioned per agent, anchored at that agent's first edit,
  closed by its own commit, with pure tool-call telemetry excluded; the threshold
  is re-baselined from measured sessions (75 → 25) with its provenance recorded
  beside the constant, and the message is written from what the counter actually
  counts.
- **Stale kickoff triage items collapse to a one-line digest.** The work-selection
  block grew with every open item; deferred items now render as a single digest
  line carrying their id and defer count while everything else keeps its full
  excerpt. Nothing is dropped, nothing reads as closed, and full text stays
  retrievable by id — the block shrinks by item count, not by truncating the
  rationale you triage on.

**Honesty repairs:**

- **A commit whose message can't be parsed no longer vanishes.** `-F -` heredoc
  messages now survive a trailing redirect, pipe, or chained command after the
  delimiter, and a body line that merely begins with the delimiter word (two bash
  termination rules the old single regex got wrong — plain `<<` closes only at
  column 0, `<<-` on leading tabs). A real session had lost ten commit events and
  their resolution trailers this way. And when a message still cannot be parsed, a
  commit whose HEAD advanced past what's recorded now leaves a low trace stating
  exactly what was observed — HEAD points at an unrecorded commit — never that a
  commit "landed", since the same signal fires for a rejection atop untracked
  history.
- **Plan review demands real behavior, and runs once.** The reviewer now asks
  whether a change alters runtime behavior (a red test the change flips), not
  merely that it is wired in — the recurring inert-fix failure mode — and a
  blocking question routes forward (asked, answered into the plan, proceed) rather
  than re-triggering an unbounded re-review loop.
- **A removal must take its tests with it.** The code reviewer's removed-behavior
  angle now searches the project's tests for a deleted symbol's name, including in
  files the diff never touched — the gap the file-domain collision gate is blind to
  — and the forbidden-vocabulary scan its cross-language guard depends on is
  centralized so its "scan raw, never lowercase" contract has one owner.
- **The reviewer read-only guard points at the route it can take.** Measured over
  every retained review since the guard shipped, its only real refusals were
  reviewers restoring a file they had changed to prove a finding — for which the
  old message named the wrong actor. The refusal now names the self-restore route
  (the reviewer's own edit tools, no git subcommand); the allowlist is unchanged.
- **The close pipeline's full review carries its own cost bounds.** The shared
  Step 4b now states what drives the review's scale, that the level token is
  positional and must be recognised, and that the named workflow — not a
  hand-authored substitute — is what keeps the fan-out bounded.
- **The assign marker is story-scoped so it cannot resurrect**, and three copies of
  a marker-guarded identity check collapse onto one self-resolving helper. A
  measured legacy-config linter antidote replaces an unmeasured guess, or records
  the refusal when no binary is available to measure it.

## v4.15.0 — Gate-logic and honesty repairs

**Eleven gates that reported something other than what the code did.** Milestone 7
collected the concerns that resisted blind fan-out — each needed measurement or
design before code. Minor bump: three of these change behavior you may depend on.

**Behavior changes (read these):**

- **`/xp-assign` selects solo-first.** A mixed frontier — a teammate batch plus one
  pending solo story — used to strand the solo story entirely: `SOLO_TARGET` was
  zeroed by the batch's mere presence, and mode selection never read it anyway.
  Assign now targets the pending solo story and **drains** it before the batch
  resumes. That ordering is a safety requirement, not a preference: a teammate spawn
  checks out the base in the same checkout an in-place solo teammate is committing
  in. The known hole at >1 in-progress solo story is stated in the skill rather than
  papered over.
- **A `type: "manual"` acceptance block may no longer carry `command`/`commands`.**
  Observational prose in a `command` was shelled, exited 127, and read as a red
  test — poisoning a close gate until someone deleted the acceptance block to
  silence it. Prose now has exactly one home, `steps`. This retires the authoring
  half of the earlier "a manual command is runnable" rule; **run-time is unchanged**,
  so a block already on disk still runs, and a per-story exemption derived from disk
  keeps one stored block from refusing every later edit to that sprint.
- **The commit-review nudge respects the active cadence.** Under story cadence the
  gate said "review deferred to /xp-story-close" while the commit path demanded
  `/xp-quality-review` anyway. It is now silent, as is the post-green sibling that
  promised committing would "trigger /xp-quality-review" — a trigger that does not
  fire under story cadence.

**Honesty repairs:**

- `branching_strategy.integration_branch` is checked as a git ref, so
  `get_primary_branch` no longer hands `-f` to `git checkout`. The check is git's own
  `check-ref-format` rule plus a leading-dash refusal (an argv hazard git has no
  opinion about) — **not** a naming pattern: `main+dev`, `trunk@2`, `feat(ui)` and
  non-ASCII names like `développement` are legal branches and are accepted. Loaders
  **preserve** a stored nonconforming value; the heal applies where the value is used,
  so a stage-1 auto-promote round-trip can never rewrite your configured branch name.
- A reviewer subagent can no longer mutate the shared index — the guard is scoped to
  the reviewing agents and destructive commands only.
- A captured runner's exit no longer clears a red test-failure gate: a compound
  command that pipes or substitutes the runner's output proves nothing about the
  suite, and is no longer treated as a green run.
- Orphan story-branch deletion resolves the **sprint** base rather than main, so a
  branch merged into an open sprint is deletable via the documented path.
- Plan re-review survives the blocking protocol. The marker is still consumed on the
  first pass; the re-review a blocking finding demands now resolves the plan through
  the recorded last-plan pointer instead, so it no longer dead-ends on "no plan
  marker".
- Teammate spawn recovers when the main checkout holds the target branch. Branch
  creation leaves the checkout on the new branch, so the following `git worktree add`
  failed 128 and the spawn died before the agent started; the only guard was an
  easily-dropped second checkout in the assign step.
- Sprint-planning prose states the exemption the collision check actually
  implements: a claim held by a **done or deferred** story never collides, so
  re-touching its file needs no dependency edge — planners no longer have to invent
  one.
- Shipped guidance names the **Workflow** tool for `/code-review` consistently, and
  the courage nudge no longer implies it runs per commit.

**Internal:** `_preload_base.sh`, `sprint_store.py`, `spawn_teammate.py` and
`system_context_schema.py` all crossed or approached the 500-line cap and were split
along cohesive seams (`_preload_emit.sh`, `_manual_shape_exemption.py`,
`sprint_capstone.py`, `spawn_args.py`), each an identity re-export with the existing
tests unchanged as the proof. Full suite green (7326 passed).

Close-cycle review of this branch found and fixed five further defects before release:
a newline chain bypassing the reviewer git-mutation guard, a trailing newline making
a green suite stop clearing the test-failure gate, a `KeyError` that took down the
`PreToolUse:Bash` hook, an unfilled capstone reporting green, and the ref check above
rejecting legal branch names.

## v4.14.6 — Hotfix: close Step 4b runs /code-review via the Workflow tool

**Every sprint/plan/free-close was breaking at Step 4b.** `/code-review` can no
longer be launched via the Skill tool (`disable-model-invocation`) — it runs via
the **Workflow tool** (async). The shared close pipeline said
`Skill(skill: "code-review")`, which now hard-errors for all plugin users. Fixed
the whole Step 4b flow at once (three coupled issues, one code region):

- **Skill → Workflow.** Step 4b now launches
  `Workflow({name: "code-review", args: "high <TARGET>...HEAD"})` and waits for its
  task-notification findings.
- **Arm the review-cycle marker.** A Workflow completion does not fire the
  `PostToolUse:Skill|Agent` review-cycle hook, so `simplify_done` was never set —
  the close Stop gate never deferred during the async window (spamming
  "mid-flight") and `xp-quality-review` never entered `consume-findings` mode. Step
  4b now arms the marker up front via the new `review_flag_cli.py`, keyed on the
  cwd-resolved agent_id the readers already use.
- **Order the close-reviewer after fixes.** The close-reviewer (Step 4.5) now runs
  only after the workflow findings are consumed and fixed, so it reviews the
  post-fix diff.

The close-cycle Stop gate's guidance text now names the Workflow tool; its defer
logic already anticipated the async flow and needed no change. `xp-quality-review`
reads consume-findings from the Workflow task-notification result. Full suite green
(7134 passed).

## v4.14.5 — Milestone 3 complete: 500-line cap paydown

**The entire Python census is now under the 500-line file cap.** Sprint-124
finished Milestone 3 with four behavior-preserving pure-move stories, fanned out
per file across sonnet subagents. No user-facing behavior change — every split
flows imports downward and re-exports by identity, so unchanged tests are the
verification (full suite green, 7131 passed, throughout).

- **story-001 — production + shared fixtures (blast radius):** `branching.py`
  (508→367, primitives to `branching_core.py`), `branching_cli.py` (506→441,
  worktree subcommands out), `linters.py` (502→167, data tables + cross-language
  guardrail comments to `linter_tables.py`), and the `_close_fixtures.py` test
  fixture (778→480). Mocks retargeted by call graph.
- **story-002 — mega test files (820+):** the 10 largest test files
  (`test_lint.py` 1805, `test_work_selection_decide.py` 1740, …) split by
  thing-tested into same-directory siblings.
- **story-003 — 600-785 band + collision families:** 21 files including the
  branching / system_context / common families, each split by a single subagent
  so a split can never regenerate an existing sibling's name.
- **story-004 — test tail (500-599):** the final 13 barely-over files.

Every split keeps tests `unittest discover`-importable (CI runs unittest); shared
cross-sibling helpers live in non-`test_`-prefixed modules so pytest never
double-collects them. Test-method multiset verified identical before/after on
every story (zero tests lost).

## v4.14.4 — Clean-fan-out debt fixes

**Closing the debt-pool loop.** Mirroring the concern sweep: after assessing the
open debts (a subagent fan-out re-judged each against current code — ~46% were
stale/accepted, the rest routed to a milestone), the four cleanly-mechanical ones
landed here. Each TDD red→green, full suite green (7129 passed).

- **Rename-away branch-absence hole:** the story-branch delete gate now also
  refuses the literal `git branch -m/-M/--move <story-branch> <new>` rename,
  which makes the branch vanish just as a delete does, breaking the same
  "absence implies merged" invariant `story_done_gate` relies on. Delete and
  rename detection now share a single command-tokenization pass. The
  current-branch shorthand (`git branch -m <new>`, no source arg) is a
  documented, accepted gap: its target depends on live HEAD, which a
  PreToolUse gate resolves *before* the command runs, so a chained
  `checkout <story> && branch -m` could defeat it — the gate's "catch the
  literal case, no-op on anything ambiguous" doctrine no-ops on it rather than
  offering false assurance. Delete behavior is byte-identical.
- **Dead-code removal:** the unused `is_file_scoped()` wrapper and its re-export
  are gone; its test assertions migrated to the equivalent over `degrade_reason`.
- **Facade discipline:** `pre_tool_skill` now reads sprint state through the
  `sprint_state` facade like the rest of the scripts layer, instead of importing
  from `smm/` directly — with fail-closed-on-corrupt behavior preserved (the
  facade chain re-raises rather than normalizing a corrupt sprint to "no sprint").
- **Test-helper consolidation:** the duplicated git-worktree test helpers are
  promoted into shared `tests/_repo_bases.py`.

## v4.14.3 — Clean-fan-out concern fixes

**Closing the concern-pool loop.** After assessing the remaining open concerns
(a subagent fan-out verified each against current code — most stale, a few
genuinely mechanical, the rest deferred to a new milestone), these landed. Each
TDD red→green, full suite green. (A fourth candidate — the exit-code-gating
hole — was attempted but the whole-range review found its fix reintroduced a
gate deadlock; it's deferred to the gate-hardening milestone, where the correct
fix must distinguish output *capture* from a merely-compound command.)

- **Whole-project linters:** `detekt`, `credo`, and `dotnet-format` join `clippy`
  in `NO_PER_FILE_ARGV` — they lint the whole project, so appending a per-file
  path asked a question their CLI can't answer.
- **Lint-config drift guard:** a new test pins that `LINTER_CONFIGS`' flat-config
  filenames stay a subset of `CONFIG_STYLE_FLAGS` keys.
- **Reslice branch preservation:** `create_story_branch` now resumes the recorded
  branch (mirroring the sprint leg, via the shared `_verified_local`), so a
  reslice that retitles a scheduled story no longer strands an orphan branch —
  and the `create` CLI now reports such a resume as `resumed:`, not `created:`.

## v4.14.2 — Signal-from-noise: 13 low-severity concern fixes

**A backlog-hygiene sweep turned into real fixes.** After trimming the open-concern
pool, a fan-out of subagents independently re-judged the dropped low-severity
concerns against current code — ~45% were genuine signal, and the cheap ones got
fixed here (each TDD red→green, full suite green throughout).

Correctness:
- `tdd_check` now anchors an **in-place (solo) teammate** to its own TDD window
  via the env+marker leg — previously it fell through to the lead's window,
  reading the wrong red/green state.
- `migrate.py`/`repair.py` read `events.jsonl` under the same lock `compact`
  uses (were unlocked → possible torn-read miscounts).
- `event_schema` re-exports the 10 `STATUS_ACTION_RETIRE_*`/`EDIT_*` names that
  previously raised `ImportError` when imported from it.
- Milestone-level `acceptance_execution.pins` is now **rejected at schema**
  (story-scoped only) instead of silently no-op'ing.
- ~~`xp-assign` preload emits `SOLO_TARGET` even when a teammate batch is fully
  spawned~~ — **corrected in v4.15.0: this never shipped.** The change was
  reverted as inert before this release merged, so 4.14.2 did not contain it.
  v4.15.0 delivers the capability for real, with different semantics
  (solo-**first**, not batch-fully-spawned).
- The `WorktreeCreate` bootstrap now runs **only for teammate-named worktrees**,
  so an Explore/ad-hoc worktree no longer pays the (up to 600s) project bootstrap.
- `smm_count` excludes a corrupt log line from a scoped count only on positive
  evidence (an embedded timestamp older than the window); the fail-closed floor
  is preserved for genuinely unscopable corruption.

Speed & cleanup:
- The slowest test (`~10.2s`, ~78% of the suite's parallel wall-clock) now runs
  in `~1.4s` via a fail-safe `XP_LOCK_TIMEOUT_SECONDS` override for the gate
  subprocess — same assertions.
- Removed inert `test_run_complete` `cwd` metadata (no consumer), duplicate
  budget test classes, and a duplicate `branch_exists`; DRY'd subprocess
  timeout/env helpers into `_subprocess_env.py`.

## v4.14.1 — 500-line cap paydown: every over-cap production module split

**A behavior-preserving maintainability sprint.** All ten production modules that
had grown past the project's 500-line file cap were split into cohesive sibling
modules — no behavior change, verified by the unchanged test suite (7101 passing
throughout).

Each split lifts a cohesive group of definitions into a new sibling module and
re-exports it **by identity** (`parent.X IS child.X`), so every importer and
every `mock.patch("pkg.mod.X")` site keeps resolving unchanged — which is why the
existing tests are the verification and needed no edits.

- **scripts:** `worktree.py` → `worktree_discovery.py`; `spawn_teammate.py` →
  `spawn_command.py`; `pre_tool_bash.py` → `pre_tool_bash_branch_delete.py`;
  `scaffold_apply.py` → `scaffold_verify.py`; `concerns.py` → `concern_conflicts.py`;
  `lint_check.py` → `lint_runners.py`; `_common.py` → `hook_io.py`.
- **smm:** `sprint_cli.py` → `sprint_cli_query.py`; `event_schema.py` →
  `event_categories.py`; `_append_impl.py` → `_append_lock.py`.

Three mock-call-graph seams were handled explicitly so patched symbols keep
intercepting after the move: `_common` keeps `_MAX_STDIN_SIZE` with a call-time
lookup, `_append_impl` keeps `LOCK_TIMEOUT_SECONDS`/`flock_with_timeout`
co-located, and `lint_runners.run_ruff` resolves `run_linter` through
`lint_check`'s namespace.

## v4.14.0 — Teammate worktrees leave the repo; the auto-merge gate reads the log, not the room

**A deferred-backlog paydown centered on one structural fix and a family of honesty
repairs.** The headline: teammate worktrees no longer live inside your repository.

**Teammate worktrees move out of the repo.** They now live at
`${CLAUDE_PLUGIN_DATA}/{project-id}/worktrees/{name}` — a sibling of the SMM dir —
instead of `{git_root}/.claude/worktrees/`. A worktree inside the repo silently
resolves some Node modules by walking *up* the tree into the primary checkout's
`node_modules`, so a teammate could test against a dependency tree it never installed
(spike-014 measured this). Out of the repo, an un-provisioned module fails honestly with
`MODULE_NOT_FOUND`. Teammate detection is now location-independent (it keys on the
`worktree-story-` path segment, not the parent dir), so it keeps firing wherever the
worktree lives; `worktree_path` derives the new base from the resolved SMM dir with a
legacy in-repo fallback. Two latent bugs the move exposed were fixed in the same pass:
the teammate prompt's main-repo path derivation (a 3-level parent walk that broke once
worktrees left the repo) and the `cd <worktree> && git` advisory's location marker.

**Auto-merge condition 2 reads the event log deterministically.** The "no blocking
finding" gate that decides whether a close auto-merges was an LLM prose read over a
reviewer summary (spike-016). It is now a deterministic `count-concerns --severity high`
read over the close cycle, mirroring condition 1. For the per-story-cadence path, which
never produced a "Block" verdict, a blocking finding is now recorded as a tagged
high-severity concern so the gate is real there too. And `count-concerns` /
`count-classifications` now **fail closed** on an unparseable `events.jsonl` line — a
corrupt line can no longer silently lower the count and wave a merge through.

**Acceptance and gate honesty.** `verify_acceptance` skips deferred stories under
`--sprint` and gates manual acceptance on command *presence*, not `type` (021/023); the
accept preload shows each story's routing (automated/walkthrough), not the bare type.
**BREAKING (021):** a `type: manual` block's `command`/`commands` is now *run*, not treated
as prose. If you previously stashed human/agent narrative in `commands` (e.g.
`commands: ["go read the logs"]`), it will now be shelled and fail the acceptance gate —
move that prose into the new optional `steps: list[str]` field (a command-less manual block
reports N/A). Only genuinely runnable confirmations belong in `command`/`commands`.
`/xp-accept` reads the existing is-complete signal instead of inferring completeness from
a zero ready-frontier (022). The staged-lint gate reads the staged blob by an unambiguous
`:0:<path>` ref, closing a fail-open (007); the close-merge event re-parses the merged
range's `Resolves-Event:` trailers so teammate work links even when per-commit events
never landed (008). Preload budgets no longer depend on where the repo is checked out
(013). The milestone-status transition tolerates a deliberate cross-milestone sprint label
instead of recording a spurious parse concern every save; the worktree-bootstrap failure
message is caller-neutral now that the platform WorktreeCreate hook reaches it.

## v4.13.1 — Doc drift fix

Reworded the retrospective agent's "Stale-Flag Concerns" section, which still
described the SessionStart stale-flag sweep that v4.13.0 (story-015) deleted —
a shipped agent doc narrating a removed mechanism. It now states only the live,
declarative instruction (surface any `flagged_stale` concern in Fix; the WEAK
`references` cascade closes it when its root closes). Docs-only; no behavior
change.

## v4.13.0 — Gate honesty: the plugin stops crying wolf, and stops certifying nothing

**If a gate has ever told you something the code didn't support — a "test failure" reprinted
at every kickoff for a suite that's green, a deliberate red-green step flagged as a
regression, an acceptance check that exits 127 on prose it was handed — this release is that
family of bugs.** A gate everyone knows lies is a gate nobody reads; this closes eight of
them, most found by *using* the system on real projects.

**The kickoff banner stops reprinting resolved notes forever.** `prune_resolved` could only
see a carry_forward item's target while that target's own event was still in the live log;
once routine archiving removed it, the resolved note was immortal and reprinted every
session in every project. It now uses `closed_target_ids` (the union that reads raw
`metadata.resolves` claims), so an archived-but-resolved target finally prunes.

**A deliberate TDD red no longer counts as a regression.** The suppressor keyed on the last
*commit* being test-only — impossible under the mandated red→green→commit workflow, so it
never fired (measured: 0 of 59 tags). It now also consults the working tree: a test-only-dirty
tree is the red step, gated on the single wide `get_uncommitted_files` scan so an untracked
production file can't slip past and silence a real regression. `test_run_complete` now carries
`cwd` so a scoped run is distinguishable from a full suite.

**The acceptance gate stops inventing failures — and stops certifying commands that can never
run.** `verify_acceptance` rejected a `VERIFY_CMD_TIMEOUT_S` of 0/negative (which made every
command die "timed out after 0s" before running) and shelled a `type: manual` story's prose
straight to a shell (exit 127 → false FAIL that blocked closes). Manual stories now report
N/A, distinct from PASS/FAIL. Separately, sprint-start now authors each story's acceptance
command from the project's *declared* `stack.test_command` instead of inventing
`python3 -m pytest` — which was never importable here and left every gate inert.

**Staleness is now a render-time annotation, not a self-multiplying concern.** The stale-flag
emitter filed a *new* concern to say an existing one was old; the triage block already shows
each item's age at render time, so 90 of 101 open items were a concern plus a second saying
"that one is old." The emitter is deleted.

**The close merge survives a transient worktree-registry race instead of aborting on it.**
Under concurrent teammates, `git checkout <target>` can briefly misreport the orchestrator's
own branch as held elsewhere; the merge now retries that signature (bounded, alongside the
`index.lock` retry) and logs `git-retry:` so the flake stays *measurable*, not hidden.

**The TDD gate's session window is the reader's own, not the lead's.** Only the lead emits
`session_started`; a mid-sprint lead `/clear` used to reclassify a teammate's live red suite
as prior-session and un-gate it on a clean tree. A worktree teammate now scans its whole
session (it has no "prior session"), keyed cwd-only.

**Sprint numbering can no longer regress.** After sprint-close archived `sprint.json`,
`next_sprint_id` fell back to *counting* sprint-start events in a truncated log — emitting an
already-used id (git held sprint-120; the counter emitted sprint-002). It now takes the max
existing id + 1 across the live sprint, archives, and events.

## v4.12.0 — The lint gate stops lying about your files; mark-done honesty at engine altitude

**If the commit-lint gate has ever blocked you with an unresolved-import error against a
file that was provably clean, this is that bug.** The gate copied each staged file into a
temp subdir of its own directory before linting it — `pkg/app.ts` became
`pkg/tmpXXXX/app.ts` — which shifted every path-relative resolution down one level. `./util`
and `../lib/x` resolved to nothing. Worse, it was self-obscuring: the temp segment was
stripped from the linter's output and the directory deleted, so you saw a finding against a
real path, naming a module that visibly exists, with no trace of the cause. One user's agent
burned ~131 turns on it; one of their test files became un-editable by anyone, and the
workaround they adopted widened two real safety guards.

**The gate no longer copies a staged file anywhere.** When the index matches the working
tree — ~99% of commits — it lints the real paths, still batched as one linter process for N
files. When a file genuinely diverges (partial `git add -p`, edit-after-add) it pipes
`git show :<path>` to the linter's own stdin mode, so the linter reads the *staged* bytes
while resolving as if at the real path. Both properties at once, which is what the temp copy
was trying and failing to achieve. Covered for ruff, eslint, prettier, flake8, rubocop and
clang-format — each argv verified against the real binary.

**A linter with no stdin mode blocks rather than waving the commit through.** For
`golangci-lint`, `clang-tidy`, `dart-analyze`, `swiftlint` and `php-cs-fixer` there is
nowhere to put a divergent file's staged bytes that does not move the file, so the gate says
so and refuses — naming the remedy, which is to `git add` the path (or unstage it) so the
index and working tree agree. This is one command, and for the case that produces the state
it is what you meant to do anyway; that is the line against a project-scoped linter like
clippy, which stays an *advisory* precisely because a whole-crate failure is genuinely not
something your staged diff can fix. It only ever fires for a file that diverges — an
ordinary Go or Swift commit is unaffected.

**Non-ASCII filenames are linted at all.** git C-quotes paths with non-ASCII bytes in its
default listings, so `café.js` arrived as the literal string `"caf\303\251.js"` — which
resolved to no blob in the index, dropped out of the gate's file groups, and committed
unlinted. Silently, because "absent from the index" is also how a legitimate staged deletion
reads. Every path listing is now read with `-z`, which also keeps a filename containing a
space in one piece.

Divergence is detected via `git` itself (so your repo's clean/smudge and eol filters are
applied, not second-guessed), and `git ls-files -v` covers the two bits — `assume-unchanged`
and `skip-worktree` — that would otherwise tell `git diff` to stop looking at a file and
report nothing about one whose staged bytes genuinely differ.

This also closes a fail-open the old design existed to fix — staging a violation and then
fixing it on disk without re-staging still blocks, because that case *is* divergence and
routes to stdin. 120 lines of materialization machinery are gone, along with the
`precondition_paths` indirection it forced, a `_cleanup_temps` that would `rmtree` a real
source directory if handed one, and a `_relabel_temps` doing blind global string surgery on
linter output.

**Ignored files stop blocking — on flat config.** Now that files are judged at their real
path, a project's eslint ignore pattern actually matches, and `--max-warnings=0` turns that
ignore *warning* into a blocking error. `--no-warn-ignored` suppresses it, and is keyed on
the config **filename** rather than the linter name: the flag is flat-config only, so keying
it on the name would have made every `.eslintrc` project exit 2 on every commit.

**Known gap:** eslint's flag has no `.eslintrc` equivalent, so a legacy-config project with
a *path-keyed* ignore pattern (one that did not match the old temp path but does match the
real one) can now see a block it could not before. Glob-keyed ignores (`**/*.test.ts`)
matched the temp path too and are unaffected. If this hits you, the workaround is to move
the pattern into `eslint.config.js`, or drop `--max-warnings=0` for that project.

**The merge proof moved below the shell.** The Bash gate reads literal command text, so
`update-story "$SID" done` slipped past every regex — the hook never sees the variable's
value. `story_done_gate.py` now lives in `smm/` and the same git-derived proof runs in the
engine handlers, where every writer of `status` converges. Same proof, one layer down.

**A recovery hatch that costs something.** `update-story-if ... --force-unmerged "<reason>"`
is the only way past the gate, and it records a debt event *before* the status write — a
bypass nobody can see is the silent mark-done this gate exists to stop. An empty reason is
refused.

**Raw `git branch -d/-D` of an unmerged story branch is refused.** Branch absence is what
the mark-done gate reads as proof the merge landed; deleting one by hand would let it read a
merge that never happened.

**Teammate worktrees can bootstrap themselves.** `git worktree add` materializes only tracked
files, so everything gitignored — `node_modules`, generated types, `.env` — is absent.
spike-005 measured the DOMINANT effect as a loud false-RED — a bare worktree's typecheck hit
TS2882 "Cannot find module", exit 2, and bare tests exited 1 over a dozen unresolvable
modules, stranding a teammate mid-story. A rarer, contrived false-GREEN also exists: missing
generated types can make a type augmentation permissive so broken code compiles clean. Set
`stack.worktree_bootstrap` in `system_context.json` to a script your repo already has, and
it runs in each new worktree before the teammate's first turn. It is an opaque command by
design — your script knows which artifacts are shareable and which must be regenerated
per-checkout; the plugin cannot and should not guess.

## v4.11.0 — Mark-done honesty: branch deletion proves merge

First milestone of a new backlog-paydown plan (M6): **a deleted branch now honestly
implies it was merged.** The mark-done gate reads branch *absence* as proof a story's
merge landed — a premise that had cracks. Every branch-delete path now proves the merge
against the recorded story base before deleting.

**One base-proving delete primitive.** `worktree.remove_worktree` used a raw `git branch
-d/-D` that trusted git's upstream-based check — so on any remote-backed repo it would
delete a pushed-but-unmerged branch. It now routes through `branch_lifecycle.delete_branch`
(which proves `is_merged_into` against the recorded story base first) and returns a
`BranchRemoval` outcome (`DELETED_MERGED` / `REFUSED_UNMERGED` / `FORCE_DROPPED_UNMERGED` /
`NO_BRANCH`) so callers know what happened.

**Proof against the base, not HEAD, fail-closed.** `cleanup_teammate` proved merge against
the current HEAD — misjudging a branch merged into its recorded base but not into HEAD. It
now proves against the recorded story base via `get_story_base_branch_required` (which
raises rather than silently degrading to primary), and refuses to delete on an unresolvable
base.

**Proven end-to-end.** An integration capstone exercises the two delete paths and the
mark-done keystone together on real git worktrees over one shared model: a merged branch's
absence allows mark-done, and an unmerged branch is refused (kept) so the gate still blocks.
(The remaining fail-open — a raw `git branch -d/-D` of an unmerged story branch typed
straight into the shell — is scheduled for M2, guarded there by prevention at the command
gate.)

## v4.10.0 — Planning artifacts keep their record

Milestone 5 finished the plan (M1–M5 all delivered): **the tools stop destroying and
misreading their own records.** Where a budget truncated rationale, it stops; where a
create overwrote history, it archives first; and three gates that misjudged a marker
now read the work itself.

**Planning fields stopped truncating rationale.** A cross-project census of 48 live
stories showed `context` right-censored at exactly its 600-char cap — the signature of
authors trimming WHY to fit — and the 500-char milestone `design_details` cap cut the
rationale on 4 of 4 milestones. Both go to 800. The `xp-sprint-start` prose that states
the budget moves in lockstep with the schema constant.

**`sprint.json` stops being unrecoverable.** Every `sprint_cli create` overwrote it, so
past sprints were gone — unlike execution plans, which archive into `plans/`. A new
`sprint_archive.archive()` (a sibling module, so `sprint_store.py` stays under the
500-line cap) snapshots the completed sprint into `sprints/` at close, wired through a
`sprint_cli archive` subcommand exactly as `/xp-plan-close` archives the plan.

**The mark-done deadlock is closed.** The `.accept` marker gates mark-done and was
consumed only *after* `/xp-accept`'s no-stories exit — so a story already merged with
nothing left to accept stranded the marker forever, escapable only by a manual `rm`
(hit live on story-008). The consume now runs on every path the skill reaches.

**The accept-evidence gate reads acceptance, not intent.** A lead's raw `/xp-story-close`
was refused unless the session-scoped `ACCEPT_IN_FLIGHT` marker was armed — which proved
accept had *started*, not that this story's acceptance *passed*. It now keys on the
per-story `closing` state `/xp-accept` sets immediately before dispatch, and it fails
**closed** on a corrupt/missing sprint (degrading quiet only when the SMM dir itself is
unresolvable).

**An answered question stops reading OPEN.** Two blocking questions asked before an
answer clobbered the single-valued question gate, so only the last was ever recorded as
answered — a plan-reviewer once read the log, saw two unanswered questions, and wrongly
concluded a plan had faked a customer sign-off. On answer, every still-open blocking
question resolves.

**verify-touch stops nagging deliberate regression pins.** When a behavior-preserving
refactor declares an existing suite as its acceptance — its staying green *unchanged* is
the proof — verify-touch flagged the untouched path and forced a `[verify-deferred]`
commit that recorded debt every time (5 misfires this sprint). A story may now declare
`acceptance_execution.pins`: repo-relative paths exempt from the untouched check at the
single point all four consumers funnel through, with the plan-reviewer flagging an
all-pinned story (no authored proof) or a malformed pin (matches nothing).

## v4.9.0 — Gates that see the work they gate

Milestone 4 was one idea, spelled four ways: **a gate that acts on state it cannot see is a gate
that fails open.** Each fix in this release makes a gate look at what actually ships instead of a
proxy for it.

**The close pipeline reviewed a different commit than it merged.** The reviewer was handed
`gh pr diff <N>` — the *remote* head as of the push — while the merge lands the *local* branch. Every
fix committed during a close (including the close-reviewer's own) shipped unreviewed; the last release
caught this live, reviewing one commit while five of its own defect fixes sat unpushed. The reviewer
now reads `git diff <target>...<source>` — the exact range that merges — and the merge re-pushes the
source first (`--no-verify`, so a stale-PR record can't wave through a wrong-tree pre-push hook) so the
PR record matches what landed. Not `...HEAD`: at story-close the reviewer runs from the orchestrator
checkout, where `HEAD` is the sprint branch, not the story.

**The close-cycle gate trusted a marker it set itself.** `CLOSE_CYCLE_ACTIVE` is written by the close
skill's own preload, so its presence proved only that a close *started*, never that a reviewer *ran*.
The close-reviewer was the one subagent that emitted no completion event; it now emits the standard
`subagent_complete` evidence, and the gate cross-checks the event log — reviewer-completion evidence
releases a lingering marker, and the read fails **closed** on a bad log. The evidence check is placed
*before* the `stop_hook_active` bypass, so a crash between emit-and-consume can't be mis-recorded as a
false abandonment.

**`/xp-story-close` could merge before `/xp-accept` ever ran.** The acceptance gate fired at
mark-done — *after* the merge. The close is now gated at its own door (the Skill hook, not the
Write-only lead-gate table): a lead `/xp-story-close` is refused unless an accept session is in flight.
Teammates were already blocked; this closes the lead's bypass.

**The commit lint gate checked the bytes on disk, not the bytes being committed.** It named the
*staged* paths but ran the linters against the *working tree*, so `git add -p` or an edit-after-add
let bad staged bytes commit clean — in any language. It now lints the git index: each staged blob is
materialized (`git show`) to an in-dir temp sibling (same directory + extension, so config and
`node_modules` resolution are unchanged), the deletion-skip keys on index membership, and an unreadable
index blob fails **closed**. Language-blind throughout — exit codes and `git show`, no per-linter branch.

A capstone integration test drives all three close gates through their real subprocess entrypoints, and
Milestone 4's source design docs are retired to `docs/completed`.

## v4.8.0 — Gates that fail OPEN

**Seven gates in this plugin could be made to wave work through**, and one of them had never
fired in production at all. Every one is fixed here — and **most were found by review, not by
the story that opened the file.** Twice, review disproved a claim the author had already
written into a commit message.

A gate that fails open is worse than no gate: it reports that it checked.

The sharpest lesson of the sprint is in the two gates that were *added* here. One shipped
**dead** — its pattern required the CLI name on the same line as the subcommand, but the real
invocation is wrapped across a line continuation, and every test passed because the test's
fixture was single-line. A fixture that does not have production's shape is a mirror, not a
test. The other was built on an invariant that turned out to be **false**: "git refuses to
delete an unmerged branch" is true only of a branch with no upstream, and this pipeline pushes
every branch before it merges.

### The schedule gate blocked the wrong writes — and the plan door failed open

The pre-write schedule gate blocked *any* write in the pre-promotion window. It blocked a write to
a file **outside the repo** — not this project's story code at all — where the only way to satisfy
it was to promote a story against a customer pause. And it blocked work on a **free branch**, where
the sprint isn't the frame.

It now exempts both, keying free-ness on branch **shape** (a marker could be `rm`'d to bypass). The
same gate runs at a second door — `EnterPlanMode` — so on a free branch you could neither write nor
plan; that door is fixed too.

Putting both doors in one diff is what exposed the real bug: **`pre_tool_plan_mode` failed OPEN on
an unreadable `sprint.json`.** It died with a traceback, and PreToolUse treats a non-2 exit as
*non-blocking* — so plan mode opened with every sprint gate blind. Its sibling write door had
failed closed correctly for months.

And the new exemption itself shipped a third: `resolve_git_root` can return an **empty string**, and
`Path("").resolve()` is the hook's own cwd — so containment was judged against the wrong tree and an
in-repo write read as out-of-tree. Caught by review, pinned by a test.

### The Write hot path could be waved through by any unexpected OSError

`resolve_git_root` caught three narrow exception types. Any *other* `OSError` from the git fork
(`PermissionError`, `EAGAIN`) escaped, killed the hook, and the write landed **un-gated**. A per-cwd
cache is what hid it: whether it fired depended on whether an earlier call had warmed that cwd — so
it presented as a **flaky test**, not as red. A flaky test guarding a fail-closed gate *was* the
gate failing open.

### The commit-time lint gate stops being Python-only

It hardcoded ruff. A TS/Rust/Go repo staged no `.py` files, and the gate silently passed — **zero
commit-time lint enforcement in any language but Python.**

(It does not reach *every* language. What it does and does not gate is spelled out below — the first
draft of this note claimed "any language", and the binaries disagreed.)

The gate no longer parses. It classifies by **exit code**: 0 is clean, non-zero with output is
findings (reported verbatim, never interpreted), non-zero with nothing readable is **unverified →
blocked**. A new language is a row in a table, never a branch. Two columns the naive design lacked:
a strictness flag (eslint exits 0 on warnings, and `no-unused-vars` is `warn` in many configs) and a
file-scoped capability flag (clippy lints the whole crate, so one pre-existing warning would have
blocked every Rust commit, unfixably).

**Breaking:** the rule is uniform, so **Python is stricter** — E302 and friends now block a commit
where before only F401/F811 did.

The gate's timeout was calibrated for ruff back when ruff was all it ran. `npx eslint`'s *cold start*
alone exceeds it — timeout → unverified → block, an unfixable gate for exactly the languages this
serves. It's now one shared budget across all linters, bounded **above** by the harness's 60s hook
limit: past that the harness kills the hook, which produces no exit 2 and fails **open**.

### A frontier with a dependency edge could be fanned out in parallel

`ready_frontier_report` could authorize concurrent teammates for stories where one depends on
another. The fault isn't file overlap — it's the **base branch**: every story branch is cut from the
same sprint base, so a promoted dependent is cut from a base *without its dependency's commits*,
wrong even when their file domains are perfectly disjoint. The frontier must be an **antichain**, and
now it is (transitively — the edge can run *through* a story absent from the frontier).

### The in-place teammate marker: liveness a pid can't fake

Liveness is now a kernel-held `flock` OR'd with a live child pid. The kernel releases the lock on any
death, SIGKILL included — no pid to recycle, no verdict to mis-adjudicate. The child-pid leg is
load-bearing: SIGKILL of the supervisor does *not* propagate to the child, and a lock-only verdict
would reap a **live** teammate's marker, certify a half-written tree, and let a respawn admit a
second agent into the same checkout.

### The retro stops nagging about work the plan already schedules

A milestone can now declare `schedules: [<event-id>]`, and the retrospective reads it. Previously it
escalated a debt to HIGH after 7 sessions "unresolved" while a milestone named that debt as its
deliverable.

Building it exposed a fail-open in the id pattern itself: `EVENT_ID_RE` was anchored with `$`, which
in Python matches **before a trailing newline** — so `"<id>\n"` validated as an id and then matched
nothing. It guards `metadata.resolves` too.

### A story could be recorded as shipped when its merge never happened

The close pipeline merged, then marked the story done — and **nothing stood between those two
steps.** When a merge failed on a transient `.git/index.lock` (a sibling worktree holding the
index for a moment), the pipeline carried on and recorded work that was not on the branch.

The failure was never silent at the git level; the merge exits non-zero with git's own stderr.
The silence is that the *caller* is an agent following prose. So mark-done is now gated on
**proof from git**, not on the agent's word.

Getting the proof right mattered more than it looked. The obvious design — record the merged
SHA at merge time — is a trap: if the merge succeeds and the state write then fails, re-running
the merge answers *"Already up to date"*, no SHA can ever be produced, and the story becomes
**permanently un-markable**. A gate whose only repair path is blocked by itself is worse than
the bug.

So the proof is derived from git at the instant of mark-done. And the invariant it first rested
on — *"git refuses to delete an unmerged branch, so the branch's absence proves the merge"* —
is **false**: `git branch -d` defers to the branch's **upstream**, and story-close pushes every
branch before merging. Git will delete an unmerged-but-pushed branch and exit 0. The merge proof
is now *ours*, checked before any delete, rather than something we hoped git enforced.

The transient lock is retried too (bounded, backing off, lock-signature only — a real conflict
must still fail on the first attempt). But the retry only **narrows** the window. The gate is
the fix.

There is an escape hatch, because a gate with no recovery path is its own failure mode:
`--force-unmerged "<reason>"` requires a non-empty reason and records a debt event. The bypass
is never silent.

### The test suite stopped writing into a shared /tmp root

Tests that drive a teammate spawn were minting real directories under the real, shared
`/tmp/xp-agents-teammates` — hundreds of them, four more every run.

The obvious fix (have the test base delete the directory it created) was **more dangerous than
the leak**: the path is derived from the SMM dir, `init.sh` honors an exported `SMM_DIR`
verbatim, and that is exactly a CLI teammate's environment — so the sweep could resolve to a
**live project's id** and delete a running teammate's logs.

Redirect, don't sweep. The log root now resolves through `XP_TEAMMATE_LOG_ROOT`, and the test
suite points it at a sandbox. Nothing is written to the real root, so nothing can delete the
wrong thing — the class of bug is gone rather than guarded against.

### What is actually gated, and what only advises

The first draft of this note claimed "any language", and when it was written nobody had run the
binaries. So we ran them, and the claim was too strong. **C/C++ and Java were not gated at all** —
both were parked as advisory-only, while the release note said otherwise.

**C/C++ is now genuinely gated**, and getting there refuted the fix we had written down for it:

- `clang-tidy`'s synopsis is `clang-tidy [options] <sources> -- [compiler-flags]` — everything
  *after* the separator is compiler flags. The gate's universal `[cmd, "--", *paths]` handed it
  **zero sources**.
- Correcting the argv **alone would have made it worse.** Invoked correctly, clang-tidy finds the
  violation, prints it, and **exits 0** — which the gate reads as *clean*. It needs
  `--warnings-as-errors`, and only the real binary could tell us that.
- Our own recorded fix said "sources before the separator, **trailing `--`**". The trailing `--`
  means *no compiler flags* and **overrides `compile_commands.json`**, throwing away the database
  that lets clang-tidy resolve an `#include`. Half our prescription was wrong.
- So C/C++ is gated **where a compile database covers the staged file** — not merely where one
  exists. A partial or stale database (a new subtree, generated sources, a DB nobody re-ran) leaves
  that file no include flags, and clang-tidy then fails to *compile* it — which the gate would read
  as a finding and refuse the commit over. Uncovered files degrade honestly instead —
  because without one, a header in another directory fails to *compile*, and the gate would block on
  an error no diff can fix.

**Java is not gated, and we now know why.** `checkstyle`'s exit code counts `severity=error` only: the
same violation at `severity=warning` is printed and then exits **0**. Its CLI has no
warnings-as-errors lever. Its exit code simply cannot express *"I found something"*, and gating it
would mean parsing its report — and in this gate, the parser *was* the bug. It stays advisory, and
now says so in its own words.

Every degraded linter now reports **its own reason**. The old advisory told C/C++ users that
clang-tidy "lints the whole project, not one file" — which is false, and the code knew it was false.

### Known-open

- The lint gate reads the **working tree**, not the staged bytes — it diverges under `git add -p`.
- Java/Kotlin/Elixir/C# get an advisory, not a gate; each now states its own reason.
- C/C++ without a `compile_commands.json` advises rather than gates.

## v4.7.0 — Adoption records intent, not resolution — and compaction stops eating the record

Two of these are silent data loss that shipped in v4.6.1. If you run this plugin, upgrade.

### Adopting work is not finishing it

Every leg of the adoption path folded a `[refs: ...]` suffix into `metadata.resolves`. So
"I'll do this" was recorded as "this is done": the target closed, the housekeeper read it
as confirmed-fixed and dropped it from your curated pillars, and the work evaporated. You
were never told.

Closure (a terminal disposition) now writes `metadata.resolves`. Intent (adopt/defer) names
its target in top-level `references` and leaves it **OPEN**. The predicate is the
disposition, not the event type. `subagent_start` was the last reader still inferring the
lane from an LLM-authored topic slug, and its status arm had no lane check at all — so
triage-lane defers of *debts and concerns* reached the housekeeper mislabelled as retro
Tries. The lane gate is now one definition, and triage items get their own heading rather
than being deleted (they are `status` events, which `materialize` buckets nowhere — that
block is the housekeeper's only signal that a concern was adopted).

Verified by a differential over 12,757 real events: zero retro drops lost, 97 historical
adoptions in and 97 out.

**This fix is forward-only.** Items already laundered in your existing log stay closed —
there is no backfill, and upgrading does not recover work that was already silently
resolved. What it does is stop the bleeding: from v4.7.0 on, adopting something no longer
closes it. If you suspect a debt or concern went quiet without being fixed, it is worth
re-reading your `backups/archive-*.jsonl` before trusting the open set.

### Compaction annihilated events that arrived while it ran

`replace_events_file` took the exclusive lock, re-read the file under it — and threw that
read away, writing the caller's stale snapshot. An event appended in that window was erased
from `events.jsonl` **and** absent from the archive, which was built from the same stale
snapshot. It reached **neither**. No trace, no signal. Teammates share one SMM dir and every
SessionEnd compacts, so this was the normal case, not an exotic one.

A whole-file rewriter now passes `seen_ids` — the ids it *read*, not the ids it keeps — and
the primitive merges under the lock. An event the caller never saw was never a candidate for
removal. A second door was found and closed in review: second-resolution archive filenames
let two same-second compactions clobber each other's archive, losing the first run's events
entirely.

### Compaction could never release a commit event, in any project

`compact.py` pinned every commit whose sprint lacked a `sprint_retro_done` marker — and
nothing ever wrote that marker. Measured across 11 projects: **100% of commit events pinned,
in every one** (74% of the live log in the worst case). The live log could never shrink, and
every hook re-read and re-parsed all of it.

Commits are now released by an **age rule**, so the fix is self-healing: it repairs existing
projects on the next compaction, with no migration. Against the live log it released 473 of
522 commits — ~579 KB of a 952 KB file — with zero markers present.

### Adoption memory now outlives the event that recorded it

A sidecar ledger (`adoption.json`, the ring-buffer template) upserts one record per adopted
target, so a compacted adopt event no longer means forgotten work. Compaction itself is the
writer — the thing that destroyed the memory is the thing that preserves it — so the adopt
path needed no changes and the ledger cannot drift from it. `events.jsonl` gains nothing.

### Also

- **The project-agnostic guardrail gets teeth.** An AST pin fails the suite when shipped code
  branches on a file extension for a *user-supplied* path without an inline `# lang-ok:`
  justification. It is a floor, not a ceiling, and its docstring says so.
- **The capstone stops assuming you write Python.** `build_capstone_story` no longer defaults
  `acceptance_execution.type` to `pytest`; it resolves from the surfaces the capstone spans,
  and degrades to a placeholder rather than guessing a language.
- **Spawn refuses a prompt that names another story.** Story ids repeat every sprint, so a
  stale prompt could spawn a teammate on the wrong story, silently.
- **The pipeline stops inverting itself.** `xp-assign` told the lead to *pause planning* to
  accept a finished teammate — which empties the background for the whole accept cycle.
  Spawnable work goes out first.
- **The `.assign-pending` gate self-clears** when there is nothing left to assign.
- **Reasoning budgets 400 → 500** for concern/debt/decision/discovery, with the kickoff
  injection bounded at *injection* time — so storage grows at zero extra injected bytes.

## v4.6.1 — The lead's gates stop forbidding the parallel pipeline

### A teammate never plans, so the planning marker must not gate it

The parallel pipeline exists so the lead can plan story N+1 while a teammate executes
story N. The plan-review gate blocked **every** agent's writes while
`.plan-awaiting-review` existed, so it forbade exactly that state: the lead exits plan
mode, the marker lands in the shared SMM dir, and every running teammate is hard-blocked
until `/xp-review-plan` clears it. A teammate cannot clear a marker it does not own, so
it stalls mid-implementation.

This was never a regression. The gate, `markers.py`, and both marker writers are
byte-identical from v4.4.2 to v4.6.0, and no release back to v3.11.1 has an agent check
anywhere near the gate. The contradiction has been latent for months and surfaced only
when four teammates wrote into a long planning turn. It also violated the project's own
constraint that gates are state-derived and self-clearing, never marker-blocks.

The assign gate immediately below already exempts teammates for the same reason — they
are dispatched *by* `/xp-assign` and share the SMM dir holding the marker. The plan gate
was simply the odd one out, so the fix is that file's existing idiom rather than a new
mechanism: planning belongs solely to the lead.

The assign gate's own teammate guard now also receives `smm_dir` explicitly. The env leg
of `is_worktree_teammate` falls back to `$SMM_DIR`, so a hook process running without
that variable failed closed and over-gated a real in-place teammate as the lead.

### The question gate had the same defect, one gate further down

Review of the above found the identical hazard sitting unfixed immediately below it. A
🔴 question — raised by *any* agent — arms `.question-gate` in the shared SMM dir, and
`AskUserQuestion` is the **only** thing that clears it. A headless teammate has no user
to ask, so it could clear neither the lead's question nor **its own**: a single blocking
question from one teammate hard-blocked every write by that teammate, the lead, and every
sibling, permanently.

Teammates are now exempt from the question gate too. The lead stays gated — it is the
only agent that *can* call `AskUserQuestion` — so a teammate's question still escalates
to the user exactly as before. It simply no longer deadlocks the fleet while doing so.

### The three lead-only gates now say so in one place

Plan, assign and question each hand-rolled their own teammate exemption, so a gate added
next would silently default to gating teammates — which is precisely how the plan gate
came to forbid the pipeline unnoticed for months. They are now one ordered table whose
entries are lead-only by construction. The teammate probe also moved *behind* the marker
check and runs at most once, so the common case (lead, nothing armed) — every Write and
Edit — no longer pays for a cwd parse, an env read and a marker stat it never consumes.

## v4.6.0 — The accept-gate sees in-flight work; perf tests stop measuring the machine

Plan `Gates that see the work`, milestone 1 (sprint-116), plus one adjacent fix.

### Accept-gate defers while an in-place teammate is mid-flight

The sprint stop-gate deferred for *worktree* teammates, but an **in-place** teammate
runs in the main checkout and registers no worktree — so the gate was blind to it and
demanded `/xp-accept` on exactly the turn the lead was correctly idle-waiting for the
spawn. Accepting there certifies a half-written tree. Four live reproductions are on
record, one of which fired *during this sprint*, against the very branch fixing it.

`worktree.has_live_in_place_teammate(smm_dir)` is a **name-free** probe (the Stop hook
knows a story is in-progress, never who is executing it), and `_deferred` consults it.
It is deliberately **not** a bare existence check: every other consumer pairs the marker
with `XP_TEAMMATE_NAME`, which is why a leaked marker is inert today. Drop that half and
one marker leaked by a SIGKILLed `spawn_teammate` would suppress the gate *forever* — so
`write_in_place_marker` now records **pids**, and the probe ignores dead-pid markers and
**reaps** them, so a recycled pid cannot resurrect one.

Which pids matters. `spawn_teammate` is only a **tee** around the real teammate: it
launches `claude` with a plain `Popen` (no `start_new_session`), so a signal to the
supervisor's pid does *not* propagate — the child reparents to init and keeps running.
A child mid-silent-stretch (a long model call; the watchdog tolerates 900s of them)
outlives its supervisor indefinitely. So the marker records **every** process whose life
means the episode is still in flight — supervisor *and* child — reads live while **any**
survives, and is reaped only once **all** are *proven* dead. That is what lets the two
consumers pull in opposite directions safely: the existence-only readers (identity, skill
gating, commit attribution) never lose a *live* teammate's marker, while the gate's
liveness probe still goes false once nothing is left running.

Proven end-to-end by a capstone that drives the hook as a real subprocess with no mocks,
and that is *falsifiable*: remove the gate clause and it goes red. The orphaned-teammate
case carries its own positive control — same fixture, same dead supervisor, the recorded
child alive in one and dead in the other — so "stays quiet" cannot pass for the wrong reason.

### Perf benchmarks assert structural invariants, not wall-clock

Six absolute wall-clock bounds gated every commit and measured the **scheduler**:
`read_delta` costs 1.3ms serially but hit 53ms against a 50ms bound under `pytest -n auto`,
blocking commits whose diff touched none of it — the likely root of a recurring
"consecutive test failures" retro signal. Each timer is replaced by the structural
invariant it stood in for (parse cost tracks the delta; the Write hook never scans the
event log; the xp-* early return precedes all I/O), each with a **durable positive control**
so a mis-scoped spy cannot be green forever. Two of the old tests were decorative:
`compact_5000` never reached the compaction path, and the output-filter deadline never
checked that it *waited*.

The three timers survive behind `unittest.skipUnless(XP_PERF)` — stdlib, because CI runs
`unittest discover` with no pytest — and now hard-gate `git push` via a **serialized**
lefthook `pre-push`, so they run alone and their numbers mean something.

## v4.5.0 — Enforce the file-domain invariant at write time; explain non-parallelizable frontiers

Plan `File-domain lock + stop-gate in-flight awareness`, milestones 1–2
(sprint-114, sprint-115). `file_domain` was documented as an exclusive-ownership
invariant but nothing enforced it — and `sprint_save`'s sister-test auto-include
actively violated it on the author's behalf. This ships the enforcement and makes
a frontier that cannot parallelize say why. Every change TDD-ordered and reviewed
before merge; also carries live the commit-recording fix that the cached 4.4.x
plugin predated.

### File-domain lock at sprint-write time (M1)

- **Sister-test auto-include can no longer claim a path another story authored.**
  `sprint_save` now seeds `existing_paths` from the union of all authored domains
  before the per-story loop, and a new `file_domain_lock` collision report keys
  each path to its `(story_id, origin)` owners — distinguishing an authored
  collision (a planner error) from an auto-included one (a tool error), which need
  different remedies. Any surviving collision fails the sprint write loudly,
  naming every colliding path, its owners, and origin — not just the first.
  Applies to `create` and `add-story` alike; comparison is literal-token via the
  shared `triage.entry_to_paths` parser, no glob expansion at write time.
- **`edit_story` file_domain edits are gated against introduced collisions.** An
  edit that would make a path collide with another story's domain is blocked,
  comparing `collision_report(baseline)` vs `collision_report(current)` with both
  sides sister-expanded so a path is blocked iff its colliding-story set grew.

### Report intentional overlap instead of silently degrading (M2)

- **A non-parallelizable frontier explains itself.** `/xp-schedule`'s preload now
  names both stories and the shared path that forced solo (`OVERLAP_DETAIL=…`), or
  reports `GLOB_FORCED=true` when a glob domain makes disjointness unprovable.
  `ready_frontier_report` carries the overlap detail alongside the parallelizable
  bool, backed by M1's collision report; the dead `scheduled-overlap` CLI
  subcommand and its now-callerless bool were removed.

### Hardening

- **A newline in a `file_domain` path can no longer forge a preload variable.**
  Every preload variable now flows through one sanitized emit path
  (`emit_var`/`sanitize_tsv_block`), closing a prompt-injection where a crafted
  path forged a preload line and shadowed a gate.
- Internal refactors kept every touched file under the 500-line cap
  (`sprint_store`→`sprint_frontier`+`sprint_metrics`; `commits.py`/
  `commit_handling.py`→`commit_command.py`+`commit_event.py`).

## v4.4.2 — Fix the /xp-assign executor-effort latch

Free-branch fix. `/xp-assign` persists two decision fields on each story —
`executor_model` and `executor_effort` — that Step 1 reads back and Step 4
forwards to the spawned teammate as `--model` / `--effort`. TDD-ordered and
reviewed before merge.

- **A retracted recommendation no longer leaves a stale `executor_effort`.**
  Step 0 wrote `executor_effort` only when the plan-reviewer recommended one and
  skipped it otherwise, so a re-assignment after a retraction (or a customer who
  keeps the default over a divergent recommendation) left the *prior* effort
  latched on the story. A new `sprint_cli.py set-executor` subcommand writes a
  field as value-or-null **only when its flag is passed** (provided-empty → null,
  omitted → untouched), and Step 0 now passes `--effort` on every spawning branch
  — the recommended effort when spawning at the recommended tier, else `--effort
  ""` — clearing the latch. (Closes a debt carried across six sessions.)
- **`executor_model` is preserved on the inherit path.** Because a story's
  `executor_model` can also be set by a deliberate `/xp-schedule` per-story
  pre-seed, Step 0 *omits* `--model` on the inherit outcome rather than clobbering
  the pre-seed to null — so a story you scheduled at, say, `haiku` still spawns at
  `haiku`.

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

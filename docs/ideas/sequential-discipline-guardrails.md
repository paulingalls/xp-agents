# Idea: Sequential-discipline guardrails (prose + injection layers)

> Status: ready for an execution plan. Prose + injection scope only; the hard
> spawn-lock guard is explicitly deferred (see "Deferred" below).

## Problem / Context

The Claude Code harness system prompt instructs the agent to batch independent
tool calls in parallel ("If you intend to call multiple tools and there are no
dependencies between the calls, make all of the independent calls in the same
block... Independent tool calls can run in parallel"). xp-agents flows are the
opposite: deliberately step-gated and sequential. When the agent over-applies
the parallel instinct inside an xp flow, three failure modes appear (all
observed live during a kickoff session):

1. **Orchestrator** — batches `AskUserQuestion → record-answer → act` in one
   block, so the user's answer races an action already queued (pre-guessed
   answers; thrown-away work when the guess is wrong).
2. **Subagent spawn** — fires N identical subagents in one block (e.g. 3
   `xp-retrospective` agents), which collide on shared preload input.
3. **Inside a subagent** — batches dependent calls (save + verify-before-
   confirmed), guesses, errors.

**Key empirical finding:** the three skills that **already** carry "complete ALL
steps in order, do NOT stop" mandates (`xp-kickoff`, `xp-work-selection`,
`xp-end-session`) are where batching was *worst*. "In order, don't stop" reads as
"fire everything at once" — it counters step-*skipping* but not parallel-
*batching*. The fix must explicitly name and counter the harness's parallel-tool
instruction, telling the agent what to tone down.

**Intended outcome:** the plugin asserts sequential discipline loudly in the
contexts it controls — per-skill SKILL.md pins, a richer PROCESS_GUIDE section, a
one-line subagent injection, and the TEAMMATE_GUIDE — each explicitly counter-
weighting the parallel-tool system instruction while preserving legitimate
independent-read batching. Honest scope: mitigation via prose+injection, not a
hard guard.

## Verified facts (grounding)

From the official hooks reference + source inspection:

- `SubagentStart` supports `additionalContext` but **cannot block** — confirms
  this layer is best-effort mitigation, not enforcement.
- `subagent_start.run()` (`plugins/xp-agents/scripts/subagent_start.py`) already
  appends XP values to **every** subagent (after the injector dispatch, near
  `plugin_loader.load_xp_values()`, ~line 160) — a single choke point for a
  subagent-scoped note.
- PROCESS_GUIDE.md is injected to the lead agent (post-housekeeping, via
  `review_cycle_done.py`) and to full-SMM subagent tiers.
- **17 skills total**: 14 inline (main-agent-driven, step-gated) + 3 forked
  delegation skills (`xp-review-plan`, `xp-sprint-review`, `xp-system-context`)
  which have no inline steps and need no pin.
- `subagent_start` tests live in
  `plugins/xp-agents/tests/hooks/test_subagent_tiers.py` (class
  `TestSubagentStartTieredInjection`, calling `subagent_start.run(...)` directly —
  there is no `_run` helper).

## Scope decisions (confirmed with user)

- **B-everywhere**: self-contained pin in each inline skill, with skill-specific
  language naming that skill's actual internal step sequence. NOT a thin
  "see PROCESS_GUIDE" reference.
- **Fold in everywhere**: include the 3 skills that already have ordering
  language — the new anti-batch rule is additive, and those are the proven
  failure sites.
- **Both injection points**: PROCESS_GUIDE section (richer — injected once) +
  one-line subagent-scoped note in `subagent_start.py`.
- **Reference the system instruction explicitly** so the agent knows precisely
  what to suppress inside xp flows, while preserving independent-read batching.
- Declarative prose, necessary-but-sufficient bar (per the declarative-skill-prose
  convention).

## The rule (canonical wording — finalize during implementation)

**Orchestrator / inline skill (SKILL.md + PROCESS_GUIDE):**
"The harness instructs you to batch independent tool calls in parallel. These
steps are dependent and gated — suppress that instinct here. Run one step per
turn: make the call, observe the result, then decide the next. Never place an
`AskUserQuestion` and the action that depends on its answer in the same block.
Never spawn the same subagent more than once. Batch only genuinely independent
read-only calls."

**Subagent (one line via `subagent_start.py`):**
"You are a single-purpose sequential agent: do one action, observe its result,
then proceed. The harness's parallel-batching guidance does not apply to
dependent calls (e.g. save then verify) — only to independent reads."

Each per-skill pin adds a one-line, skill-specific ordering reminder using the
real step names (e.g. xp-accept: "Step 1 → 1b → 1.5 → 2 → 3 → 4 strictly; never
batch the AskUserQuestion in Step 1 with the /xp-story-close call in Step 2").

## Files to modify

### Injection layer (code — TDD)
- **`plugins/xp-agents/scripts/subagent_start.py`** — add a module-level
  `SEQUENTIAL_DISCIPLINE_NOTE` constant and append it to `parts` in `run()`
  alongside the existing XP-values append (and in the `smm_dir is None` early
  return). Wording must exempt independent reads so Explore fan-out isn't chilled.
- **`plugins/xp-agents/tests/hooks/test_subagent_tiers.py`** — failing tests
  first (TDD): assert the sequential note appears in `run()` output for a
  default agent and for an `xp-retrospective` (values-only) agent, and that the
  independent-read exemption phrasing is present. Use `subagent_start.run(...)`
  directly per existing patterns in that file.

### Prose layer (PROCESS_GUIDE + guides)
- **`plugins/xp-agents/PROCESS_GUIDE.md`** — new "## Sequential Discipline"
  section (richer treatment; names the system instruction, one-step-per-turn,
  the AskUserQuestion-race rule, no-duplicate-subagent, independent-read
  exemption).
- **`plugins/xp-agents/TEAMMATE_GUIDE.md`** — parallel short section for
  teammates (sequential single-story workers). Anchor near "TDD Workflow" /
  "Code Quality".

### Prose layer (per-skill pins — B-everywhere, all 14 inline skills)
Insert a self-contained pin immediately after the frontmatter + preload block:
- Already have ordering language (fold anti-batch in): `xp-kickoff`,
  `xp-work-selection`, `xp-end-session`.
- Lack ordering language (add full pin): `xp-plan`, `xp-sprint-start`,
  `xp-accept`, `xp-assign`, `xp-quality-review`, `xp-scaffold-acceptance`,
  `xp-sprint-close`, `xp-plan-close`, `xp-free-close`, `xp-story-close`,
  `xp-stage-migration`.
- **Special case** `xp-scaffold-acceptance`: declares non-standard runtime order
  `1 → 3 → 2 → 4 → … → 10` with per-surface loop nesting — the pin must echo
  that exact order.
- **No pin** for the 3 forked skills.

## ⚠️ Line-budget gates (from plan review — the build-breaking gotcha)

`tests/.../test_guide_budgets.py` and `test_skill_budgets.py` enforce `wc -l`
caps, pinned to the real files. **Every file whose pin/section overflows its cap
MUST bump the matching dict entry in the SAME commit**, or `pytest` goes red and
the commit gate blocks. Known-tight at time of writing:
- **PROCESS_GUIDE.md: 90/90 lines — ZERO headroom.** Any added line fails until
  `test_guide_budgets.py` is bumped.
- **TEAMMATE_GUIDE.md: 46/50** — only +4.
- Tight skills: `xp-sprint-close` **+2**, `xp-quality-review` +10,
  `xp-work-selection` +10, `xp-free-close` +12.
- Comfortable: xp-kickoff (+52), xp-plan (+28), xp-story-close (+27),
  xp-sprint-start (+24), xp-assign (+24).

(Re-measure at implementation time; numbers drift between releases.)

## Suggested build order (TDD where there's code)

1. **Injection layer first (testable):** failing test in `test_subagent_tiers.py`
   → implement the constant + append in `subagent_start.py` → tier tests green →
   full suite `pytest -n auto`. `/code-review` → `/xp-quality-review` → commit.
2. **PROCESS_GUIDE + TEAMMATE_GUIDE sections** + their budget bumps in the same
   commit. `/code-review` → `/xp-quality-review` → commit.
3. **Per-skill pins** (all 14) + each overflowing skill's `SKILL_BUDGETS` bump in
   the same commit. `/code-review` → `/xp-quality-review` → commit.

If sprint-mode: these map cleanly to 3 stories (injection / guides / pins), all
sharing the budget-test files (so likely solo or careful domain split — the
shared `test_guide_budgets.py` + `test_skill_budgets.py` edits create overlap).

## Verification

- Unit: new tests in `test_subagent_tiers.py` assert injection content +
  independent-read exemption.
- Full suite: `pytest -n auto` green (catches the budget gates).
- Manual read-through: each of the 14 pins names that skill's real step sequence
  + the anti-batch / AskUserQuestion-race rules; forked skills untouched.
- Dogfood next session: the live cached plugin only updates on version bump +
  publish, so guardrails won't affect the authoring session — verify
  behaviorally in a later kickoff.

## Design notes to watch during /xp-quality-review

- The subagent note lands in **every** tier (incl. the 3 forked delegation
  skills, Explore, housekeeper, retrospective) — desirable, but acknowledge the
  blast radius rather than framing it as targeted.
- Read-chilling on Explore: exemption wording mitigates; net effect unverifiable
  until next-session dogfood.
- 14 near-identical pins risk boilerplate. Each earns its place only via genuine
  skill-specific step-name wording; if a pin degrades to generic text, that's the
  signal it should reference PROCESS_GUIDE instead.

## Deferred (separate future plan)

The hard guardrail — atomic `O_CREAT|O_EXCL` spawn-lock keyed by agent_type to
reject duplicate concurrent subagent spawns — pending one empirical test: does
`PreToolUse` (or `TaskCreated`) fire on subagent spawn, and what `tool_name`/
matcher does it carry? `SubagentStart` is confirmed unable to block, so that
test decides the whole enforcement design.

**This prose/injection work must NOT be tagged as resolving SMM risk
`28b167e65f2e`** — that risk is closed by the deferred hard guard, not by this
mitigation.

## Related SMM events (from this session, for traceability)

- Risk `28b167e65f2e` (the parallel-batch collision risk).
- Plan-review: concern `dbf302820763` + decision `2bf50a4ec872`
  (`guide-line-budgets`); assumptions `1354895ff058` (read-chilling),
  `1c3a39886073` (blast radius), `71bfdf62e89c` (pin boilerplate).
- Memory: `feedback_no_batch_across_xp_steps` (the durable self-instruction).

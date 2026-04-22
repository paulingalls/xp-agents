# Verbosity Audit — Reduce Token Spend Across the Plugin

## Context

Sessions are consuming more tokens than they should. Everything downstream (retros, curation input, preloads, subagent injections) composes from the same atoms — events, SMM items, retro bullets, plan text. Shrinking the atoms shrinks everything they feed.

**Principle: necessary but sufficient.** Preserve signal, reduce noise. Whiteboard discipline — if it wouldn't fit on a sticky, it's probably too long.

**Mechanism (priority order):**
1. JSON schema `maxLength` — hard enforcement at write time. Fails loud.
2. Governance prose + worked examples in writers' tools (agent prompts, `append.sh --help`, reference docs).
3. Code changes only where schema + prose can't carry the load.

**Overarching guardrail: no signal loss.** Every cut must name what's preserved, not just what's removed. If a cut can't justify "the signal still lives at X", pull it back. End-state test: same *quality* of outcome with fewer tokens. Quality regresses → cut was wrong. §8 details the signal-preservation protocol for prompt edits; the same principle governs every section.

**Compression targets by artifact class:**
- Events, retros, agent/skill prompts, always-loaded docs — aggressive (30–50% on the tail).
- SMM pillars — aggressive **via purpose audit**, not compression (see §2 per-pillar filters).
- Plans (system_context, execution_plan, sprint.json, plan files) — generous. Rework cost dwarfs token savings. ≤10% ceiling via structural dedup, not word-level compression.

**Audit methodology.** Budgets below are evidence-based: load real event logs from `xp-agents` + SimplyHuman, compute per-type length distributions (p50/p90/p95/p99/max), sample the top-25%, hand-compress representatives, set budgets at achievable Twitter-discipline levels. Audit scripts move to `plugins/xp-agents/tools/verbosity_audit/` when M1 ships.

---

## 1. Event log — content field budgets

**Current state** (2167 events ours + 3371 SH = 5538 total):

| Type | n | p50 | p90 | p95 | max |
|------|---|-----|-----|-----|-----|
| status | 3978 | ~40 | ~95 | ~250 | 962 |
| concern | 466 | ~100 | ~600 | ~720 | 1099 |
| decision | 185 | ~250 | ~600 | ~660 | 10443 |
| assumption | 80 | ~390 | ~520 | ~600 | 732 |
| debt | 64 | ~475 | ~660 | ~680 | 816 |
| question | 24 | ~485 | ~765 | ~820 | 888 |
| answer | 19 | ~480 | ~508 | ~508 | 508 |
| commit | 148 | ~830 | ~1730 | ~2075 | 3330 |
| goal | 33 | ~20 | ~110 | ~200 | 370 |

`schema.json` has no `maxLength` on any `content` field today. Events read many times downstream — retro digest, curation input, materialized SMM, skill preloads, subagent injection.

**Compression evidence (10 hand-compressed tail samples, 29-66% reduction):**

| Sample | Type | Orig | Compressed | % |
|--------|------|------|------------|---|
| e6d8e9239ace | concern | 1099 | 370 | 66% |
| 96399d761cf8 | concern | 596 | 270 | 55% |
| c5f333b3221a | debt | 816 | 395 | 52% |
| 9f6bf47efca5 | decision | 557 | 280 | 50% |
| eab9f86c6dca | decision | 829 | 420 | 49% |
| eaa75fb3d78e | assumption | 732 | 370 | 49% |
| 0994451f1ba8 | debt | 619 | 320 | 48% |
| 5d4883222679 | assumption | 539 | 290 | 46% |
| d8cda4e3bf12 | status | 352 | 230 | 35% |
| aceebfa809ff | goal | 370 | 260 | 30% |

**Worked example (concern 1099 → 370, 66%):** *"Story-002 plan misses 17 integration tests (grep) across tests/{smm,hooks,integration,engine}/ referencing xp-run-retrospective/xp-housekeeping. Plan enumerates only 4. Cycle 4 step 13's grep audit runs AFTER rewrite — breaks suite green gate. Fix: enumerate explicitly OR move grep audit before cycle 3 deletion."* — all signal preserved (17-file scope, directory pattern, cycle refs, both fix options); cut the file enumeration, narrative tissue, apologetic framing.

**Budgets:**

| Type | Budget | Type | Budget |
|------|--------|------|--------|
| status | 200 | assumption | 400 |
| commit | uncapped | discovery | 400 |
| decision | 400 | goal | 200 |
| convention | 250 | customer_intent | 250 |
| concern | 400 | sprint | 200 |
| debt | 400 | customer_input | uncapped |
| question | 450 | retrospective | 100 (pointer; see §4) |
| answer | 350 | session_end | 50 |

**Discipline note:** the 962-char "status" event filed as proposal content was an event-type misuse (should be `decision` or `retrospective` Try). Tight 200-char status budget naturally forces correct type selection — budget doubles as discipline enforcement.

**Aggregate savings:** ~40K chars sustainable on top-25% events (278 sampled events totaling 160K chars, 25% cut). Plus every downstream consumer pays per-read.

**Governance:**
- `append.sh` wrapper rejects over-budget writes with current-length + budget + trim suggestion.
- Worked-examples block in retro/housekeeper/plan-reviewer/code-reviewer prompts + `PROCESS_GUIDE.md` Recording Events section. Use the concern 1099→370 as headline example.

**Implementation:** add `maxLength` to `schema.json`; validation runs at `_append_impl.append_safe`; only new error messages needed.

**Signal-loss check:** `metadata.resolves`, `metadata.supersedes`, `references`, `files`, `topic` carry cross-event linkage independently. Shortening `content` doesn't break causal traces. Cuts strip writerly throat-clearing, file enumeration patterns can replace, narrative tense. The 10 samples confirm no signal loss at 45-55% tail reduction.

---

## 2. SMM pillars — purpose audit (drift from strategic to tactical)

**Framing.** Pillars are the shared mental model injected into every subagent — they steer how agents work together. A pillar item earns its place by steering future decisions broadly, not recording what happened once. Tactical items aren't just long — they're in the wrong artifact. Fix is relocation, not compression.

**Current state:**

| Pillar | ours (n / KB) | SH (n / KB) | Combined p50 / p90 / max |
|--------|---------------|-------------|--------------------------|
| intent | 1 / 0.5 | 2 / 1.0 | 467 / 567 / 593 |
| constraints | 21 / 4.3 | 26 / 5.5 | 205 / 383 / 450 |
| risks | 8 / 1.8 | 9 / 3.3 | 284 / 436 / 452 |
| wisdom | 10 / 1.9 | 10 / 2.0 | 171 / 292 / 563 |

Our SMM = 8.5 KB; SH's = 11.9 KB. At ~10 subagent launches/session: 85-120 KB of SMM content re-injected per session.

**Per-pillar filter (what belongs / what doesn't):**

- **Intent — project-level north-star.** Filter: "project-level or sprint/milestone-operational?" Good: "Trust-by-proof social platform: WorldID identity, federated moderation." Bad: sprint story lists, iteration groupings (belong in `sprint.json`).
- **Constraints — durable binding rules.** Filter: "binds every DB call / commit / file / hook / test in its domain?" Good: "Postgres + Drizzle + relations", "TDD — red, green, refactor, commit", "Tests are production code". Bad: "bunfig.toml `pathIgnorePatterns` excludes ONLY e2e/" (binds one config file).
- **Risks — strategic concerns.** Filter: "systemic (cross-cutting, not sprint-resolvable) or tactical (specific, sprint-resolvable)?" Good: "Agent Teams adoption unmeasured". Bad: "4 sibling debts (a1b2c3...)" — tactical items surface via §3 work-selection triage, not pillar promotion.
- **Wisdom — timeless patterns.** Filter: "will this still apply in 3 months?" Good: "Declare refactor-mode at plan time when behavior-preserving". Bad: tooling-specific troubleshooting hints (belong as code comments).

**Applying filters to current pillars — ~30-40% of content is tactical** and should relocate:

| Pillar | % strategic (keep) | % tactical (relocate) |
|--------|-------------------|-----------------------|
| Intent | 60% | 40% (operational sprint detail) |
| Constraints | 70% | 30% (tactical configs, one-shot retirement details) |
| Risks | 50% | 50% (sibling-debt enumerations) |
| Wisdom | 90% | 10% (tool-specific hints) |

**Compression evidence (7 samples, 20-46% reduction):**

| Sample | Pillar | Orig | Compressed | % |
|--------|--------|------|------------|---|
| 9c710de9d551 (SH sprint-008) | intent | 593 | 370 | 38% |
| fa27f6786183 (ours MDC) | intent | 467 | 325 | 30% |
| f642734e36f0 (SH cascade rule) | constraints | 450 | 355 | 21% |
| 1cf0cc2032c1 (ours retire) | constraints | 436 | 345 | 21% |
| 622e4563242e (SH shared-types) | risks | 452 | 310 | 31% |
| 973c68eac9fa (SH label) | risks | 448 | 240 | 46% |
| fda4bdc9599a (SH World ID) | wisdom | 563 | 425 | 24% |

Items compress less than raw events (§1 tail 46-66%) because they've survived one housekeeper pass. Bigger win is relocation, not compression.

**Budgets (aggressive, justified by purpose not size):**

| Pillar | Budget | Rationale |
|--------|--------|-----------|
| intent | 200 | Strategic north-star fits ("WorldID identity, federated moderation" = 88 chars). Misuse exceeds it, forcing proper filing. |
| constraints | 150 | Durable binding rules fit ("Postgres + Drizzle + relations" = 34; "TDD — red, green, refactor, commit" = 38). Longer = tactical. |
| risks | 200 | Strategic concerns. Slightly more room for scope framing. |
| wisdom | 150 | Proven patterns ("Declare refactor-mode at plan time" = 60). |

**Governance:**
- Housekeeper prompt: per-pillar purpose + filters + one good/bad example each. Curation-by-purpose, not promotion-by-activity. Fails filter → do NOT promote; write/keep as event.
- `smm_cli.py` mutations validate `maxLength` per pillar at CLI boundary.
- One-shot housekeeper migration pass: apply filters across both projects; relocate tactical items, compress strategic ones.

**Aggregate savings:** ours 8.5 KB → ~5.1 KB (40%); SH 11.9 KB → ~6.2 KB (48%). × ~10 subagent launches/session = **40-55 KB/session** just on SMM injection, plus knock-on reductions in curation input + retro digest + preloads.

**Signal-loss check.** No signal lost — tactical content relocates to `events.jsonl` (source of truth); aging/escalation moves to compute-at-consumption-time (§3 work-selection preload + retro digest). Strategic references preserve cross-links via `metadata.references` / `metadata.resolves`. The pillar loses its "passive ambient reminder" function; that function moves to active triage at work selection (§3), more explicit and harder to ignore.

---

## 3. Triage surfaces — work selection for debts / concerns / questions

**Framing.** §2 removes tactical debts/concerns/questions from the Risks pillar. Without a replacement surface they'd drift. Work selection picks up the function as *active triage* rather than *passive injection*.

**Current state.** Work selection already triages retro Tries at kickoff (adopt/defer/drop). Tactical items escalate via housekeeper pillar promotion + aging markers (⚠️ 4+ sessions, 🔴 7+), surfaced indirectly through retro Fix items. Problem: pillar carries aging state as shadow data, escalation isn't a triage moment, user's attention isn't explicitly drawn to decide.

**Proposed flow.** Work-selection preload scans `events.jsonl` for unresolved tactical items and presents three new triage sections after retro Try review. **UX note (coupled with §4.1 Try cap at 4):** Try triage fits exactly one `AskUserQuestion` invocation; each new section is its own call, respecting the 4-question grouping limit. No pagination logic.

**3.1 Open Debts.** Scan `events.jsonl` for `debt` events without `metadata.resolves` on a subsequent `commit`/`decision`/`status`. For each: compute age; elevate if `debt.files` intersects `story.file_domain` (contextual — cheap to pay now). Triage: **adopt-now** (pull into sprint), **keep-deferred** (record `status` with `disposition=deferred`), **drop** (record `status` with `disposition=dropped` + rationale).

**3.2 Open Concerns.** Scan unresolved `concern` events. Group by severity (high → medium → low). Same triage options as debts.

**3.3 Open Questions.** Scan unresolved `question` events. Group by priority: 🔴 blocking (must triage), 🟡 assumed aged N+ sessions, 🟢 info (opt-in). Triage: **answer-now** (`answer` event with `metadata.resolves=[question_id]` via AskUserQuestion "Other" freeform), **keep-open** (status `disposition=keep-open`), **drop** (status + rationale).

**Aging moves to `materialize.py`** — extract `compute_aging(events, event_type, cutoff_sessions)` helper used by both work-selection preload and retro digest builder. Today aging markers applied by housekeeper at promotion time; with pillar-promotion gone, computed at consumption from event timestamps.

**Complementary channels preserved:**

| Artifact | Kickoff triage | Mid-session | Session-end / retro |
|----------|----------------|-------------|---------------------|
| Retro Tries | work selection | (set at kickoff) | retro agent next session |
| Debts | work selection | /xp-quality-review opportunistic fix | retro Fix escalation |
| Concerns | work selection | `metadata.resolves` on commits | retro Fix escalation |
| Questions | work selection | `answer` event with `metadata.resolves` | session-end wisdom |

**Recommended changes.** Extend `prepare_work_selection.py` with three new triage sections. Extract `materialize.compute_aging`. Extend `work_selection_decide.py` with debt/concern/question subcommands. Update `xp-work-selection/SKILL.md` with new steps. Update `xp-housekeeper.md` to stop tactical pillar-promotion. Update `xp-retrospective.md` to read `digest.aging_*` from digest instead of pillar.

**Signal-loss check.** Pillar was a passive ambient reminder. New flow centralizes at one kickoff moment per session. Risks: user skips work selection → retro's `digest.aging_*` still surfaces in Fix items (two surfaces, not one). File-intersection contextual elevation provides mid-flow relevance for stories touching known-debt files. Net: tighter, more explicit triage with no ambiguity about whether the user acknowledged the item.

---

## 4. Retrospective — JSON + event + digest

**Current state** (11 retros ours + 15 SH = 26 total):

| Field | n total | Per-retro avg | Combined p50 / p90 / max |
|-------|---------|---------------|--------------------------|
| keep items | 185 | 7 | 417 / 562 / 857 |
| fix items | 143 | 5.5 | 500 / 697 / 1039 |
| try items | 130 | 5 | 462 / 626 / 962 |
| retro file | — | ~11 KB | — |

**Three data surfaces:**
1. `retrospectives/<ts>.json` — full K/F/T + `analysis_notes`. ~11 KB avg.
2. `retrospective` event in `events.jsonl` — **already pointer-shaped** (48 chars: "Session retrospective: N keeps, M fixes, K tries"). No duplication. No change needed.
3. `.retro-input.json` — built by `retrospective.py` + `retro_history.gather_retro_history()`, loaded by retro agent at kickoff. Carries slimmed `previous_retros`.

**Two confirmed bugs, must ship together:**

**Bug 1:** `retro_history.py:14` has `MAX_RETRO_HISTORY = 2`. Current `.retro-input.json` verified: carries 2 previous retros. `annotate_try_status` uses `[0]` only. **Fix: `MAX_RETRO_HISTORY = 1`.** Saves ~5 KB per `.retro-input.json` build.

**Bug 2:** `gather_retro_history` slims each retro to `{timestamp, keep, fix, try}` — **drops `analysis_notes` entirely**. The field that's supposed to carry cross-session trends forward has never worked as a read path. **Fix: add `analysis_notes` to the slim.**

Compound: reducing `MAX_RETRO_HISTORY=1` strips one retro's context; `analysis_notes` then supposed to carry multi-session signal forward but doesn't. Both fixes required together.

**Compression evidence (3 tail samples, 39-58% reduction):**

| Sample | Section | Orig | Compressed | % |
|--------|---------|------|------------|---|
| Keep (9 commit refs) | keep | 857 | 360 | 58% |
| Fix (10 debt IDs) | fix | 1039 | 520 | 50% |
| Try (debt-payment sprint) | try | 962 | 590 | 39% |

Structural pattern: long items carry ID+tag lists wrapped in narrative prose — IDs are load-bearing; prose isn't.

**Budgets:**
- `keep[].content` ≤ **250**
- `fix[].content` ≤ **300**
- `try[].content` ≤ **300**
- `try` array **`maxItems: 4`** (see §4.1)
- `analysis_notes` ≤ **600** (cross-session trend carrier, the field previous_retros=2 was compensating for)

### 4.1 Try cap at 4

**Why:** Try items carry forward across sessions — adopted-but-unexecuted Tries roll forward and keep re-appearing. Current retros avg 4.9 Tries (ours) max 7; 5th+ Try is often merge-of-two, carry-forward-that-should-be-Wisdom, or non-experiment-observation.

**Three reasons for the cap:**
1. **AskUserQuestion fits.** Tool accepts 1-4 questions. At 4 Tries max, Try triage = one call. Current 5-Try retros force two invocations.
2. **Forces retro quality.** >4 candidates → agent must *merge similar Tries*, *promote proven carry-forwards into Wisdom*, *reclassify non-experiments as Fix or events*, *drop lowest-value*.
3. **Reduces carry-forward drift.** Smaller `previous_retros.try` payload; less adopted-but-unexecuted noise.

Scope: Try only. Keep and Fix don't carry the same forward-pressure.

**Schema enforcement.** Retro JSON schema (new `smm/retro_schema.json`): `try: {type: "array", maxItems: 4}`. `save_retrospective.py` rejects >4 at write time.

**Retro agent prompt — three coordinated directives** (all required for `analysis_notes` to serve its purpose):
- **Write-side:** "Populate `analysis_notes` (≤600 chars) with cross-session trends this session's K/F/T don't fully capture. Examples: 'Nth consecutive retro proposing debt-payment sprint', 'Risks pillar growing'."
- **Read-side:** "Before analyzing, read `previous_retros[0].analysis_notes`. Factor trends into your analysis; increment ('8th' → '9th consecutive'); drop resolved trends noting in Keep with resolver ID."
- **Whiteboard framing on K/F/T:** "Sticky notes, not paragraphs. State observation, name IDs, stop. IDs+tags use comma-separated structure, not prose. Worked example: [Fix 1039→520 above]."
- **Try-cap guidance:** "Max 4 Try items. >4 candidates → merge / promote-to-Wisdom / reclassify / drop-with-count-noted. Schema rejects >4 at save."

**Aggregate savings:** `.retro-input.json` build: ~16 KB → ~4 KB (**75% cut**), ~12 KB saved per kickoff. Retro file on disk: avg 11 KB → ~6-7 KB (35-40%).

**Implementation:**
1. `retro_history.py:14` → `MAX_RETRO_HISTORY = 1`. Update tests.
2. `retro_history.py:52-61` → include `analysis_notes` in slim. Add test.
3. Add `smm/retro_schema.json` (per-item `maxLength` + `try maxItems 4`). Wire into `save_retrospective.py`.
4. Update `agents/xp-retrospective.md` with three coordinated directives + worked example.

Steps 1+2 MUST ship together — reducing `MAX_RETRO_HISTORY` without `analysis_notes` fix strips cross-session context with no replacement carrier.

**Signal-loss check.** `MAX_RETRO_HISTORY=2→1` loses one retro's direct context; `analysis_notes` carries trend signal forward. Retro agent also reads event log's unanalyzed events — plenty of signal. Item-level compression = same shape as §1: preserve IDs, file paths, counts, cause→effect; cut narrative framing, restated context.

---

## 5. System context, execution plan, sprint.json — plan surface audit

**Framing.** Generous with plans — rework cost from under-specified plans dwarfs token savings. 10% reduction applies to **composite plan surface**, not per-file. Primary mechanism: **structural dedup**, not word-level compression.

**Plan-mode read path (ideal, each layer distinct concern):**

| Layer | File | Concern |
|-------|------|---------|
| 1. Architecture | `system_context.md` | WHERE this fits (product, stack, hook API, modules). Read once/session. |
| 2. Milestone | `execution_plan.json[milestone].{design_details,constraints,sources}` | WHY + key decisions + scope. Read entering plan on any story in milestone. |
| 3. Story | `sprint.json[story].{context,file_domain,interface_contracts,acceptance_criteria}` | WHAT this story uniquely does. Read planning this story. |
| 4. Design doc | linked via `sources` / `design_sources` | FULL RATIONALE + data. Read on demand at decision points. |

When layers stay in their lanes, dedup saves tokens without losing signal. When they leak (story context re-states milestone rationale), plan mode pays per read AND maintenance cost multiplies.

**Current state:**

| File | ours | SH |
|------|------|-----|
| `system_context.md` | 25.7 KB / 189 lines | 21.1 KB / 178 lines |
| `execution_plan.json` | 14.5 KB / 4 milestones | 18.8 KB / 5 milestones |
| `sprint.json` | 8.1 KB / 2 stories | 12.3 KB / 5 stories |
| **Total** | **~48 KB** | **~52 KB** |

**Duplication evidence.** Our story-001 context (1766 chars) rehearses ~400 chars of rationale already in M2 `design_details` AND `constraints` AND (as a derived constraint) the SMM pillar. Four layers saying the same thing ("domain_accuracy is dominated by story size + attribution... retire, not rename... cascade_size informational, no threshold..."). Plan mode reads all four; pays tokens for each copy. Story-unique content is ~500 chars of mechanical "update these tests, update this line."

**Per-layer responsibility + budgets:**

- **`system_context.md`** — audit redundancy with CLAUDE.md + PROCESS_GUIDE (§7). 30-40% cuttable. Keeps: product statement, stack, module inventory, hook API reference, arch-level conventions. Cuts: inventory prose that drifts (skills count, file counts).
- **`execution_plan.json[milestone]`:** `.goal` ≤ **200**, `.done` ≤ **300**, `.design_details` ≤ **500** (full rationale → linked design doc), `.constraints[]` ≤ **150** each, `.change_zones[].note` ≤ **150** each, `.sources` always present.
- **`sprint.json[story]`:** `.context` ≤ **600** (what THIS story uniquely does — mechanical specifics, AC summary, file-count scope. **Do not restate milestone rationale.** Example opening: *"Milestone M2 retires domain_accuracy (see execution_plan.json M2 for rationale). This story handles the sizing_metrics + retro-agent half: ..."* — ~400 chars). `.file_domain[]` ≤ **200** each. `.interface_contracts` uncapped (rare, load-bearing). `.acceptance_criteria` uncapped. `.design_sources` always present.
- **Plan files (`~/.claude/plans/*.md`):** no budget. Plan reviewer is the signal, not length cap.

**Plan-mode/teammate-spawn procedure must change** (structural dedup only works if readers follow pointers):
1. `/xp-plan` skill prompt: planning a story → explicitly read `execution_plan.json` milestone (`design_details`, `constraints`, `sources`) BEFORE going deep on the story.
2. Teammate spawn prompt must include milestone context + story context (not just story). Update prompt-writing logic in `spawn_teammate.py` or teammate prompt template.
3. `/xp-review-plan`: flag "story context rehearses milestone rationale" as **redundancy concern**, not density feature.

**Stronger governance via JSON migration.** `system_context.md` is the only plan-artifact still stored as free-form markdown (others are JSON-with-schema-with-render-CLI). Converting enables per-field `maxLength` (same discipline as §1/§2), targeted section reads, runtime-derived inventory fields (no drift), and ecosystem consistency. Generic-core schema + `project_specific` extension point keeps it portable across projects (xp-agents = hook API + SMM engine; React webapp = component library + routing). Own initiative — 4 stories, ships after M1 establishes schema patterns. See **[SYSTEM_CONTEXT_JSON_MIGRATION.md](SYSTEM_CONTEXT_JSON_MIGRATION.md)**.

**Aggregate savings (composite plan surface):** ours 48 KB → ~34 KB (**29% composite**). Above 10% ceiling but via relocation (content lives in canonical home), not deletion. User-warned caution: ship dedup + read-path updates in same sprint; measure reviewer insufficiency concerns for 2-3 sprints; relax budgets if needed.

**Implementation:**
1. Add `maxLength` to `execution_plan_schema.py` + `sprint_schema.py`.
2. Update `xp-plan.md`, `xp-sprint-start.md`, `xp-plan-reviewer.md` prompts: layer-responsibility framing + dedup guidance + story-001-vs-M2 worked example.
3. Update teammate spawn path to include milestone context.
4. system_context.md trim pass per §7.
5. Migration housekeeper/plan-author pass to apply layer responsibility.

**Signal-loss check.** All layers remain on disk — nothing deleted. Tight story context + full milestone `design_details` + linked design doc collectively carry same signal. Plan reviewer reads all four layers — flags genuine insufficiency, not just redundancy. Teammate spawn explicitly loads milestone context. Rollback cheap: relax story-context budget (600→800) if reviewer insufficiency concerns fire.

---

## 6. Hook-injected context

**Five injection surfaces; four action items, one already lean.**

**6.1 PROCESS_GUIDE injection.** `review_cycle_done.py:73` (once per `/xp-kickoff`) + `session_start.py:141-143` (on `source=="compact"`). Current 10.9 KB / 201 lines, fires 1-3x/session. **No §6 work — covered by §7 tightening (10.9 KB → ~5.5 KB via cuts + CLI-usage tables moved to `--help`).** Injection pattern is correct; only file size is the lever.

**6.2 Open-questions nudge on decision Bash.** `pre_tool_bash._open_questions_context` (lines 53-75). Fires every `append.sh --type decision` lacking `--metadata '{"resolves":[...]}'`. ~80-char header + ~120 chars/question (truncated 80). **No dedup today** — 5 decisions × 3 open questions = 2.2 KB repeat injection. **Action: per-(question_id, agent_id) fire counter via marker files. After N=2 fires, mute until question resolves or SessionEnd.** Marker `QUESTION_NUDGED` (agent-scoped, counter JSON payload), cleared on question resolution or SessionEnd via `_AGENT_SCOPED_MARKERS` registry. Saves ~60% on this surface.

**6.3 SubagentStart tier injection.** `subagent_start.py` dispatch:

| Agent type | Injects | Today | After §2 |
|------------|---------|-------|----------|
| `Explore` | Intent + Constraints + XP values | ~5 KB | ~3.3 KB |
| `xp-code-reviewer` / Default (Plan, general-purpose) | Full SMM + XP values | ~10 KB | ~6 KB |
| `xp-retrospective` | SMM_DIR + RETRO_INPUT paths + XP values | ~1.6 KB | same |
| `xp-housekeeper` | curation-input path + work_selection + XP values | ~1.5-3 KB | same |
| Other `xp-*` forked | XP values only | ~1.4 KB | same |

Session aggregate (~10 launches): today ~59 KB; after §2 ~40 KB (~32% via §2 rollup). **No dispatch change recommended** — Explore-tier Constraints trim saves ~2 KB but incremental after §2 makes Constraints strategic-only. Docstring comment "~200 tokens" (line 6) is stale — actual Explore injection ~5 KB post-framing; update during §8 skill/agent pass.

**6.4 prompt_nugget (UserPromptSubmit).** Max 3 items × 120 chars + header = ~400 chars max. Watermark-based delta, noisy-auto-concerns filtered. **Already lean — no action.** Rides §1 event compression for incremental reduction.

**6.5 TASK_CREATION_NUDGE.** 180 chars × once-per-plan-review. Negligible. **No action.**

**§6-specific changes:** (1) open-questions nudge dedup cache (§6.2) — the only §6-unique code change. (2) SubagentStart docstring comment cleanup (during §8). PROCESS_GUIDE savings ride §7; SubagentStart tier savings ride §2.

**Aggregate §6-specific savings: ~1-2 KB/session** (dedup cache). Most per-session savings from §2 and §7 landing in these same injection surfaces.

**Signal-loss check.** Open-questions dedup: after 2 nudges an agent hasn't absorbed, 3rd-Nth teaches nothing. Question still shows in retro Fix, work-selection triage (§3), and SMM if promoted. Multiple surfaces. SessionEnd clears markers so next session starts fresh.

---

## 7. PROCESS_GUIDE.md, CLAUDE.md, XP_VALUES.md — always-loaded docs

**Three files, three audiences:**

| File | Audience | Shipped with plugin? | Injection |
|------|----------|----------------------|-----------|
| `CLAUDE.md` | Plugin developers only (us) | **No** — only in xp-agents repo | Every turn (harness) |
| `PROCESS_GUIDE.md` | Plugin users (any installed project) | **Yes** | Once per kickoff + each compact |
| `XP_VALUES.md` | Plugin users | **Yes** | SessionStart + every SubagentStart |

**Critical scoping rule.** CLAUDE.md NOT shipped. Plugin users have their own CLAUDE.md. **PROCESS_GUIDE.md must be self-sufficient for plugin behavior.** Cross-file dedup one-directional: CLAUDE.md may lean on PROCESS_GUIDE.md; PROCESS_GUIDE.md may NEVER lean on CLAUDE.md.

Per-turn injection (CLAUDE.md) = highest compound impact for us. 9 KB cut × 50-turn session = ~450 KB.

**Current state:**

| File | Bytes | Lines |
|------|-------|-------|
| `CLAUDE.md` | 16.9 KB | 316 |
| `PROCESS_GUIDE.md` | 10.9 KB | 201 |
| `XP_VALUES.md` | 1.4 KB | 15 |

### 7.1 CLAUDE.md → ~115 lines / ~8 KB (53% cut)

**Keep:** project identity (lines 3-7), coding standards (21-29), Key Decisions list (292-309), Error Handling principles (183-191), Further Reading (311-316).

**Cut/compress:**
- **Hook Patterns (31-92, 60 lines) → ~12 lines.** Keep *minimum-viable code-shape comments* as recognition triggers (command input read, block pattern, inject pattern, agent/prompt return shape, recursion-prevention); full detail in hooks reference (already linked).
- **Official Claude Code Docs (9-19) → 2 lines.** Docs-index link only (`https://code.claude.com/docs/llms.txt`).
- **SMM Path Resolution (94-105) → 3 lines.** Init.sh rule + user-level path note (shape as code comment).
- **Event Appending partial table (107-118) → delete.** Subset of PROCESS_GUIDE canonical table.
- **Hook Registration example (120-149, 30 lines) → 2 lines.** Link to plugins reference.
- **Platform Constraints (151-165) → 5 lines.** Keep only points hooks reference doesn't clearly document (`additionalContext` unsupported events, Stop-parallel).
- **File Structure tree (167-181) → 3 lines.** Counts drift — remove numeric inventory.
- **Test layout tree (213-271, 59 lines) → delete.** Pure filesystem duplication.
- **Test helpers list (283-290) → delete.** Discoverable via imports.
- **Writing new tests (273-281) → 4 lines.** Compressed procedure.
- **Testing run commands (193-209, 15 lines) → 4 lines.** Keep full-suite + one single-file example.

### 7.2 PROCESS_GUIDE.md → ~95 lines / ~5.5 KB (49% cut)

**Keep mostly verbatim:** Resolution Discipline (3 link types), When to Run XP Skills (plan/commit/sprint cycles), File Domain Discipline, forked vs inline skills, Project Files, Event Types table, Question Priority, `Resolves-Event:` trailer example.

**Cut/compress:**
- **Practicing the Values (3-17, 15 lines) → 5 lines.** Compress to list: *"Honesty: ground truth in SMM. Communication: record why not what. Feedback: act on review findings. Courage + Simplicity: see XP_VALUES.md."*
- **CLI Tools section (72-93, 22 lines) → 1 line pointer.** Subcommand lists move to each CLI's `--help`.
- **Recording Events example (99-105, 7 lines) → 4 lines.** Minimum-viable `append.sh` shape + pointer to `--help`.
- **`working_on` / `references` fields (139-153, 15 lines) → 4 lines.** Rule + minimum-viable shape.
- **Common Recording Patterns (174-199, 25 lines) → 6 lines.** Keep four canonical shapes (status / decision / debt / assumption) as one-line `append.sh` invocations + pointer to `--help`. These are **recognition triggers** — cutting them entirely loses "I should file this event" prompts; compressing them preserves the trigger role.

### 7.3 XP_VALUES.md — no change

15 lines, ~300 chars per value + precedence. Atomic. Ship as-is.

### Aggregate

| File | Before | After | Cut |
|------|--------|-------|-----|
| CLAUDE.md | 16.9 KB / 316 | ~8 KB / ~115 | 53% |
| PROCESS_GUIDE.md | 10.9 KB / 201 | ~5.5 KB / ~95 | 49% |
| XP_VALUES.md | 1.4 KB / 15 | unchanged | 0% |

**CLAUDE.md is the single highest-leverage cut in the audit** — injected every turn. 20-turn session saves ~180 KB.

### Relocation (content moves, not deletes)

**CLAUDE.md cuts (plugin-dev only):** → Claude Code hooks/plugins references, filesystem (`ls tests/`), PROCESS_GUIDE.md canonical table, lefthook.yml.

**PROCESS_GUIDE.md cuts (MUST ship with plugin):** → `sprint_cli.py --help` / `plan_cli.py --help` / `smm_cli.py --help` / `retro_cli.py --help` / `append.sh --help`. **Never relocate to CLAUDE.md** — plugin users don't have it.

**`--help` discipline becomes load-bearing for plugin users.** Every CLI's `--help` must carry compact example-rich subcommand/flag/pattern description. Enriched `--help` ships before (or together with) PROCESS_GUIDE cuts.

### Implementation — two independent workstreams

**Workstream A (plugin users):** CLI `--help` enrichment + PROCESS_GUIDE cuts. MUST ship together. Smoke test on fresh *installed-plugin* project (not xp-agents repo): agent can author events, run tests, follow plan/commit cycles from PROCESS_GUIDE.md + CLIs' `--help` alone.

**Workstream B (plugin dev):** CLAUDE.md tightening. Independent. Smoke test on xp-agents repo.

**Order:** A first (user-facing, per-kickoff compounded). B anytime after.

### Signal-loss check

- **Minimum-viable examples preserved** as recognition triggers — every pattern the guide showed still has a one-line code-shape form. Full flag lists in `--help`.
- **All cut content relocates**, never deletes.
- **`--help` is agent-native** — agents already run `<cmd> --help` reflexively.
- **Key Decisions list preserved** in CLAUDE.md.
- **Rollback cheap** — if agents make avoidable mistakes, re-inline the failed section. Measurable signal: retro Fix items "should have known X".

---

## 8. Agent + skill prompts

**Current state (measured):**

**Agents (7 files, 967 lines):**

| File | Lines | Touched by other sections? |
|------|-------|----------------------------|
| `xp-retrospective.md` | 233 | §4 (analysis_notes + whiteboard + Try cap). Has stale `previous_retros 2-3` line. |
| `xp-housekeeper.md` | 206 | §2 (per-pillar purpose filters) + §3 (stop pillar-promoting tactical). |
| `xp-plan-reviewer.md` | 152 | §5 (dedup-across-layers as review concern). |
| `xp-code-reviewer.md` | 138 | None — needs §8-only pass. |
| `xp-system-analyzer.md` | 105 | SYSTEM_CONTEXT_JSON_MIGRATION. |
| `xp-sprint-reviewer.md` | 88 | None — needs §8-only pass. |
| `xp-security-reviewer.md` | 45 | Already tight. No action. |

**Skills (11 files):**

Heavy (inline):
| File | Lines | Touched? |
|------|-------|----------|
| `xp-plan/SKILL.md` | 174 | §5 + SYSTEM_CONTEXT_JSON_MIGRATION. |
| `xp-sprint-start/SKILL.md` | 163 | §5 + SYSTEM_CONTEXT_JSON_MIGRATION. |
| `xp-assign/SKILL.md` | 140 | None — §8-only. |
| `xp-quality-review/SKILL.md` | 129 | Minor §3; mostly §8-only. |
| `xp-work-selection/SKILL.md` | 115 | §3 (expands with triage sections — §8 must integrate so expansion stays tight). |
| `xp-kickoff/SKILL.md` | 98 | §4 (retro reads analysis_notes). |
| `xp-accept/SKILL.md` | 90 | None — §8-only. |

Light (forked, all already tight — no action): xp-system-context (24), xp-sprint-review (20), xp-security-triage (19), xp-review-plan (19).

**Integration framing (task #5 discipline).** Most prompts edit on the path of §2/§3/§4/§5/§7. §8 adds: **as we edit each prompt for other sections' purposes, also tighten the prompt itself.** Don't let "add directive" become "net-growth." Integrated tightening prevents monotonic growth.

### Bloat-pattern checklist (from sampling xp-retrospective + xp-plan)

| Pattern | Fix |
|---------|-----|
| Verbose role framing ("You are the X in an XP workflow...") | 1-2 lines: role + input + output |
| Exhaustive input-JSON field documentation | Field list with 1-word semantics |
| Section headers + bullets restating the header | One-line prompt + bullets |
| "Why this mechanism exists" prose | One sentence when the rule stands alone |
| Scattered safety notes | Consolidated Boundaries block |
| Full code examples where shape suffices | Minimum-viable shape + `--help` pointer |
| Procedural verbosity across overlapping sections | Numbered procedure + single Boundaries section |
| Stale directives (e.g., `previous_retros 2-3`) | Sweep with dependent-section change |

**Targets:**
- Heavy agents: ~35% avg reduction. xp-retrospective can hit ~45% (prose-heavy).
- Heavy skills: ~30% avg reduction.
- Light files: no action.

**Aggregate:** heavy prompts sum to ~1550 lines / ~55 KB. At ~30% = ~17 KB cut. Plus per-subagent-launch savings ongoing.

### Signal-preservation protocol (applies to every prompt edit in §2-§7 rollouts AND §8)

Prompt regressions are the highest-risk failure mode — cut a load-bearing directive and the agent makes avoidable mistakes that cost far more (rework) than tokens saved.

**Before the cut — enumerate what must survive:**
1. Every directive (do X / do not Y).
2. Every conditional branch ("If X, then Y; else Z").
3. Every recognition trigger — minimum-viable examples, code shapes, pattern comments.
4. Every concrete reference — file paths, function names, event IDs, thresholds, field names.
5. Sequence/ordering constraints.

**Fair game for removal:** narrative framing, "why this exists" prose when the rule stands alone, section-header-restatements, redundant qualifiers ("carefully", "thoroughly"), full code examples where shape+`--help` pointer serves, scattered safety notes (consolidate, don't delete).

**Commit justification:** message names removed + preserved. *"refactor(xp-retrospective): 233→130 (44%). Removed: role framing, why-flags-precomputed prose, scattered Don't-X notes (consolidated). Preserved: all directives (compressed), XP values lens list, digest field semantics (list form), Resolves-Event trailer example."*

**Verification:** directive-checklist diff, smoke test (representative input, output quality vs prior baseline), stale-reference scan.

**Post-merge monitoring.** First retro after prompt-tightening sprint MUST flag "should have known X" patterns as Fix linked to commit. Three such flags in one sprint = pause §8-style cuts; refine checklist.

**One file per commit** — cheap bisect, easy rollback.

### Implementation — integrate with other milestones

- **M4 + M5** (housekeeper + triage): apply §8 checklist during rewrites.
- **M6** (retro fixes): apply §8 during `xp-retrospective.md` + `xp-kickoff/SKILL.md` edits.
- **M7** (plan dedup): apply §8 during `xp-plan/SKILL.md`, `xp-sprint-start/SKILL.md`, `xp-plan-reviewer.md` edits.
- **M3a** (PROCESS_GUIDE + `--help`): bloat-pattern principles apply to docs/`--help` too.
- **SYSTEM_CONTEXT_JSON_MIGRATION:** apply §8 to `xp-system-analyzer.md` rewrite.
- **M9 — dedicated §8 mini-sprint** for the 5 untouched files: `xp-code-reviewer`, `xp-sprint-reviewer`, `xp-assign`, `xp-quality-review`, `xp-accept`. Ships after M4-M7 so bloat-pattern discipline is established and lessons learned.

**The integration discipline matters more than any single cut.** Prompt that gets "add directive × 3 sprints without tightening" becomes 50 lines longer. Prompt tightened during each edit stays flat or shrinks.

---

## 9. Curation input (materialize.prepare_curation_data)

**Biggest single artifact in the plugin — 337 KB ours / 392 KB SH per kickoff.** Housekeeper Reads the whole file at curation time; every KB costs tokens once per session. Reducing this = single largest per-kickoff win.

**Current state:**

| Section | ours | SH | % |
|---------|------|-----|---|
| `new_since_last_curation.customer_inputs` | 147 KB | 117 KB | 49% / 34% |
| `new_since_last_curation.resolutions` | 82 KB | 80 KB | 27% / 23% |
| `new_since_last_curation.decisions` | 30 KB | 63 KB | 10% / 18% |
| `new_since_last_curation.debt/assumptions/concerns/questions` | ~40 KB | ~78 KB | 13% / 23% |
| `retro_history.adopted_tries` | 22 KB | 34 KB | 7% / 10% |
| `current_smm` | 14 KB | 18 KB | 4% / 5% |
| `retro_history.latest_tries` / aging / health | ~4 KB | ~4 KB | small |

**Consumer analysis (what housekeeper actually DOES):**

| Field | Use | Data actually needed |
|-------|-----|----------------------|
| `current_smm` | Merge context | Full pillar render (~5 KB after §2) |
| `customer_inputs` | "Deliverable outcome (intent) or task (skip)?" | Content gist (~200 chars) + id |
| `resolutions` | Membership check: "is this id resolved?" | **Just a set of resolved IDs.** Resolver content unused. |
| `decisions` | "Would another agent need to know this to avoid conflict → Constraint" | Content (compressed under §1) + topic + id |
| `concerns/assumptions/debt/questions` | "Systemic enough for Risk?" (tactical items surface via §3) | Content (§1) + type + severity + files + id |
| `retro_history.latest_tries` | Wisdom promotion | Full content (§4 compressed), ≤5 items |
| `retro_history.adopted_tries` | "Adopted + worked? → promote" | **Last N=10** — older already absorbed or dropped |
| `aging` | 6+ session flags | ID → age dict. Keep. |
| `health` | Pillar health warnings | Keep. |

### Five findings

**F1 (biggest structural win): resolutions over-structured.** Currently `{resolved_id: "resolver description"}`. Housekeeper rule is pure membership. **Fix: dict → list of IDs.** 82 KB → ~3 KB (**96% cut**). Resolver descriptions never quoted/acted on; if future judgment needs them, `smm_cli.py get-event <id>` serves on-demand.

**F2 (customer_inputs — normalize, don't filter).** AskUserQuestion answers ARE legitimate user signal — the user making a decision. But serialization is bloated (~440 chars of JSON for a ~20-char choice). The housekeeper's Intent-curation rule uses gist, not full payload.

**Fix (two layers):**
- **Normalize at producer.** Detect AskUserQuestion-shaped customer_inputs (content parses as JSON with `questions`+`answers`); re-serialize as `"Q: <question> → A: <answer[s]>"`. Drops Claude-generated option descriptions; preserves user decision context + choice. Example: `~440 chars → ~70 chars`.
- **Truncate long typed prompts to 300 chars.** Attach `content_truncated: true` flag. Housekeeper `get-event` for full body if judgment hinges on detail.

Combined: 147 KB → ~40 KB (**73% cut**).

**F3 (adopted_tries cap to 10).** Current 49-67 full Try bodies across all retros. Older Tries are already absorbed into Wisdom or dropped. Only recent adopted tries are promotion candidates. **Fix: cap `adopted_tries` to last N=10** (most recent). Additional knock-on from §4 retro-item 300-char cap. 22 KB → ~5 KB (**77% cut**).

**F4 (rides §1).** decisions/concerns/debt/assumptions/questions — fields structured correctly; content shrinks ~40% naturally when §1 event budgets land. ~70 KB → ~42 KB.

**F5 (rides §2).** `current_smm` — 14 KB → ~5 KB (64%) from §2 purpose audit.

### Aggregate savings

| Section | Before | After | Cut |
|---------|--------|-------|-----|
| customer_inputs | 147 KB | 40 KB | 73% (F2) |
| resolutions | 82 KB | 3 KB | 96% (F1) |
| decisions/concerns/debt/etc. | ~70 KB | ~42 KB | 40% (rides §1) |
| adopted_tries | 22 KB | 5 KB | 77% (F3) |
| current_smm | 14 KB | 5 KB | 64% (rides §2) |
| latest_tries / aging / health | ~4 KB | ~4 KB | 0% |
| **Total** | **~339 KB** | **~99 KB** | **~71%** |

**Per-kickoff saving: ~240 KB ≈ ~60K tokens** at each housekeeping step.

### On-demand deep-read fallback

Add `smm_cli.py get-event <id>` for targeted reads. Same pattern as §2 pillar items carrying `source_event_id`. Housekeeper prompt addition: *"If you need the full body of a truncated customer_input or a resolver's content, fetch via `smm_cli.py get-event <id>`. Front-load is designed lean."*

### Recommended changes

- **`materialize.prepare_curation_data`:**
  - Convert `resolutions` dict → list of resolved IDs.
  - Detect AskUserQuestion customer_inputs; re-serialize `"Q: <question> → A: <answer>"`.
  - Truncate typed-prompt `customer_input.content` to 300 chars; set `content_truncated: true`.
  - Cap `retro_history.adopted_tries` to last N=10.
- **`smm_cli.py`:** add `get-event <id>` subcommand.
- **`xp-housekeeper.md` prompt:** document new input shape + on-demand deep-read pattern. Apply §8 tightening discipline.
- **Tests:** `materialize` tests update for new payload shape; integration test verifies housekeeper still produces correct Intent/Constraint/Risk/Wisdom calls.

### Implementation

1. **Low-risk first: resolutions dict → list.** One-line `materialize` change + housekeeper prompt update.
2. **adopted_tries cap to 10.** Same PR as F1.
3. **customer_input classifier + truncation.** Own story with AskUserQuestion-detection test.
4. **`smm_cli.py get-event`.** Ships with F3 so "fetch full content" prompt addition is actionable.
5. **Housekeeper prompt rewrite** — apply §8 discipline; document new shape; preserve behavior.

**Sequencing:** M2 in the milestone table. Structural fixes (F1/F2/F3/F4) independent of other milestones — ship any time. Rollup wins (F4+F5) land as §1/§2 ship. Ship M2 early; let rollups compound.

### Signal-loss check

Highest-stakes cut by volume. Per §8 protocol:
- **F1 resolutions → set:** housekeeper usage verified as pure membership. Future content needs served by `get-event`. Zero loss at current behavior.
- **F2 customer_inputs normalize + truncate:** user signal (question context + choice) preserved; Claude-generated option descriptions dropped. Truncation to 300 chars preserves first-order intent; `content_truncated: true` + `get-event` covers rare detail-dependent judgments. Risk: boilerplate-prefixed prompts where first 300 chars are "I need you to..." — mitigate with classifier detecting boilerplate prefixes.
- **F3 adopted_tries cap 10:** older tries already absorbed into Wisdom or dropped. Risk: slow-burn Try adopted 15 sessions ago finally "working" — mitigation: Wisdom promotion primarily driven by `latest_tries` (recent disposition) + `recurring_fixes`; adopted_tries is backup.
- **F4, F5:** validated in §1/§2 signal-loss checks.

**Monitoring.** First 2-3 housekeeping runs post-M2 compared to baseline for same items added/removed, pillar-health warnings, question events for ambiguous cases. Divergence → refine.

**Rollback cheap:** four structural changes independently revertible.

---

## Execution plan — milestones ordered by bang-for-the-buck

This doc is the design source for `/xp-plan` to consume. Each milestone maps to one section; `/xp-plan` should produce one `execution_plan.json` with these milestones, reading the corresponding section as authoritative design detail.

**Ordering principle:** session-impact magnitude. Multipliers and independent-of-dependencies wins land first; rollup-consumers land later. Dependencies noted per-milestone.

| # | Milestone | § | Primary savings | Dependencies |
|---|-----------|---|-----------------|--------------|
| **M1** | Event content budgets + schema enforcement + append.sh --help | §1 | **Multiplier** — enables §2/§4/§9 rollup wins. ~40K chars direct on tail. | None. First. |
| **M2** | Curation input structural fixes (resolutions → list, customer_input normalize+truncate, adopted_tries cap, `get-event`) | §9 | ~240 KB / ~60K tokens per kickoff. Biggest single per-event win. | None for structural fixes. Rollups land with M1/M4/M6. |
| **M3a** | CLI `--help` enrichment + PROCESS_GUIDE tightening (Workstream A) | §7 | ~5.4 KB × each kickoff+compact. Plugin-user wins. | None. Ship A-parts together (non-discoverable gap otherwise). |
| **M3b** | CLAUDE.md tightening (Workstream B) | §7 | ~9 KB × every turn for plugin devs. ~450 KB over 50-turn session. | None. Independent of M3a. |
| **M4** | SMM purpose audit + housekeeper rewrite (per-pillar filters + stop promoting tactical) | §2 | 40-48% SMM cut × subagent launches = 20-30 KB/session. | M1 (event budgets). Must ship with M5. |
| **M5** | Triage surfaces (work-selection Open Debts/Concerns/Questions + `materialize.compute_aging`) | §3 | No direct token savings — backfills pillar-promotion surface. Critical for M4 safety. | Couples with M4. Paired sprint. |
| **M6** | Retro fixes: `MAX_RETRO_HISTORY=1` + `analysis_notes` slim + retro JSON schema (K/F/T budgets + `try maxItems: 4`) + retro-agent prompt (whiteboard + analysis_notes r/w + Try-cap) | §4 | ~12 KB/kickoff on `.retro-input.json`. Two confirmed bugs resolved. | M1 (event budgets). |
| **M7** | Plan-layer dedup (execution_plan / sprint.json field budgets) + plan-reader skill updates | §5 | ~14 KB composite. Generous 10% target. | Independent. Monitor rework risk. |
| **M8** | Open-questions nudge dedup cache + SubagentStart tier docstring cleanup | §6 | ~1-2 KB/session direct. Small, bounded. | None. |
| **M9** | Dedicated prompt-tightening mini-sprint — 5 untouched files (xp-code-reviewer, xp-sprint-reviewer, xp-assign, xp-quality-review, xp-accept) | §8 | ~17 KB one-time + per-subagent-load ongoing. | After M4-M7 so bloat-pattern discipline is established. |
| **(side)** | SYSTEM_CONTEXT_JSON_MIGRATION | — | Schema enforcement + targeted reads + runtime-derived counts | See [SYSTEM_CONTEXT_JSON_MIGRATION.md](SYSTEM_CONTEXT_JSON_MIGRATION.md). Ships after M1. |

**/xp-plan consumption:** each row → one milestone. `sources` field points back to `docs/ideas/VERBOSITY_AUDIT.md §N`. Milestone fields (`goal`, `done`, `design_details`, `constraints`, `change_zones`) come from that section's `Recommended changes` + `Implementation` + `Signal-loss check` subsections.

**Shipping groupings:** M4+M5 paired (safety coupling). M3a own sprint (plugin-user A coupling). Others = own sprint OR paired by team bandwidth.

**Acceptance per milestone:** before/after token counts on a reference session + no regressions fired by the signal-loss check for 2-3 sprints.

**Cross-cutting: §8 signal-preservation protocol applies to every prompt-editing milestone.** Don't defer — upfront hygiene during each milestone.

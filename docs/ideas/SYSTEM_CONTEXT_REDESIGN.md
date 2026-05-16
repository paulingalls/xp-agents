# System Context Redesign

**Status:** Design (spike conversation, free-2026-05-15 session) — no code lands here.
**Implementation milestone:** TBD (next session).
**Companion to:** Goal #3 wiring shipped in commits `f5c6754d` + `fd1714ef` + `62bfc19e` (CLI `render --sections / --topics-only` flag + plan-reviewer + close-reviewer wiring).

The wiring shipped this session gave reviewers scoped renders of `system_context.json`. The deeper question this design answers: **what should `system_context.json` actually contain, and how do we keep it from bloating across project lifetimes?**

**TL;DR for implementers.** Five interlocking changes:
1. Drop `sources` (dead field — no consumer).
2. Rename `key_decisions` → `principles` with a sharp reversal-test definition.
3. Tighten `modules.purpose` cap from 200 → 100 chars; redefine modules as a navigation index (not architecture-retelling).
4. Add string-length + count caps on every uncapped leaf (full table in §4).
5. Add `retire-*` CLI subcommands and per-write soft/hard cap warnings.

A one-time curation pass on this project drops 27 of 42 `key_decisions` and 5 of 11 `project_specific` entries (§7).

---

## 1. The problem this design addresses

`system_context.json` is rendered into the main-agent session-start context. For this project it's currently ~27KB (~6.7K tokens) on every session. Other projects on this laptop sit at 2–5KB. Our project is a 60–250% outlier.

Audit found three drift patterns:

1. **`key_decisions` accumulated as a running diary.** 42 entries, only ~14 of which are architecturally load-bearing. The word "decision" gives no resistance — every implementation choice qualifies.
2. **`modules.purpose` strings drift toward retelling architecture_overview.** Counts and detail bleed into what should be a navigation index.
3. **`project_specific` has no definitional discipline.** Analyzer prompt says "anything that doesn't fit the generic fields." Same bloat risk as `key_decisions` — just hasn't fired yet.

Plus one true dead field:
4. **`sources` has no consumer.** Started as analyzer provenance (here's what I read), drifted across projects into file-index / important-docs-roster usage. Nothing reads it.

---

## 2. The defining insight: "decision" was the wrong word

Decisions get recorded every time someone makes one. **Principles** describe what a project *is*, not what was decided along the way. Renaming the field forces the analyzer prompt to read in a new frame and resists the diary-accumulation pattern.

### Reversal test (the central discipline)

> **A principle, reversed, makes this a different project. A constraint, reversed, makes the same project behave differently.**

Worked examples:
- `hooks-first` reversed ("agents are subagent-first") → different architecture → **principle** ✓
- `zero-dependencies` reversed ("vendored requirements.txt") → different project identity → **principle** ✓
- `four-file-architecture` reversed ("monolithic product_spec") → different data model → **principle** ✓
- `PreToolUse blocks direct commits to sprint branch` reversed → same project, different behavior → **constraint** (SMM Constraints pillar or `conventions`), not a principle
- `Use match/case for tool_name routing` reversed → same project, different code shape → **convention**, not a principle

The lens is grammatical too:
- Noun-shaped identity: "this project IS X-structured" → principle
- Verb-shaped behavior: "when X, do/don't Y" → constraint

### Why this matters separately from the rename

The word `principles` carries normative weight without diary connotations. Reading the analyzer prompt section "list this project's principles" produces a different cognitive prompt than "list this project's key decisions." The rename does part of the curation work for us.

---

## 3. Sharper definition per field

Each field gets a definition + a discriminator test to keep the analyzer (and any human editor) honest at write time.

### 3.1 `product` (existing, no change)

What the system is, who it's for, how it works. 400ch cap holds.

### 3.2 `architecture_overview` (existing, no change)

How components connect, key patterns. 750ch cap holds.

### 3.3 `stack` (existing, no change)

Languages, runtime, test_command, dependencies_policy, package_manager. `test_command` is load-bearing — read by close-skill auto-merge gates. 100ch per optional field holds.

### 3.4 `modules` (tighten)

**Definition:** navigation index for code locations. Each entry helps the agent answer "where do I put new code of type X?" or "where is functionality Y implemented?"

**Discriminator test:** Could the agent navigate to this directory to find or place code? If yes, it's a module. If it *describes the system* rather than locating code, that belongs in `architecture_overview`.

**Schema:** `{name ≤50ch, path ≤200ch, purpose ≤100ch}` (purpose tightened from 200).

**Exclude:**
- Documentation directories (`docs/` isn't a code module — docs are *about* the code, not part of it)
- Asset / binary directories with no executable role
- Empty placeholder directories
- Implementation counts / tallies ("4490 test methods", "74 hook scripts", "19 tables") — telemetry that drifts the moment anyone adds a file

**Purpose shape:** verb-shaped or noun-of-role, terse.
- GOOD: `"handles HTTP routing and request validation"`
- GOOD: `"stores domain types shared by server and mobile"`
- BAD: `"Drizzle DB layer. 19 tables across 9 schema modules + 28 pgEnums (L1-L3). Pool f..."` (counts + structural detail retold from architecture)
- BAD: `"74 command hook scripts — TDD, lint, conflicts, commit gates, Resolves-Event, prompt nuggets..."` (feature catalog)

### 3.5 `conventions` (existing shape, add count cap)

Flat list of codebase conventions. Each ≤150ch. Convention = "how this codebase is written." Distinct from SMM Constraints pillar ("how the XP process operates") — `conventions` describes the code, Constraints describes operating procedure.

### 3.6 `principles` (renamed from `key_decisions`)

**Definition:** identity statements about how this project is structured. Each entry describes what the system *is*, not what behavior is required.

**Discriminator test (the reversal test):** would reversing this make it a *different project*, or would it just make the same project *behave differently*? Different project → principle. Different behavior → not a principle; record as a convention, a code comment, or an SMM Constraints-pillar event.

**Schema:** `{topic ≤60ch, decision ≤200ch, rationale ≤200ch optional}`. Same shape as `key_decisions` minus the field name.

**Don't record:** bug fixes, version-stamped behavior changes, CLI flag additions, internal refactors, race-condition resolutions, naming conventions, status updates, "this skill does X" entries. These belong in commit messages, tests, code comments, or SMM Constraints — not here.

### 3.7 `project_specific` (sharper definition + tighter caps)

**Definition:** domain content the main agent operationally consults that doesn't fit the generic fields.

**Discriminator test:** would the agent reach for this *within the session* during execution, or is this reference material? Reference material → docs/ file. Operational domain content → here.

**Schema:** `{name ≤50ch, content ≤500ch when serialized}` — list of strings, lists, or objects all subject to the 500ch serialized cap.

**Don't record:**
- Registry-shape entries that duplicate the file system (skills/, agents/, modules/) — each component self-documents in its own .md
- Content >500ch that should be split or moved to docs/
- Status updates ("current_phase: M3", "active_milestones: ...") — these belong in execution_plan.json
- Architecture retold at section granularity

### 3.8 `branching_strategy` (existing, no change)

Stage, user_namespace, protected_branches, integration_branch, rationale. Already well-disciplined.

### 3.9 `acceptance_surfaces` (existing shape, add caps)

`{name ≤50ch, signals[] ≤100ch each, status enum, harness ≤50ch}`. Real surfaces (cli, sdk, web, api, db, mobile). Most projects have 1–4.

### 3.10 `sources` — **DROP**

True dead field. No consumer in:
- Main agent (no prompt reads it)
- Reviewers (Goal #3 subset wiring doesn't include it)
- Analyzer in update mode (no read-back instruction)
- `session_start.py` (just renders it as part of full output, no behavior)

Three projects on this laptop interpreted it three different ways (file index, key docs, doctrine roster). That divergence is the tell — without a sharp use case, the field drifts into whatever the analyzer happened to do.

Removal is a schema break, but blast radius is small: other projects re-render without it on their next `/xp-system-context` run. Schema validator should gracefully read-ignore legacy `sources` field for one release.

---

## 4. Cap table (single source of truth)

| Field | String cap | Count cap (soft / hard) | Status |
|---|---|---|---|
| `product` | 400ch | n/a | existing |
| `architecture_overview` | 750ch | n/a | existing |
| `stack.languages[]` items | **30ch** | **4 / 6** | NEW |
| `stack.*` optional | 100ch each | n/a | existing |
| `modules[].name` | **50ch** | — | NEW |
| `modules[].path` | **200ch** | — | NEW |
| `modules[].purpose` | **100ch** (was 200) | — | tighten |
| `modules[]` count | n/a | **10 / 15** | NEW |
| `conventions[]` items | 150ch | — | existing |
| `conventions[]` count | n/a | **20 / 30** | NEW |
| `principles[].topic` | **60ch** | — | NEW |
| `principles[].decision` | 200ch | — | existing (under new name) |
| `principles[].rationale` | 200ch | — | existing (under new name) |
| `principles[]` count | n/a | **15 / 20** | NEW |
| `project_specific[].name` | **50ch** | — | NEW |
| `project_specific[].content` (JSON-serialized) | **500ch** | — | NEW |
| `project_specific[]` count | n/a | **10 / 15** | NEW |
| `acceptance_surfaces[].name` | **50ch** | — | NEW |
| `acceptance_surfaces[].signals[]` items | **100ch** | 5 per surface | NEW |
| `acceptance_surfaces[].harness` | **50ch** | — | NEW |
| `acceptance_surfaces[]` count | n/a | **5 / 8** | NEW |
| `branching_strategy.*` | existing | n/a | existing |

### Worst-case render sizes under caps

- **Hard ceiling** (all caps maxed): ~34KB ≈ 8.5K tokens
- **Soft caps respected** (typical projects): ~22KB ≈ 5.5K tokens
- **Today's actual** (this project): ~27KB ≈ 6.7K tokens
- **Smaller projects** (ContactForge, Divine Ruin, SimplyHuman): 2–3K tokens — already well within

Soft caps create curation pressure without ever blocking work. Hard caps prevent runaway accumulation.

### Soft/hard cap behavior

- **Soft cap (count ≥ soft threshold):** CLI succeeds, prints stderr warning ("approaching cap N — consider whether existing entries should retire/supersede before adding more")
- **Hard cap (count ≥ hard threshold):** CLI refuses with non-zero exit and clear next-step ("hard cap reached; run `retire-<kind> <name>` to evict an entry before adding a new one")

---

## 5. CLI surface (new and changed)

### Existing subcommands (rename only)

- `add-decision` → `add-principle` (topic + content from stdin JSON)
- The other patch CLIs (`add-module`, `add-convention`, `add-acceptance-surface`, `edit-stack-field`, `edit-branching-field`) keep their names.

### New subcommands

- `retire-principle <topic>` — removes by topic
- `retire-module <name>` — removes by name
- `retire-convention <index-or-substring>` — removes by index or substring match
- `retire-project-specific <name>` — removes by name
- `retire-acceptance-surface <name>` — removes by name

All retire commands emit a status event for traceability (matches SMM curation patterns).

### Modified validation

- `validate` subcommand reports over-soft counts in addition to over-budget strings.
- `render` and per-write subcommands surface soft-cap warnings to stderr.
- `add-*` subcommands hard-refuse over hard cap with the retire-first error message.

---

## 6. Analyzer prompt rewrite

`agents/xp-system-analyzer.md` Step 4 (Build system_context JSON) needs the following:

1. **Drop `sources`** from the JSON template.
2. **Rename `key_decisions` → `principles`** throughout.
3. **Add per-field definition + discriminator test** for each field in the template:
   - `modules`: navigation-index test + "no docs/" exclusion + purpose-shape guidance
   - `principles`: reversal test + don't-record list
   - `project_specific`: session-relevance test + don't-record list
4. **Add cap awareness** — analyzer should preview counts against soft/hard caps before committing entries; in update mode, identify retirement candidates first when over soft cap.
5. **Add the negation framing** at the top of Step 4: "Record what defines this project, not what was decided along the way."

Test pin (`tests/hooks/test_agent_prompts.py`): the analyzer prompt must contain each discriminator test phrase + each cap number, so a future edit can't silently drop them.

---

## 7. One-time curation of this project

The cap mechanism prevents future bloat. To bring this project under caps, a single curation commit (separate from the schema/CLI commit):

### Principles (was key_decisions): 42 → 14

**Keep (14 — architectural identity):**
hooks-first, four-file-architecture, smm-storage, commit-gated-review, security-review-at-close-skills, cli-teammates, broadcast-smm, retrospective-timing, zero-dependencies, curation-model, kickoff-gate, branch-lifecycle, close-reviewer, tier-1-deterministic-security

**Retire (28 — tactical/historical/bug-fix-shaped):** see full list in §7-appendix of this doc.

### project_specific: 11 → 6

**Retire (5 — registry duplicates or trimmable to <500ch):**
- `skills` — duplicates `skills/` directory + each SKILL.md
- `subagents` — duplicates `agents/` directory + each agent.md
- `branch-lifecycle` (995ch) — trim to ≤500ch summary or move to docs/
- `review-tiers` (861ch) — trim to ≤500ch summary
- `story-lifecycle-states` (840ch) — trim to ≤500ch summary

**Keep / re-shape (6):**
- `hook-event-lifecycle` (702ch → ≤500ch)
- `event-types`, `smm-four-pillars`, `platform-constraints`, `session-history`, `version` — all already ≤500ch

### conventions: 27 → ~18

Review for entries that drift toward operational rules (belong in SMM Constraints pillar) or version-stamped behavior changes. Target: 18–20 codebase conventions only.

### modules: 7 → 6

Drop `docs/` per the navigation-index discipline.

### Estimated final render

~14KB ≈ 3.5K tokens. Drops to within Legacy's range. Reviewer subsets we built in Goal #3 still earn their keep (plan-reviewer ~1.5K, close-reviewer ~900) but the urgency for them lessens.

---

## 8. Files that change

**Schema / validation:**
- `plugins/xp-agents/smm/system_context_schema.py` — drop `sources` from required fields + `empty_system_context()`, rename `KEY_DECISION_*` → `PRINCIPLE_*`, add count caps as named constants (`MODULES_SOFT_CAP=10`, `MODULES_HARD_CAP=15`, etc.), add new string caps (`MODULE_NAME_MAXLENGTH=50`, etc.), wire validation
- `plugins/xp-agents/smm/system_context_renderer.py` — rename `_render_key_decisions` → `_render_principles`, drop `_render_sources`, update `ALL_SECTIONS` + heading map
- `plugins/xp-agents/smm/system_context_cli.py` — rename `add-decision` → `add-principle`, add `retire-*` subcommands, add soft-cap stderr warning + hard-cap refusal
- `plugins/xp-agents/smm/system_context_store.py` — graceful read-fallback for legacy `key_decisions` field; on write canonicalize to `principles`

**Analyzer + agents:**
- `plugins/xp-agents/agents/xp-system-analyzer.md` — rewrite Step 4 per §6 above
- `plugins/xp-agents/agents/xp-plan-reviewer.md` — update "Cross-Layer Redundancy" reference if it cites `key_decisions` (it cites "system_context=WHERE" — likely unaffected)
- `plugins/xp-agents/agents/xp-close-reviewer.md` — update reference to renamed sections if any

**Guides:**
- `plugins/xp-agents/PROCESS_GUIDE.md` — System Context section: list `principles` (with cap), drop `sources` mention
- `plugins/xp-agents/CLAUDE.md` — if it mentions key_decisions by name, update

**Helper:**
- `plugins/xp-agents/skills/_preload_base.sh` — `system_context_render_to_tempfile_for` already takes a kind arg; update the hardcoded `--sections` literals for `plan-reviewer` and `close-reviewer` to swap `key_decisions` → `principles`. Add new `main-agent` kind only if/when we subset session_start (separate decision; see §10).

**Tests:**
- New tests for caps (soft warn / hard refuse)
- New tests for `retire-*` subcommands
- Update existing `system_context_cli` tests for renamed field
- Update analyzer prompt pin tests
- Update reviewer subset tests for renamed field
- Test for graceful read-fallback of legacy `key_decisions`

---

## 9. Suggested commit split

Single plan, three commits:

1. **A: Schema + CLI rename + caps + retire subcommands.** Pure mechanical schema work + new CLI surface + tests. Backward-compatible read of legacy `key_decisions`. No content changes.

2. **B: Analyzer prompt + guides update.** Rewrite analyzer Step 4 per §6, update PROCESS_GUIDE.md + CLAUDE.md mentions, update `_preload_base.sh` subset literals, fix any agent .md references.

3. **C: Project curation.** Apply §7 to this project: retire 28 principles, 5 project_specific, ~9 conventions, 1 module. Single mechanical commit using the retire CLIs from A.

Each commit independently green.

---

## 10. Out of scope for this design

- **Session-start render subsetting** (the "main-agent" kind discussed earlier in session). After curation reduces our full render to ~3.5K tokens, the case for subsetting weakens substantially. Defer the decision to post-curation: if 3.5K tokens still feels heavy, add a `main-agent` kind to `system_context_render_to_tempfile_for` with the same subset shape as plan-reviewer. If not, leave session_start using the full render.
- **Cross-project propagation of process discipline.** SMM Wisdom items don't propagate across projects today. Out of scope.
- **`project_specific` as session-pinned vs project-static.** Some entries (current_phase) might naturally live in execution_plan.json. Out of scope until pain demands.

---

## 11. Caveats worth surfacing in implementation

- **Reversal test is judgment-laden.** Edge cases will exist. The analyzer's job is to apply the test honestly; the cap is the safety net for when judgment leans toward "yes, this is architectural" too often.
- **Content cap on `project_specific.content` measured against JSON-serialized length** — applies uniformly across string/list/object content shapes.
- **`retire-*` semantics: hard delete, not soft.** The decision/principle's content disappears from system_context.json. Provenance survives in events.jsonl (the original `decision` event remains). If we ever want a "graveyard" archive, that's separate scope.
- **Backward compat window.** Legacy `key_decisions` field readable for one release (v3.2.x), then drop in v3.3 or v4. Schema validator emits warning when legacy field present.
- **The curation commit (C) is heavy reading.** Listing 28 retirements in a single commit message is dense; consider attaching a brief retire-rationale per entry in the commit body or in a separate companion doc.

---

## §7-Appendix: Principles retirement list for this project

The 28 entries from current `key_decisions` to retire under the reversal test, with terse rationale:

| Topic | Why retire |
|---|---|
| `acceptance-surfaces` | Field-existence statement, not architectural |
| `xp-story-close` | Describes a skill (skill self-documents) |
| `resolves-event-hard-gate` | Constraint, not principle (was advisory → blocking) |
| `story-attribution-tier-0` | Tactical parsing rule |
| `fast-forward-on-resume` | Git mechanism |
| `free-session-lifecycle` | Workflow detail |
| `team-scenario-branching` | Status update ("All 5 milestones complete") |
| `story-branch-lifecycle` | Naming convention + lazy-creation detail |
| `accept-auto-switch` | UI smoothing |
| `ac-fail-cascade` | Constraint (behavioral cascade), not principle |
| `mid-chain-nudge` | Advisory mechanism |
| `compaction-retains-sprint-commits` | Bug-fix specific |
| `git-prefix-shared-regex` | Tactical regex fix |
| `count-concerns-cli` | CLI command behavior |
| `incremental-teammate-accept` | Version-stamped behavior change |
| `closing-state-lifecycle` | State-machine detail |
| `cas-guarded-status-transitions` | Concurrency primitive |
| `probe-snapshot-staleness-reread` | Bug fix (and probes retired) |
| `treat-as-done-jit-next` | Race-condition resolution |
| `session-history-ring-buffer` | File design detail |
| `end-session-skill` | Skill behavior summary |
| `event-category-enum` | Internal refactor |
| `decision-supersedence-nudge` | Meta-process advisory |
| `stage-2-floor-migration` | Workflow detail |
| `dropped-try-resurfacing-fix` | Bug fix |
| `xp-accept-auto-close-chain` | Workflow detail |
| `session-history-cli-canonical` | CLI naming |
| `probe-emission-removal` | Historical / stale (probes retired) |

Net: 14 principles remain, well under the soft cap of 15 with breathing room for one more before pressure applies.

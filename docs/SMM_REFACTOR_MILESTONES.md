# SMM Refactor — Migration Milestones

Migrating from the current event-dump SMM to the five-pillar curated model described in `SMM_DESIGN.md`. Each milestone is independently shippable and leaves the system working.

---

## M1: Preload Data Structure

**Goal:** Build the data layer that feeds housekeeping's judgment. The materializer shifts from "render the SMM" to "prepare data for curation."

**What changes:**
- New function in materializer: `prepare_curation_data(smm_dir)` → returns the structured JSON described in SMM_DESIGN.md (current_smm, new_since_last_curation, retro_history, aging, health)
- Curation watermark: `.curation-watermark` file with last-curated event count/timestamp
- Preload script for housekeeping calls `prepare_curation_data()` and outputs it

**What doesn't change yet:**
- Old materializer still runs and writes SMM.md (parallel operation)
- PreToolUse delta still fires (removed later)
- Housekeeping still triages raw event types (enhanced in M2)

**Acceptance criteria:**
- [ ] `prepare_curation_data()` returns valid JSON with all fields from the design
- [ ] Curation watermark written and read correctly
- [ ] Preload outputs structured data for housekeeping
- [ ] Old materializer unaffected — existing tests pass
- [ ] Tests for the new function covering: fresh project, mature project, team scenario

---

## M2: Housekeeping Curates the Five-Pillar SMM

**Goal:** Housekeeping writes `SHARED_MENTAL_MODEL.md` using LLM judgment against the five pillars. This is the core change.

**What changes:**
- Housekeeping SKILL.md updated with five-pillar curation instructions
- Housekeeping reads `prepare_curation_data()` output (from M1 preload)
- Housekeeping reads existing SMM.md (merge, don't replace)
- Housekeeping writes new SMM.md in five-pillar format
- Housekeeping enforces caps and health signals
- Old mechanical materializer no longer writes SMM.md (but `prepare_curation_data()` still runs)

**What doesn't change yet:**
- PreToolUse delta still fires
- Event types unchanged
- Watermarks unchanged

**Acceptance criteria:**
- [ ] Housekeeping produces five-pillar SMM.md with Intent, Constraints, Risks, Coordination, Wisdom
- [ ] Customer inputs distilled to Intents (judgment)
- [ ] Draft decisions promoted to Constraints (judgment)
- [ ] Concerns/assumptions/debt/questions unified into Risks with severity
- [ ] Retro Tries promoted to Wisdom when appropriate
- [ ] Caps enforced — health signals appear when pillar is unhealthy
- [ ] Merge works — existing items preserved, new items added
- [ ] SMM.md is ~300-700 tokens at healthy state

---

## M3: Coordination File

**Goal:** Replace event-log scanning for team conflict detection with a lightweight `.coordination.json` file.

**What changes:**
- New `.coordination.json` file in SMM directory
- PostToolUse command hook (Write/Edit) atomically updates the agent's entry
- PreToolUse conflict check reads `.coordination.json` instead of scanning events
- SessionEnd clears the agent's entry
- Stale entries (>30 min) ignored

**What doesn't change yet:**
- PreToolUse delta still fires (removed in M4)
- Event log still has status events (still useful for housekeeping data trails)

**Acceptance criteria:**
- [ ] `.coordination.json` updated atomically on file writes
- [ ] Conflict detection reads coordination file, not event log
- [ ] Stale entry cleanup works
- [ ] SessionEnd clears entry
- [ ] Flock-protected for concurrent access
- [ ] Team scenario: two agents detect overlap correctly

---

## M4: Remove PreToolUse Delta, Add Stop Nuggets

**Goal:** Eliminate the per-tool-call SMM injection. Replace with lightweight nuggets at Stop events. This is the big context savings.

**What changes:**
- PreToolUse no longer reads the event log or injects SMM delta
- PreToolUse retains only: conflict check (via `.coordination.json` from M3), TDD order check, plan review gate
- Stop hook injects a nugget: unresolved risks, undelivered intents (~50-80 tokens)
- SubagentStart injects the full curated SMM (for new subagents/teammates)

**What gets removed:**
- `read_delta.py` usage in PreToolUse (delta formatting, tier filtering)
- Per-agent watermarks (`.watermark-*` files)
- SMM delta context in every tool call

**What stays:**
- `read_delta.py` module (may still be useful for other purposes)
- Event log append (hooks still leave data trails)
- Curation watermark (for housekeeping, from M1)

**Acceptance criteria:**
- [ ] PreToolUse no longer reads events.jsonl
- [ ] PreToolUse no longer injects `<smm-context>` or `<smm-delta>`
- [ ] Stop nugget shows unresolved risks and undelivered intents
- [ ] Stop nugget is empty (no injection) when nothing needs attention
- [ ] SubagentStart injects full five-pillar SMM
- [ ] Context savings verified: measure tokens per tool call before/after
- [ ] All existing functionality preserved (TDD check, conflict detection, plan gate)

---

## M5: Event Log Compaction

**Goal:** The event log stabilizes at ~1-2 sessions instead of growing forever.

**What changes:**
- Housekeeping compacts the event log after curation
- Retains: events since curation watermark + last 3 `session_end` events + events referenced by current SMM items
- For teams: compacts only past the oldest agent's curation watermark
- Backup before compaction (safety net)

**What gets removed:**
- Old delta watermark files (`.watermark-*`)
- PreCompact backup logic (simplified — compaction is now part of housekeeping, not a separate hook)

**Acceptance criteria:**
- [ ] Event log compacted after housekeeping curation
- [ ] Retained events: recent + session_end + referenced
- [ ] Team safety: no compaction past oldest agent's watermark
- [ ] Backup created before compaction
- [ ] Event log size stabilizes (~50-200 events, not 1000+)
- [ ] Aging calculations still work after compaction (session_end events retained)

---

## M6: Cleanup

**Goal:** Remove dead code from the pre-refactor SMM system.

**What gets removed:**
- Old `materialize()` and `materialize_to_file()` rendering functions (replaced by `prepare_curation_data()`)
- `read_delta.py` if no longer used
- Old watermark read/write functions
- `format_delta()`, `filter_by_tier()`
- Delta-related tests
- Old SMM format references in docs (ARCHITECTURE.md, README.md, CLAUDE.md)
- `smm-protocol` skill updated for five-pillar model

**What gets updated:**
- README.md Token Cost Model (new injection model)
- ARCHITECTURE.md (new SMM design)
- CLAUDE.md (new SMM references)

**Acceptance criteria:**
- [ ] No dead code from old SMM system
- [ ] All docs reflect five-pillar model
- [ ] Test count may decrease (removed delta tests) but coverage of new system is complete
- [ ] Clean `grep` for old patterns: `smm-delta`, `smm-context`, `read_delta`, `filter_by_tier`

---

## Migration Safety

Each milestone leaves the system working:

| After | SMM written by | Delta injection | Conflict detection | Event log |
|---|---|---|---|---|
| Current | materializer (Python) | Every PreToolUse | Event log scan | Unbounded |
| M1 | materializer (Python) | Every PreToolUse | Event log scan | Unbounded |
| M2 | housekeeping (LLM) | Every PreToolUse | Event log scan | Unbounded |
| M3 | housekeeping (LLM) | Every PreToolUse | .coordination.json | Unbounded |
| M4 | housekeeping (LLM) | Stop nuggets only | .coordination.json | Unbounded |
| M5 | housekeeping (LLM) | Stop nuggets only | .coordination.json | Compacted |
| M6 | housekeeping (LLM) | Stop nuggets only | .coordination.json | Compacted |

The riskiest milestone is **M2** (housekeeping takes over SMM writing). Everything else is additive or subtractive with clear rollback.

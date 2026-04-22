# Remove Story Sizing — Drop S/M/L from sprint stories

**Plugin:** `xp-agents`
**Type:** Simplification
**Priority:** Low (no user-visible behavior change; removes dead metric)
**Decision:** Recorded in session 2026-04-22, topic `story-sizing`

---

## Problem

Story sizing (S/M/L) has been miscalibrated for 11 consecutive retro sessions. S stories consistently end up larger than M stories. The retro flags it every time, we adopt a fix every time, and it never sticks — because the metric doesn't map to how the work flows.

Sizing was intended for velocity calibration and sprint capacity planning. In practice:
- We work one sprint at a time with one agent — no team capacity math needed
- Stories are scoped by acceptance criteria, not estimated effort
- File domain and plan step count aren't known until after sizing happens
- The per-size calibration table says the same thing every session (inverted) and we never act on it

---

## Scope

Remove the `size` field from sprint story schema and all code that reads/writes/validates it.

### Files to change

1. **`smm/event_schema.py`** — remove `size` from story schema validation
2. **`smm/sprint_cli.py`** — remove `--size` from `add-story`, drop size from `render` output
3. **`smm/sprint_state.py`** — remove any size-dependent logic
4. **`skills/xp-sprint-start/SKILL.md`** — remove sizing instructions and size field from story JSON template
5. **`skills/xp-sprint-review/SKILL.md`** — remove per-size calibration table from review output (if present)
6. **`agents/xp-retrospective/`** — remove per-size metrics from retro analysis
7. **Tests** — update any tests that include `size` in story fixtures

### What stays

- Sprint stories still have `id`, `title`, `status`, `dependencies`, `acceptance_criteria`
- Velocity tracking (commits, files, duration) remains — just not bucketed by size
- If we need effort estimation later (e.g., multi-agent capacity), reintroduce based on plan step count or file_domain size rather than upfront guessing

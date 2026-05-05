# Sprint-062 follow-up: `/xp-accept` preload + `.accept` marker re-arm

**Plugin:** `xp-agents`
**Origin:** Sprint-062 deferred frictions #3 and #4 from `docs/completed/sprint-062-workflow-plumbing-stories.md`. Both were named in that sprint's "Why" but not addressed by its 4 stories. We then hit both repeatedly during the sprint itself, confirming they're real.
**Status:** Draft — feed into next `/xp-sprint-start` planning.

## Why this follow-up

The sprint-062 doc listed 4 close-cycle frictions but only shipped fixes for 2 (auto-link + multi-AC schema). Frictions #3 and #4 were carried in "Why this sprint" prose without corresponding stories. During sprint-062 execution we hit both — concrete reproductions below.

---

## Friction #3 — `/xp-accept`'s preload misses `reviewing` stories

**Original framing (sprint-062 doc):** *"`/xp-accept`'s preload only sees `in-progress` stories, but teammates self-promote to `reviewing` before exiting. After the first /xp-accept, the preload listed only the still-running teammates, silently excluding the reviewing-batch ready for the orchestrator. Workaround: manually process reviewing stories outside the preload's scope."*

**Sprint-062 reproduction.** When the four parallel teammates finished and self-promoted to `reviewing` (per their prompt instructions to flip status before exit), `/xp-accept`'s preload reported `NO_IN_PROGRESS — No in-progress stories to accept` and exited early. I had to manually revert all four stories from `reviewing` back to `in-progress` via `sprint_cli.py update-story` before re-invoking `/xp-accept`. The skill design assumes the preload-driven promote-to-reviewing flow (Step 1.0 in `/xp-accept` SKILL.md), but teammate prompts can't honor that without orchestrator coordination.

**Two design directions:**

1. **Teammate prompts stop self-promoting.** TEAMMATE_GUIDE.md tells teammates to exit while still `in-progress`; the orchestrator's `/xp-accept` does the promote→reviewing transition. This is the documented design — teammate prompts have just been overriding it.
2. **`/xp-accept` preload reads both `in-progress` AND `reviewing`.** Defensive: works regardless of how stories arrived in `reviewing` (teammate self-promote, prior-session leftover, etc.). Treats `reviewing` as "ready to verify" exactly the same as `in-progress`.

Direction (1) is the cheaper fix; (2) is more robust against future teammate-prompt drift. Either could ship as a one-story fix.

### File domain (option 1 — teammate-prompt fix)

- `plugins/xp-agents/TEAMMATE_GUIDE.md` — clarify the lifecycle: teammates exit at `in-progress`, never `reviewing`
- `plugins/xp-agents/scripts/spawn_teammate.py` — if the prompt template injects exit instructions, update them
- `plugins/xp-agents/tests/integration/test_assign_team.py` (or similar) — pin: spawned teammate exits with story still `in-progress`

### File domain (option 2 — preload widening)

- `plugins/xp-agents/skills/xp-accept/scripts/preload.sh` — widen the status filter from `in-progress` to `in-progress|reviewing`
- `plugins/xp-agents/skills/xp-accept/SKILL.md` — Step 1.0 promote-to-reviewing becomes idempotent (skip if already `reviewing`)
- `plugins/xp-agents/tests/integration/test_accept_lifecycle.py` — extend with reviewing-only and mixed-state preload cases

---

## Friction #4 — `.accept` marker re-arm whack-a-mole

**Original framing (sprint-062 doc):** *"Multiple times `pre_tool_bash` blocked `update-story done` with 'Run /xp-accept first' even mid-flow. Re-invoking /xp-accept against `NO_IN_PROGRESS` just to satisfy the marker gate was clunky."*

**Sprint-062 reproduction.** During every `/xp-story-close` fix-cycle (when reviewer concerns required edits + a follow-up commit), the `.accept` marker re-armed. Subsequent `update-story <id> done` was blocked by `pre_tool_bash` with `Run /xp-accept to verify acceptance criteria before marking stories done`. I had to `rm -f $SMM_DIR/.accept` manually between every story-close cycle. Hit this 4+ times in this sprint alone (once per story-close after the first).

The skill design (Step 1.0 in `/xp-accept` SKILL.md) cites the `ACCEPT_ACTIVE` marker as the mechanism that prevents re-arm during the acceptance window. Either the marker isn't being written by the preload, or it's being consumed too early, or the re-arm logic in `pre_tool_write` doesn't actually consult it.

**Investigation needed:**

1. Does `/xp-accept`'s preload write `ACCEPT_ACTIVE` to `$SMM_DIR/`? Confirm via `ls $SMM_DIR/ACCEPT_ACTIVE` after invoking `/xp-accept`.
2. Does `pre_tool_write` (or whichever hook re-arms `.accept`) check for `ACCEPT_ACTIVE` presence?
3. Is `ACCEPT_ACTIVE` consumed by `/xp-sprint-close` end-of-flow, or at some earlier checkpoint that fires too soon?

**Likely fixes (depending on root cause):**

- Preload writes `ACCEPT_ACTIVE` but never gets read → wire `pre_tool_write` re-arm to skip when marker present
- Marker is consumed too early (e.g., by `/xp-story-close`) → defer consumption to `/xp-sprint-close` per the SKILL.md design
- Marker is never written → write it in `xp-accept/scripts/preload.sh`

### File domain (after investigation)

- `plugins/xp-agents/skills/xp-accept/scripts/preload.sh` — write `ACCEPT_ACTIVE` if not already
- `plugins/xp-agents/scripts/pre_tool_write.py` — skip `.accept` re-arm when `ACCEPT_ACTIVE` present
- `plugins/xp-agents/skills/xp-sprint-close/SKILL.md` — consume `ACCEPT_ACTIVE` at end-of-flow
- `plugins/xp-agents/tests/integration/test_accept_lifecycle.py` — extend with multi-story-close flow asserting no manual marker cleanup needed

---

## Sequencing

- Friction #3 and #4 are independent and dep-free with each other
- Each is roughly one M-sized story
- Could ship together in a "close-cycle ergonomics" mini-sprint, or as two stories within a larger sprint

## Provenance

- Originally captured in `docs/completed/sprint-062-workflow-plumbing-stories.md` "Why this sprint" frictions #3 and #4 (no corresponding stories)
- Sprint-062 (2026-05-04) execution hit both frictions repeatedly — see this session's transcript for concrete reproductions
- Drafted at sprint-062 close as the user audited the source doc against shipped stories

# `.accept` marker re-arm whack-a-mole — investigation + fix

**Plugin:** `xp-agents`
**Origin:** Sprint-062 friction #4. Originally captured alongside friction #3 in `docs/ideas/3-preload-reviewing-and-accept-marker.md` (since deleted); friction #3 is now in doc 8, and friction #4 is preserved here.
**Status:** Draft — feed into next `/xp-sprint-start` planning.

## Original framing

> Multiple times `pre_tool_bash` blocked `update-story done` with "Run /xp-accept first" even mid-flow. Re-invoking `/xp-accept` against `NO_IN_PROGRESS` just to satisfy the marker gate was clunky.

## Sprint-062 reproduction

During every `/xp-story-close` fix-cycle (when reviewer concerns required edits + a follow-up commit), the `.accept` marker re-armed. Subsequent `update-story <id> done` was blocked by `pre_tool_bash` with `Run /xp-accept to verify acceptance criteria before marking stories done`. I had to `rm -f $SMM_DIR/.accept` manually between every story-close cycle. Hit this 4+ times in one sprint (once per story-close after the first).

The skill design (Step 1.0 in `/xp-accept` SKILL.md) cites the `ACCEPT_ACTIVE` marker as the mechanism that prevents re-arm during the acceptance window. Either the marker isn't being written by the preload, or it's being consumed too early, or the re-arm logic in `pre_tool_write` doesn't actually consult it.

## Investigation needed

1. Does `/xp-accept`'s preload write `ACCEPT_ACTIVE` to `$SMM_DIR/`? Confirm via `ls $SMM_DIR/ACCEPT_ACTIVE` after invoking `/xp-accept`.
2. Does `pre_tool_write` (or whichever hook re-arms `.accept`) check for `ACCEPT_ACTIVE` presence?
3. Is `ACCEPT_ACTIVE` consumed by `/xp-sprint-close` end-of-flow, or at some earlier checkpoint that fires too soon?

Note from execution-plan M-3 design details: prior investigation already established that `ACCEPT_ACTIVE` IS wired in `pre_tool_write.py:322` — the bug is elsewhere. Hypotheses worth pursuing: (a) marker consumed too early by `/xp-story-close`, (b) Edit path bypasses the check, (c) marker write happens after the first re-arm has already fired.

## Likely fixes (depending on root cause)

- Preload writes `ACCEPT_ACTIVE` but never gets read → wire `pre_tool_write` re-arm to skip when marker present
- Marker is consumed too early (e.g., by `/xp-story-close`) → defer consumption to `/xp-sprint-close` per the SKILL.md design
- Marker is never written → write it in `xp-accept/scripts/preload.sh`

## File domain (after investigation)

- `plugins/xp-agents/skills/xp-accept/scripts/preload.sh` — write `ACCEPT_ACTIVE` if not already
- `plugins/xp-agents/scripts/pre_tool_write.py` — skip `.accept` re-arm when `ACCEPT_ACTIVE` present
- `plugins/xp-agents/skills/xp-sprint-close/SKILL.md` — consume `ACCEPT_ACTIVE` at end-of-flow
- `plugins/xp-agents/tests/integration/test_accept_lifecycle.py` — extend with multi-story-close flow asserting no manual marker cleanup needed

## Sequencing

- Independent of doc 8's incremental-acceptance work (different mechanism, different code paths)
- Roughly one M-sized story; could ship alongside doc 8's work in a "close-cycle ergonomics" mini-sprint or independently

## Provenance

- Originally captured in `docs/completed/sprint-062-workflow-plumbing-stories.md` "Why this sprint" friction #4 (no corresponding story)
- Sprint-062 (2026-05-04) execution hit this friction repeatedly — see that session's transcript for concrete reproductions
- Drafted at sprint-062 close as the user audited the source doc against shipped stories
- Split out from old doc 3 when doc 8 superseded the friction #3 portion (sprint-065 Wave 2 close)

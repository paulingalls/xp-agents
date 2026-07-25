<!--
PROVENANCE — saved at the end of the sprint-117 session so it survives the
next plan-mode entry (the ~/.claude/plans/ file is per-session and gets
overwritten).

STATUS: PLANNED and REVIEWED. /xp-review-plan ran twice; the second pass found
the original detector rule was WRONG on both triage legs and forced the unified
rule below. sprint.json's story-003 file_domain + acceptance_execution were
rewritten to match (they previously named test_retro_metrics.py, which this plan
never touches — the verify-touch gate would have refused the close).

TO EXECUTE NEXT SESSION:
  1. /xp-kickoff  ->  sprint-117 is still open (3/8 stories done, not closed).
  2. story-003 is `scheduled` with execution_mode=teammate, executor opus/high.
  3. Re-enter plan mode ONLY to re-arm the .plan-awaiting-review marker, paste
     this file as the plan, exit, run /xp-review-plan, then /xp-assign.
  4. It closes Milestone 2. Until it lands, adopted Trys AND adopted debts are
     re-offered forever — you will see it at the very next kickoff.

KEY DECISIONS ALREADY RECORDED (do not re-derive):
  ad52b9720972  intent-link-unified-rule   <- the corrected detector
  1162afbbad2e  adoption-detection-by-shape
  28c8d21badb3  adoption-intent-channel
-->

# story-003 — The tools remember what was adopted (both lanes)

## Context

Sprint-117 / execution_plan.json §**Milestone 2**. This is the story that **closes
M2** — the mirror-image regression story-001 must not leave behind.

story-001 made adoption *link* instead of *close*: an intent event (adopt, defer)
now names its target in top-level `references` and leaves it OPEN; only a terminal
disposition (`dropped`/`wont_fix`) writes `metadata.resolves`. That was the fix.

But **two readers still ask "was this resolved?" and get the wrong answer**, on two
different lanes:

**Retro lane.** `annotate_try_status` (`retro_history.py:81`) looks each Try up in
`build_resolutions_map`, which is fed **only** by `compute_resolutions` — i.e. by
`metadata.resolves` plus its cascade. So post-story-001, only *dropped* Trys are
found. An adopted Try and a deferred Try each report
`resolved_this_session: False`, and the retro agent re-proposes them forever.

**Triage lane** (concern `30a453b97537`, confirmed). `triage_preload.run` filters on
`triage.find_unresolved`, which is purely `id not in resolved_ids`. `triage-adopt`
writes `disposition=adopted` + `references=[debt_id]` and **no `resolves`** — so the
debt never enters a resolutions bucket and is re-offered at **every kickoff, forever**,
with only its `(N sessions old)` age string. No "adopted", no adopter.

Same defect, both lanes. story-001 converted adoption from closure to intent on both;
repairing only one would be exactly the half-fix this sprint keeps catching.

## The detector — and the shape table I got wrong

My first table keyed adoption on `type == decision`. **It was wrong on both triage
legs**, and the reviewer caught it by reading the writers. The real shapes:

| writer | type | disposition | link |
|---|---|---|---|
| retro `adopt` / `defer --force-adopt` | `decision` | **none** | `references` |
| retro `defer` | `status` | `deferred` | `references` |
| retro `drop` | `status` | `dropped` | `metadata.resolves` |
| **`triage-adopt`** | **`status`** | `adopted` | `references` |
| **`triage-defer`** | **`status`** | `deferred` | **neither — links nothing** |

So `decision + references ⇒ adopted` **never fires for `triage-adopt`** (it's a
`status`), and the whole lane the widening exists to fix would still re-offer adopted
debt forever. And **`triage-defer` links nothing at all — no reader can fix that.**

**The unified rule that actually works:**

> **`id ∈ top-level references` (ANY event type) ⇒ intent link.
> `disposition` = `metadata.disposition` when present, else `adopted`**
> (a link with no disposition *is* the retro adopt path).
> **`metadata.resolves` still wins as terminal.**

One rule, all four intent shapes — which is what "one detector, two callers" needs in
order to be true.

**Plus a WRITER fix**: `triage-defer` must emit `references=[event_id]`
(`work_selection_decide.py`). Without it the deferred leg is undetectable by
construction.

**Do not key on the `retro-try-` topic.** It's LLM-supplied and nothing enforces the
prefix. `references` is the *structural* signal — machine-written by
`extract_refs_suffix`. Topic may ride along as provenance; it must not be a predicate.

**But do not over-match either.** "Any event whose `references` name the id" would let a
reviewer's decision that merely *cites* a Try id — or a cascade flag — silently mark it
adopted and suppress re-proposal forever. Corroborate with writer provenance
(`metadata.disposition`, or the work-selection topic) rather than bare `references`.
That is concern `86798eb2eaed`, and it is a real hole in the rule as stated.

**Ordering is load-bearing.** A Try can be deferred in sessions 1–2 and adopted in
session 3. Scan events in order, **last intent event wins**, or the deferral masks the
adoption. And a **drop is terminal** — it must not be overridden by an earlier adopt.

**Use the FULL events list, not the unanalyzed slice.** An adopt from a *prior* session
must keep suppressing the Try, or you rebuild the same amnesia one session later.

## Verify this before implementing — the recon's most surprising finding

I assumed `_preload_base.sh`'s `get_try_items` skip-branch (`if
statuses[i].get('resolved_this_session'): continue`) is what re-proposes a Try. **It
appears to be dormant.** `annotate_try_status` mutates the *in-memory* history into
`.retro-input.json`; nothing writes `try_status` back into a `retrospectives/*.json`
(`save_retrospective.py:120` writes `try` with no `try_status`), and kickoff runs the
retro *before* work-selection — so the file the preload reads is the one the agent just
wrote, which has no `try_status`.

If that holds, **the real gate is the retro agent**, which reads `try_status` from
`.retro-input.json` and already has prompt rules for all three dispositions
(`agents/xp-retrospective.md:207-211`: adopted → don't re-propose; dropped → never;
deferred → may re-propose noting the count; false → re-propose if still a problem).
That means fixing `annotate_try_status` **is** sufficient to close the retro loop.

**Confirm it empirically before relying on it.** If it does *not* hold, the renderer
needs fixing too — say so rather than shipping on the assumption.

## Changes

### 1. `scripts/retro_history.py` — the shared intent detector

Natural home: it's 126 lines and already owns the Try domain (`retro_metrics.py` is
**494/500** — a new function there crosses the cap).

- **NEW `build_intent_map(events) -> {target_id: {disposition, resolver_id, resolver_ts, topic?}}`** —
  the shape rules above, in-order, last-write-wins. **Write it so BOTH lanes can call
  it**: the triage lane needs the same map keyed on debt/concern ids. One detector, two
  callers — that is the whole point of widening this story.
- `annotate_try_status(previous_retros, resolutions_map, events)` — consult
  `resolutions_map` **first** (a drop is terminal and must win), then fall back to the
  intent map.
- **Delete the dead branch** at `:119` (`elif hit.get("resolver_type") == "decision"` →
  "decisions without explicit disposition are adoptions").

  **Correction — my justification was false.** I claimed "no shipped writer emits a
  `decision` carrying `metadata.resolves` any more." `scaffold_post.py:281-290` does
  exactly that. The deletion may still be right, but it needs a **Try-lane
  reachability** argument (no writer emits a `decision` + `resolves` naming a *Try* id),
  not a global one. Make that argument explicitly, or keep the branch.

  Also: `DISPOSITION_ADOPTED` will **not** be unused — `build_intent_map` needs it to
  label adopted entries. Don't delete the import.

### 2. `scripts/retrospective.py` — pass `events` through
One line at `:168`. `events` and `resolutions` are both already in scope in
`_build_retro_input` (`:143`). Update the import at `:33`.

### 3. `skills/xp-work-selection/scripts/work_selection_decide.py` — the WRITER fix
`triage-defer` writes `disposition=deferred` and **links nothing** — no `references`, no
`resolves`. Its target is undetectable by construction, so no reader can repair it. Make
it emit `references=[event_id]`, matching `triage-adopt`. (`triage-drop` keeps `resolves`
— it is terminal.)

This file is story-001's declared domain, but story-001 is **done**, so the
concurrent-claim rule cannot fire.

### 4. `skills/xp-work-selection/scripts/triage_preload.py` — the second lane
Consult the same `build_intent_map`. An adopted debt/concern must surface **annotated**
("adopted N sessions ago by `<id>`"), not re-offered identically. Deferred likewise.
Keep the existing `MAYBE ADDRESSED` commit-overlap hint (concerns-only) as-is.

### Commit cadence
At least three red→green→commit cycles — one fat commit skips the per-increment review:
**(1)** detector + retro wiring · **(2)** writer fix + triage lane · **(3)** prose +
fixtures.

### 5. `agents/xp-retrospective.md` — the prose is now false
`:221` still says the mechanism "is built on `metadata.resolves` wiring done by
`/xp-work-selection adopt`." That channel no longer exists. This is shipped prose that
teaches a deleted mechanism — the same class of defect story-001's close review caught
in `SKILL.md`. Fix it here; do not leave it for a docs story.

## Tests (TDD — red first)

### `tests/hooks/test_retro_history_pipeline.py` — the real end-to-end pins
`:227 test_adopt_via_metadata_resolves_marks_resolved_and_keeps_try` builds
`make_event(DECISION, topic=..., metadata={"resolves": [try_id]})` — **a shape no writer
produces any more. The test is a fiction.** Rewriting it is story-003's red test:
replace the resolver with the *real* post-story-001 adopt event (`decision`, topic,
`references=[try_id]`, no metadata) and assert `disposition == "adopted"` and
`resolved_this_session == True`.

Keep `:191` (drop via `metadata.resolves`) — still correct. Read the cascade tests at
`:262`/`:293` before touching the detector; they constrain what `references` may mean.

### `tests/hooks/test_retro_history.py`
`TestAnnotateTryDisposition` builds **synthetic** `resolutions_map`s via
`_make_resolutions_map` (`:23`), hard-coding `"resolver_type": "decision"`. Those pin the
shape this story kills:
- `:34`, `:107`, `:123`, `:168` — dead-branch dependent. `:168`
  (`test_decision_resolver_without_disposition_defaults_to_adopted`) **IS** the dead
  branch; delete or replace with the reference-shape equivalent.
- `:76 test_deferred_try_gets_disposition_deferred` is a **false green** — it supplies an
  explicit disposition, so it proves nothing about the real deferred event (which carries
  `references` and no `resolves`, so `build_resolutions_map` never sees it). Re-anchor
  end-to-end.
- `:94 test_unresolved_try_has_no_disposition` — keep as the negative case.

### `tests/hooks/test_triage_preload.py` (or wherever the lane is pinned)
An adopted debt surfaces **annotated**, not re-offered bare. A deferred one likewise. An
untouched debt is still offered normally — the control.

### `tests/_event_fixtures.py`
`make_retrospective_with_try` (`:81`) exists. There is **no** fixture for the adopt/defer
events themselves — add them. **Build them by actually calling `work_selection_decide`
where practical**, so the fixture cannot drift from the writer the way
`_make_resolutions_map` just did. That drift is precisely why `:34`/`:123`/`:168` are
testing a shape production no longer emits.

## Verification

1. `pytest plugins/xp-agents/tests/hooks/test_retro_history_pipeline.py`
   `pytest plugins/xp-agents/tests/hooks/test_retro_history.py`
   `pytest plugins/xp-agents/tests/hooks/test_triage_preload.py` — red first, then green.
2. Full suite: `pytest -n auto` (baseline 6231 green).
3. **End-to-end against a real SMM, no mocks, both lanes:**
   - Adopt a Try via the real `work_selection_decide` CLI → regenerate the retro input →
     the Try reports `disposition: adopted`, and `compute_resolutions` **still reports it
     unresolved** (linking is not closing — assert both halves).
   - Defer a Try → reports `deferred`.
   - Drop a Try → still reports `dropped` via `metadata.resolves`.
   - `triage-adopt` a debt → it surfaces **annotated as adopted**, and is **still OPEN**.
4. **Falsifiability:** a Try deferred twice and *then* adopted must report **adopted**,
   not deferred. Get the ordering wrong and this fails.

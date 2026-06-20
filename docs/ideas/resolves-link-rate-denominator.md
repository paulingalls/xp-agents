# Finding: `resolves_link_rate` measures the wrong denominator

> **Status: INVESTIGATION (story-003, sprint-101).** Code-free finding +
> recommendation. The fix lands in a dedicated story (story-004) — see §Fix.
>
> Origin: the retro flags `resolves_link_rate ≈ 0.33` as a Fix-under-Communication
> every sprint, across many xp-agents instances. The trailer-discipline Try gets
> adopted every retro and the number never moves. Customer asked: real discipline
> gap, measurement artifact, or bar too high?

## Answer

**The bar is mis-specified relative to the denominator.** Not a discipline gap,
not a parsing bug. `0.80` was defined (in the design docs) against *"commits that
had a candidate concern to link"*, but the shipped code divides by *all eligible
code commits*. The two aren't comparable, so the flag fires forever and no amount
of trailer discipline can move it.

## What the metric computes today

`scripts/retro_metrics.py:_compute_resolves_link_rate` (lines 339–426):

```
rate = (eligible code commits WITH a Resolves-Event trailer)
       / (ALL eligible code commits)
```

`_included` (lines 380–396) is **exclusion-based**. It removes, from the sprint
window's code commits:

- `metadata.is_merge` — close-cycle merge HEADs,
- escape-hatch messages — `[release]` / `[chore]` / `[sprint-direct]`,
- `metadata.story_id` present — the story is the unit of resolution,
- `is_free_session` **without** a trailer — exploration with nothing to link.

It never restricts to "commits that *should* have carried a trailer." The `0.80`
threshold lives only in the agent prompt (`agents/xp-retrospective.md:133`), not
in code.

## Root cause: code contradicts its own design docs

Both docs that defined this metric specify a **candidate-gated** denominator:

- `docs/completed/FR_resolves_trailer_prompting.md` §Success metric —
  `resolves_link_rate = commits_with_resolves / commits_that_had_candidates`
- `docs/completed/MECHANICAL_DISCIPLINE_CLOSURE.md` §1.2 —
  `… / count(resolves_probe_shown events in sprint)`

The intended denominator is **commits where a probe found a matching open
concern/debt/question** — i.e. commits that *should* link. The shipped metric
instead counts every eligible code commit, the vast majority of which are
feature/refactor/doc work that legitimately closes nothing and correctly carries
no trailer. Those land in the denominator as permanent "misses," pinning the rate
near the fraction of commits that happen to close a tracked event (empirically
~⅓). **`0.80` of *all* code commits is unachievable by construction.**

The candidate signal the docs assumed was never wired: `resolves_probe` emits no
`resolves_probe_shown` event, `retro_metrics`/`retrospective` never reference
probe candidates, and the live event log holds **zero** probe events. The
denominator was narrowed by exclusion lists but never gated on "had a candidate."

## Evidence (this project's live SMM, sprint-101 window)

- After exclusions: **7** eligible code commits, **3** with a trailer → `0.43`.
  The **4** without trailers are all legitimate non-closing work — a 500-line
  test split, a `chmod`, a doc-sync ref fix, a dead-code drop. **Zero genuine
  missing trailers.**
- All **3** open concerns were resolved — via `status`/`decision` events carrying
  `metadata.resolves`, none via a commit trailer. Concerns are routinely closed
  by non-commit mechanisms a commit-based metric can't credit.
- Trailer parsing is correct (spot-checked `d15eae00`, `57ecee7f`, `26b2abd1` —
  valid trailers in git, `metadata.resolves` in the log). Not an instrument bug.

## Fix (dedicated story-004)

Restrict the denominator to its documented intent: **eligible code commits that,
at commit time, had ≥1 open concern/debt/question candidate**, by the same
structural file-overlap the "MAYBE ADDRESSED" nudge already uses. The reusable
building blocks exist:

- `scripts/commits.py:find_addressing_commits(concern, events)` and
- `scripts/triage.find_overlapping_commits(concern, events)`

so the candidate set is computable retroactively from the event log with **no new
emission**. Numerator stays "carried a trailer." Then `0.80` means *"of the
commits that should have linked, how many did"* — a real, achievable discipline
target.

TDD surface for story-004: `scripts/retro_metrics.py` (the `_included` /
candidate-gating logic), `tests/hooks/test_retro_metrics*.py` (denominator
characterization: a no-candidate commit is excluded; a commit overlapping an open
concern's files is included), and `agents/xp-retrospective.md` (interpret `0.80`
against the new denominator).

## Non-goals

- No keyword/NLP matching — ruled out in `MECHANICAL_DISCIPLINE_CLOSURE.md`
  §Non-goals (high false-positive noise; conflicts with the `files=[]` structural
  discipline). Use the existing file-overlap signal only.
- No retroactive re-linking of past commits — the SMM is append-only.
- No new emission — compute the candidate set at retro time from existing events.

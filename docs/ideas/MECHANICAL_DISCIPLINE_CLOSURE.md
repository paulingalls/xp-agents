# Mechanical SMM Discipline — Close the Feedback Loop

**Plugin:** `xp-agents`
**Type:** Execution plan design source (multi-milestone)
**Supersedes:** `BUG_domain_accuracy_wrong_signal.md`, `FR_resolves_trailer_prompting.md`
**Priority:** High (two external reports + 4 unexecuted retro Tries all point at the same gap)

---

## Problem

Sprint-004 shipped three mechanical hooks for SMM resolution-link discipline (decision-time open-questions nudge, commit-auto-link nudge, attribution-anomaly detector). The mechanisms are in place. The discipline loop is not closed:

1. **We cannot measure adoption.** The commit-auto-link nudge fires into agent context with no tracking event, so retros cannot compute whether agents act on it. SimplyHuman's sprint-006 shipped 7 of 10 unlinked resolutions after adopting the convention four retros in a row — no feedback signal means no correction.
2. **Four retro Tries adopted-but-unexecuted.** Per-commit quality-review linkage hook (#5), duplicate-debt detector (#6), M<15 size-floor enforcement (#4), file_domain discipline (#7). All "adopt as decision → forget by next sprint."
3. **`domain_accuracy` is actively misleading.** Sprint-004 data confirms it penalizes well-planned stories whenever post-story cleanup commits attach to them. The attribution-anomaly fix from sprint-004 does NOT clear the noise.

This doc unifies the three threads into one execution-plan direction.

---

## Data supporting the direction

### Sprint-004 sizing measurements (post-close, 2026-04-19)

| Story | Size | Commits | Files | in-domain | domain_accuracy | attribution_anomaly |
|-------|------|---------|-------|-----------|-----------------|---------------------|
| story-001 | M | 4 | 10 | 3 | **0.30** | false |
| story-002 | M | 3 | 11 | 6 | 0.55 | false |
| story-003 | S | 1 | 2 | 2 | 1.00 | false |

**`attribution_anomaly` works as designed** — zero false positives on a well-behaved sprint.

**`domain_accuracy` stays broken** — story-001 scored 0.30 because the post-merge simplify commit (`47f366f`, 9 files across all three stories' domains) got attributed to story-001 via `_resolve_story_id`'s tier-2 tie-break on file-domain overlap. The teammate's actual story work (commit `3cff206`) was clean and fully in-domain. The "bad planning" signal is a lie; the real cause is cross-cutting-forced-to-one-story.

**story-003's 1.0 is artificially clean** — tight S-sized stories score high mechanically regardless of planning quality. The metric flatters small stories and punishes anything with cleanup work. It is measuring story size, not planning.

### Resolves-Event trailer adoption (SimplyHuman sprint-006, external report)

- `resolves_link_rate = 3/10 = 30%` — 7 of 10 commits that matched an open concern shipped without a trailer.
- Convention adopted in retro four sessions running without adoption sticking.

Both signals converge: mechanical nudges without measurement are invisible; conventions without enforcement decay.

---

## Theme 1: Close the retro-feedback loop

### 1.1 Amend command in commit-auto-link nudge

**Current** (`bash_post_tool._handle_commit`): nudge text says `"Consider adding `Resolves-Event: {id}` trailer."`
**Proposed:** show the exact command the agent can run:

```
Auto-link nudge: concern {id} — {first-80-chars}.
If correct, re-commit with:
  git commit --amend --trailer "Resolves-Event: {id}"
```

Multi-candidate: join IDs with commas, cap at 5 to prevent flood.

**Files:** `scripts/bash_post_tool.py`, `tests/hooks/test_bash.py` (~15 lines)

### 1.2 Status event for retro tracking

Emit a `status` event whenever the probe surfaces candidates, so the retro can compute adoption rate.

**Event shape:**
```
type=status
content="resolves_probe_shown: N candidates"
metadata={"probe_candidates": ["<id1>", "<id2>", ...], "commit_hash": "<hash>"}
```

**Retro metric (computed in `retrospective.py`):**
```
resolves_link_rate = count(commits whose subsequent commit adopts trailer for a probe candidate)
                   / count(resolves_probe_shown events in sprint)
```

Surfaced in Sprint Analysis under a new "Resolution-link adoption" subsection.

**Target:** ≥80% for three consecutive sprints → retro stops raising the convention.

**Files:** `scripts/bash_post_tool.py`, `scripts/retrospective.py`, `agents/xp-retrospective.md`, tests

### 1.3 Explicit 12-hex ID mention as implicit trailer

If a commit body contains a 12-hex ID that matches an open concern / question / debt event, treat it as a Resolves-Event trailer (still emit a discipline nudge that says "use the formal trailer next time," but accept the link).

**Rationale:** Low-noise; agents sometimes write the id intentionally in free-form prose without formal trailer syntax. Don't penalize honest intent.

**Files:** `scripts/commits.py:extract_resolves_trailer` (extend to scan body for bare open-event IDs, not just `Resolves-Event:` lines), tests

### 1.4 Port probe to `/xp-quality-review`

Currently the auto-link probe fires in `bash_post_tool.py` PostToolUse (after the commit already happened; requires `git commit --amend` to fix). Pre-commit probe in `/xp-quality-review` is cleaner — surfaces candidates before the agent writes the commit, so the trailer lands on the first commit without amend.

Keep `bash_post_tool.py` as the fallback for teammates that skip `/xp-quality-review`. Dedup: the hook skips if the review already fired for the same file set + open-concern set this session (tracked via a session marker).

**Files:** `skills/xp-quality-review/SKILL.md`, new `scripts/resolves_probe.py` (extracted from `bash_post_tool`), `scripts/bash_post_tool.py` (dedup logic), tests

### 1.5 Retire `domain_accuracy`; emit `cascade_size` as unscored info

**Evidence (section above):** domain_accuracy is dominated by story size and whether cross-cutting commits attach. Neither correlates with planning quality. No ratio-form of this metric can be made honest without solving attribution pathology that is intrinsic to cross-cutting work.

**Proposed per-story record change:**

- **Remove:** `domain_accuracy`, `in_domain_files`, `out_of_domain_files` fields.
- **Add:** `cascade_size: int` — count of committed files not in the declared `file_domain`. Informational only, no threshold.
- **Retro agent reads it descriptively:** *"story-001 touched 7 cascade files — expected for the post-story simplify sweep."* Judgment stays with the retro agent, supported by the count.

**Also fix:** `_resolve_story_id` tier-2 tie-break. Currently, when multiple in-progress stories tie on file-domain overlap, it picks the first one. Proposed: return `None` on multi-way tie, so cross-cutting commits get null story_id and land at sprint level rather than pinning one story.

**Files:** `scripts/sizing_metrics.py`, `scripts/bash_post_tool.py:_resolve_story_id`, `agents/xp-retrospective.md`, tests

### 1.6 Remove stale domain_accuracy references

- `agents/xp-retrospective.md`: delete the "flag stories with `domain_accuracy < 0.5`" prompt branch.
- Any prior-retro Tries tied to domain_accuracy tuning: mark superseded with `metadata.supersedes=[<try_id>]` on a decision event during the retire-sprint.

---

## Theme 2: Execute the adopted-but-unexecuted Tries

Four retro Tries keep getting adopted without landing. Codify them here so `/xp-plan` pulls them into the execution plan.

### 2.1 M<15 size-floor enforcement at plan time (Try #4)

Adopted as decisions `d7b8df6433f0` (sprint-003) + `032e57cce919` (sprint-004 kickoff). Not yet implemented.

**Enforcement:** `xp-review-plan` blocks plans where any M-sized story's declared `file_domain` (plus sibling test-file projection) exceeds 15 files. Reviewer reports "size floor violation: story-NNN declares 17 files at size M; must be L or split." Sprint-004 measurements show total file touches per M story at 10-11, so the threshold is already being respected in practice — codifying prevents drift.

**Files:** `skills/xp-review-plan/SKILL.md`, `agents/xp-plan-reviewer.md`, tests

### 2.2 Per-commit quality-review linkage hook (Try #5)

Adopted. Not yet implemented.

**Mechanism:** PostToolUse:Bash hook on `git commit`. Scan the last N events for a `status` event matching "Quality review complete" or "Code review complete" dated after the last commit. If none, inject `additionalContext` warning: *"No preceding quality_review within N events — was the review skipped?"*

**Files:** `scripts/bash_post_tool.py` (new branch in `_handle_commit`), tests

### 2.3 Duplicate-debt detector (Try #6)

Adopted. Not yet implemented. Motivated by `182584eecff0` / `924ad2756dfa` (two debts describing the same fix, filed in the same session).

**Mechanism:** In `append.sh` (or a SubagentStop hook for `xp-housekeeper`). On new debt event, Jaccard similarity > 0.8 against recent debt contents (normalized: lowercased, punctuation-stripped, stopwords removed) → append an advisory `concern` event: *"new debt resembles <id>; consider `metadata.resolves=[<id>]` to dedup."*

**Files:** new `scripts/dup_debt_probe.py`, `scripts/concerns.py` hook point, tests

### 2.4 file_domain discipline — partially subsumed (Try #7)

The original Try proposed tightening sprint.json authoring so file_domain covers the expected work surface. **Subsumed by 1.5:** once `cascade_size` replaces the scored ratio, over-declaration stops being incentivized. Remaining discipline: declare what the planner genuinely expects. Codify in PROCESS_GUIDE.md as soft guidance, not an enforced check.

**Files:** `PROCESS_GUIDE.md` one-paragraph addition

---

## Non-goals

- **No NLP-style keyword matching for concerns.** Ruled out during FR_resolves_trailer discussion. Keyword overlap has high false-positive noise and conflicts with the STRUCTURAL-link discipline codified in sprint-004 (reviewer concerns MUST carry `files=[]`). If the tool fuzzily matches without files, agents stop filing files.
- **No auto-insertion of Resolves-Event trailer** without agent confirmation. Silent commit-message modification violates Honesty — the agent should see the match and decide.
- **No retroactive re-linking** of already-emitted commit events. SMM is append-only; past unlinked commits stay unlinked. Retros handle the cleanup via curation-level `metadata.resolves`.
- **No `domain_accuracy` restoration** in any form. Retired, not renamed.

---

## Success metrics (post-delivery)

- **`resolves_link_rate` ≥ 80%** for three consecutive sprints → Try stops appearing in retros.
- **Zero `attribution_anomaly=true` stories** for three consecutive sprints (already hitting this; guards against regression).
- **Retro output no longer mentions `domain_accuracy`.** Grep history for the literal string returns only historical entries.
- **Size-floor violations ≤ 1 per sprint.** Some judgment-call bending is fine; systematic over-packing isn't.
- **Duplicate-debt advisories ≤ 2 per sprint.**

---

## Suggested milestones (for `/xp-plan` to refine)

- **M1: Close the feedback loop** — Theme 1 items 1.1, 1.2, 1.3, 1.5, 1.6. Ship together; measurement (1.2) only works when the nudge (1.1) is actionable. Item 1.6 is cleanup that naturally lands with 1.5.
- **M2: Probe in `/xp-quality-review`** — Theme 1 item 1.4. Independent file surface (skill + new script + dedup marker); good candidate for solo or one-teammate sprint.
- **M3: Execute adopted Tries** — Theme 2 items 2.1, 2.2, 2.3. Three stories with disjoint file surfaces, good `/xp-assign` fan-out candidate. Item 2.4 is doc-only, bundle with M1.

---

## References

- **SMM events** (decisions adopted-but-unexecuted): `dc01ca694e51`, `3e705a6169e8`, `d7b8df6433f0`, `032e57cce919`.
- **Debts** (related, not in scope here): `c5f333b3221a` (`load_events_with_resolutions`), import-style-sweep debt — both in `CONSOLIDATION_REFACTOR.md`.
- **Superseded docs:** `docs/ideas/BUG_domain_accuracy_wrong_signal.md`, `docs/ideas/FR_resolves_trailer_prompting.md`.
- **Sprint-004 sizing data** (preserved in "Data supporting the direction" section) — the empirical justification for retiring `domain_accuracy`.

---

## Author

Filed 2026-04-19 by xp-agents self-dogfood at sprint-004 close. External reports from SimplyHuman project (the BUG + FR docs) confirmed as the same underlying pattern: mechanical enforcement plus measurement is the only path that scales. Design supersedes both external reports.

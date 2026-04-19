# Consolidation Refactor — Pay down accumulated shared-helper debt

**Plugin:** `xp-agents`
**Type:** Refactor sprint design source
**Priority:** Medium (no user-visible behavior change; reduces friction on future hook work)

---

## Problem

Sprint-004's mechanical-hook work added two new call sites that read `events.jsonl` and compute resolutions independently — joining an existing pile of copy-paste sites. The per-site diff is small; nobody extracts. The sum is real friction for the next hook author.

None of these is a correctness bug. All are **refactor debt the reviewer flagged during sprint-004 quality review** and we filed rather than pay inline.

---

## Scope

Pure refactor. No user-visible behavior change. All tests green throughout. All three sections share the same call-site list, so sequencing matters.

---

## Section 1: `load_events_with_resolutions` helper

**Current state — 6 call sites with near-identical prologue:**

```python
events = _common.read_events_raw(smm_dir)
resolutions = resolution.compute_resolutions(events)
# …then filter for the relevant bucket
```

**Sites:**
- `scripts/pre_tool_bash.py:_open_questions_context` (sprint-004)
- `scripts/commits.py:open_concerns_matching_commit` (sprint-004)
- `scripts/_common.py:count_unresolved_concerns`
- `scripts/session_end.py` (question-filter)
- `scripts/retrospective.py` (question-filter)
- `scripts/prompt_nugget.py` (concern/question delivery)

**Proposed:**

```python
# scripts/_common.py
def load_events_with_resolutions(smm_dir: Path) -> tuple[list[dict], dict]:
    """Read events.jsonl and compute resolutions in one call.

    Returns (events, resolutions). resolutions is the dict returned by
    resolution.compute_resolutions — contains resolved_concern_ids,
    answered_question_ids, resolved_debt_ids, etc.
    """
    events = read_events_raw(smm_dir)
    return events, resolution.compute_resolutions(events)
```

Each call site collapses to one-liner:

```python
events, resolutions = _common.load_events_with_resolutions(smm_dir)
open_qs = [e for e in events if e.get("type") == _common.QUESTION
           and e.get("id") not in resolutions["answered_question_ids"]]
```

**Debt reference:** `c5f333b3221a`

---

## Section 2: Import-style sweep for `compute_resolutions`

**Current state — three import styles coexist:**

| Style | Example call | Files |
|-------|--------------|-------|
| `from resolution import compute_resolutions` | `compute_resolutions(events)` | `pre_tool_bash.py` (+ others) |
| `import resolution` + module-qualified | `resolution.compute_resolutions(events)` | `commits.py`, `session_end.py`, `retrospective.py` |
| `from _append_impl import compute_resolutions` | `compute_resolutions(events)` | `concerns.py`, `tdd_check.py` — older re-export |

**Proposed:** Canonical form is `import resolution` + module-qualified call. Rationale:
- Module-qualified calls make grep-for-consumers accurate.
- Matches the dominant existing pattern (majority of current sites already use it).
- Keeps cold-path imports of heavy modules grep-visible.

Once all consumers migrate off `_append_impl.compute_resolutions`, remove the re-export.

**Debt reference:** filed by `xp-code-reviewer` during sprint-004 quality review (no event id captured; see the review summary for the full file list).

---

## Section 3: Thread events through `_handle_commit`

**Current state:** one commit triggers multiple events.jsonl reads:

1. `commits.open_concerns_matching_commit(smm_dir, committed_files, cwd)` — read events + compute resolutions.
2. `_resolve_lint_on_commit` → `concerns.resolve_concerns` → reads events internally.

Commits are not a hot path, but the pattern spreads: any new check added to `_handle_commit` will pay the same price, and eventually the overhead compounds.

**Proposed:** Thread `events` and `resolutions` through `_handle_commit` as optional kwargs. Helpers accept `events=None` / `resolutions=None` and fall back to self-load when called standalone. Zero signature break for external callers.

```python
def _handle_commit(smm_dir, agent_id, cwd, response_text,
                   events=None, resolutions=None):
    if events is None or resolutions is None:
        events, resolutions = _common.load_events_with_resolutions(smm_dir)
    # … pass events/resolutions to open_concerns_matching_commit
    # … thread into concerns.resolve_concerns when that helper adopts the kwarg
```

Depends on Section 1 — the helper must exist first. `concerns.resolve_concerns` also needs an optional `events=` kwarg to actually eliminate the inner read; that's scope-adjacent and may span a follow-up story.

**Debt reference:** `6926074eb2a2` (pre-existing, sprint-004 teammate B flagged it).

---

## Milestones

- **M1: Ship `load_events_with_resolutions` helper + migrate 6 call sites.** Atomic refactor; must stay green. Paves M2/M3.
- **M2: Import-style sweep.** Independent file surface from M1's call-site changes. Mostly mechanical; low-risk. Can run in parallel with M1 via `/xp-assign`.
- **M3: Thread events through `_handle_commit`.** Depends on M1. Small, but requires touching `concerns.resolve_concerns` to realize the efficiency win.

All three are disjoint file surfaces and good `/xp-assign` fan-out candidates — ideal refactor sprint shape.

---

## Non-goals

- **No new features, no new hooks.** Pure consolidation.
- **No schema changes.** `events.jsonl` shape unchanged.
- **No semantic changes to `compute_resolutions`.** Signature and return stay identical.
- **No abstraction-for-its-own-sake.** If extracting surfaces a deeper abstraction (e.g., a "resolved view" object wrapping events + resolutions), resist — ship the flat tuple first. A follow-up can layer abstraction if the usage pattern demands it.

---

## Success metrics

- Call sites of "read_events_raw + compute_resolutions + filter" collapse from **6 → 1 helper + 6 one-line callers.**
- `compute_resolutions` import style **normalized** across all 14+ files (one style, `import resolution`).
- `_handle_commit` reads events **at most once per commit** (plus one indirect read from `concerns.resolve_concerns` until that helper also adopts the kwarg).
- **Full test suite green. Zero regressions.**
- **No observable behavior change in retros or SMM output.**

---

## References

- **Debts** (will be cited by metadata.resolves when this ships): `c5f333b3221a` (load_events_with_resolutions), `6926074eb2a2` (_handle_commit triple read), plus the import-style-sweep debt filed by xp-code-reviewer in sprint-004 quality review.
- **Source incident:** sprint-004 post-merge `/simplify` + `/xp-quality-review` surfaced all three items; filed as debt rather than paid inline because they spanned outside the sprint's file domain.
- **Related but separate:** `MECHANICAL_DISCIPLINE_CLOSURE.md` — behavior-additive mechanical work. Different risk profile. Should be a different sprint.

---

## Author

Filed 2026-04-19 by xp-agents self-dogfood at sprint-004 close. No external report — pure internal debt paydown surfaced by cross-teammate review. Referenced from `MECHANICAL_DISCIPLINE_CLOSURE.md` as a sibling planning doc.

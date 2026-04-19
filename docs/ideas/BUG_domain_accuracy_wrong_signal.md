# Bug: `domain_accuracy` metric consistently gives wrong signal for sweep/cascade stories

**Plugin:** `xp-agents`
**Component:** `scripts/sizing_metrics.py` — `_attribute_commits()` (surfaces in `/xp-run-retrospective`)
**Severity:** High (5th consecutive retro flagging this; metric is load-bearing in retros but its signal is inversely correlated with actual story quality)

---

## Summary

The `domain_accuracy` metric — `in_domain_files / files_changed` per story, computed by `scripts/sizing_metrics.py:96` — scores stories near 0.0 whenever the committed work legitimately touches cascade files (Playwright specs, configs, fixtures, integration tests, e2e tests) that were not pre-declared in `file_domain`. The metric then flags the story as poorly planned, when in reality the planning was correct and the cascade files _had to_ be touched.

Concrete evidence from a single project's last 5 sprints (SimplyHuman, sprint-001 through sprint-006):

| Sprint         | Stories                | Worst-story `domain_accuracy` | Retro disposition              |
| -------------- | ---------------------- | ----------------------------: | ------------------------------ |
| sprint-002     | (early type-hardening) |                         ~0.12 | "domain_accuracy needs fix"    |
| sprint-003     | type-hardening sweep   |                          0.08 | "domain_accuracy needs fix"    |
| sprint-004     | moderation schema      |                          0.15 | "domain_accuracy needs fix"    |
| sprint-005     | integration-test casts |                          0.22 | "domain_accuracy needs fix"    |
| **sprint-006** | **marketing M1**       |         **0.000** (story-004) | **"retire or fix the metric"** |

Sprint-006 story-004 (a test-only regression-guard story) scored 0.0/1.0 while _correctly_ delivering its acceptance criteria. Story-003 (SPA login explainer) scored 0.017 across 58 files — again, correctly delivered. The metric is anti-correlated with success on the classes of work this project actually does.

---

## Current implementation

`scripts/sizing_metrics.py:52-97`:

```python
def _attribute_commits(commit_events, stories):
    story_domains = {
        s["id"]: extract_file_domain_paths(s.get("file_domain", []))
        for s in stories
    }
    # ...
    for commit in commit_events:
        story_id = commit.get("metadata", {}).get("story_id")
        # ...
        domain_files[story_id] |= {
            f for f in committed_files
            if file_matches_domain(f, domain)
        }
    # ...
    domain_accuracy = in_d / total
```

`file_matches_domain` (line 34) matches on:

1. Exact path equality
2. Path-suffix match (`a/b/foo.py` matches `foo.py`)
3. `test_foo.py` → `foo.py` mapping (Python-style test naming)

What it does NOT handle:

- TS/JS test naming (`foo.test.ts`, `foo.spec.ts`)
- Playwright e2e specs in `e2e/**/*.spec.ts` (rarely pre-declared — they're cascade work)
- Config files (`bunfig.toml`, `package.json`, `tsconfig.json`) that shift during story work
- Fixture files (`__integration__/fixtures/*.ts`)
- Import-graph downstream files forced to change by a schema narrowing

---

## Why the metric is wrong (root cause)

The metric asks: "Did the commits touch the files the planner pre-declared?"

But the planner cannot pre-declare cascade files without doing the implementer's job first. Cascade files fall into three classes:

1. **Reactive cascade** — narrowing a type in `shared/src/types/*` forces typecheck fixes in 12+ consumer files. The planner doesn't know which consumers break until tsc runs.
2. **Test cascade** — changing a route shape forces Playwright specs in `e2e/**` to update. The planner who owns the API doesn't own the e2e harness and often doesn't know which specs assert on the route.
3. **Config cascade** — a marketing-pages story touches `index.html`, `marketing.css`, `marketing.ts`, plus the test that asserts bundled CSS loads, plus maybe `bunfig.toml` if test patterns shift. Three of those four are legitimate story files; one is a cascade.

The planner _could_ enumerate every cascade file up front, but that:

- Burns planning time on mechanical discovery the tool can do
- Encourages over-declaration (to pad the metric), which makes file_domain noise
- Becomes wrong the moment the codebase changes (stale domain pre-declarations)

---

## Repro steps

1. Start a fresh SMM: `init.sh` → `seed_smm.py`.
2. Create a sprint with a story whose work touches test files or e2e specs:
   ```json
   {
     "id": "story-001",
     "title": "Narrow `UserRole` literal union",
     "size": "S",
     "file_domain": ["packages/shared/src/types/user.ts — change"]
   }
   ```
3. Commit the schema change alongside the downstream typecheck fixes:
   ```bash
   # Story commit touches 1 declared file + 14 undeclared consumers
   git commit -m "narrow UserRole" -- \
     packages/shared/src/types/user.ts \
     apps/server/src/routes/users.ts \
     apps/server/src/routes/admin.ts \
     # ... 12 more consumer files forced by tsc ...
   ```
4. Run `/xp-run-retrospective`.
5. Observe: `domain_accuracy` = 1/15 = **0.067**.
6. Retro labels the story poorly-planned. It was not — the cascade was unavoidable.

---

## What "right" looks like — three viable options

### Option A — Import-graph auto-include (high engineering cost, high accuracy)

At sprint planning time, for each declared file in `file_domain`, run a static import-graph traversal and include direct consumers. `typescript-language-server` or `tsc --listFiles` can produce the graph for TS projects; `grep -r "from .*/<file>"` is a poor-man's fallback.

**Pros:** Metric becomes meaningful. Cascade is pre-declared automatically.
**Cons:** Language-specific tooling per project. Needs sandboxing (don't want to run `tsc` from inside a retro hook). May over-include (a widely-imported `types/index.ts` pulls the world).

### Option B — Domain-neutral classification (medium cost, medium accuracy)

Classify files into "owned" vs "domain-neutral" buckets:

- **Owned:** `apps/**/src/**`, `packages/**/src/**` (excluding tests)
- **Domain-neutral:** `**/__tests__/**`, `**/__integration__/**`, `e2e/**/*.spec.ts`, `**/*.test.ts`, `**/*.spec.ts`, top-level config files (`*.toml`, `tsconfig*.json`, `package.json`)

Compute `domain_accuracy` on owned files only; report `cascade_size` separately as `count(domain-neutral files touched)`.

**Pros:** Works without language tooling. Captures the two signals retros actually care about (did we plan the code we own correctly? how large was the test/config cascade?).
**Cons:** Requires project-level config for "owned" paths. One-size-fits-all patterns will miss edge cases.

### Option C — Retire `domain_accuracy`, replace with `sweep_completeness` (low cost, low accuracy for planning quality)

Stop measuring accuracy. For sweep-style stories, measure completeness: "did the grep/tsc sweep return zero after your final commit?" Boolean, not ratio.

**Pros:** Trivial to implement. Removes a 5-retro noise source.
**Cons:** Doesn't measure planning quality at all. Doesn't catch "story was sized S but was actually L."

### My recommendation

**Adopt Option B + a reduced Option C for sweeps.** Report two metrics:

1. `planning_accuracy` = in_owned_domain_files / owned_files_touched — tells the planner "did we name the right code files?"
2. `cascade_size` = count(domain-neutral files touched) — tells the planner "did we underestimate the blast radius?"

Both signals are actionable. Neither is anti-correlated with success. This matches what the `cascading-file disclosure` retro try adopted by this project on 2026-04-18 (SMM constraint `f642734e36f0`) is reaching for from the planner's side.

---

## Scope of fix

Touches:

- `scripts/sizing_metrics.py` — `_attribute_commits`, `file_matches_domain`, public signature
- `agents/xp-retrospective.md` — update the retro prompt to read the new two-metric surface
- `tests/hooks/test_sizing_metrics.py` — add cases for test-file naming, config paths, e2e specs

Migration: old retro reports cite `domain_accuracy`. Keep the field emitted but flagged `@deprecated` for one release, OR remove and rely on retro-agent prompt updates.

---

## Related events in this project's SMM

- Retro try `5de79ac439b7` (adopted as constraint `f642734e36f0`): planning-side cascade disclosure — the other half of this fix.
- Decisions citing this: `bc601024aea4`, `d4866a8e8f2c`, `0974ead94c6f` — all priors where domain_accuracy led retros astray.
- Sprint-006 retro explicitly stated: "5th consecutive retro with no mechanical fix landed — pick a mechanical option OR retire the metric."

---

## Author

Filed by SimplyHuman project during sprint-007 kickoff, 2026-04-18. User asked for a writeup after the 5th retro in a row flagged the metric without progress. Happy to prototype Option B as a PR if the plugin team accepts the direction.

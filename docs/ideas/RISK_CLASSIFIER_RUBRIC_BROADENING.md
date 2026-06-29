# Risk-classifier rubric broadening (xp-risk-classifier)

**Status:** idea
**Source:** sprint-107 story-005 capstone observations (live per-story pipeline run)
**Files in scope:** `plugins/xp-agents/agents/xp-risk-classifier.md`; possibly `plugins/xp-agents/agents/xp-code-reviewer.md` Section 1c for new SIGNAL keywords

## What the classifier does today

Spawned in `/xp-quality-review` Step 1.4 when `MODE=self-find`. Reads the diff
+ changed-files list, returns `RISK=high|low` on the first line + optional
`SIGNALS=<comma-list>` on the second. Single Haiku-tier call. The reviewer's
optional `## Review Focus` block enriches xp-code-reviewer only on `RISK=high`,
naming the angles to elevate. Default angle when `SIGNALS=` is empty is
`state/lifecycle/concurrency`.

## Observation (sprint-107)

Three teammate stories ran through the classifier. Each verdict was on-rubric
but the rubric itself missed the angle that mattered most for the largest
story:

- **story-003** (79 LOC, 1 CLI pre-check, 5 tests). `RISK=low`,
  `SIGNALS=validation,idempotency-guard`. Correct call.
- **story-001** (1313 LOC, NEW pure-function module + 10 BUILTIN data tables +
  96 tests, cross-runtime API landmine, csharp_xunit path-escape bug caught
  later by the reviewer). `RISK=low`, `SIGNALS=pure-function,immutable-data`.
  **On-rubric but undercounted** — the reviewer found a real path-escape bug
  in csharp_xunit's `{dir}/../Tests/...` rule (resolved candidates escaped
  `project_root` via lexical `..`). Caught by the reviewer's correctness
  self-find, not by `## Review Focus` enrichment.
- **story-002** (600 LOC, schema validator + CLI + renderer + agent prose).
  `RISK=low`, `SIGNALS=schema-extension,optional-field`. Correct call.

## The mismatch

Today's rubric is essentially one dimension: state/lifecycle/concurrency. The
classifier correctly says "doesn't need that enrichment" for pure-function or
schema-extension diffs, but "doesn't need state/lifecycle enrichment" is NOT
the same as "doesn't need any enrichment." Story-001 had three real risk
dimensions the rubric doesn't name:

1. **Sheer size** — more code, more cells to get wrong.
2. **Combinatorial data-table coverage** — a 10-entry enum × multiple rules
   per entry is a matrix where one off-by-one silently misroutes.
3. **Cross-runtime portability** — one concrete instance: `PurePosixPath.match`
   doesn't honor mid-`**` until Python 3.13 (our CI runs 3.11/3.12). The
   generic shape is "API behavior that differs across versions/runtimes the
   project supports" — same shape shows up as a Node-version diff in a JS
   project, a Cargo MSRV in a Rust project, etc.
4. **Path-traversal** — `{dir}/../...` substitution + globbing + lexical
   relative-path resolution = silent project-root escape unless guarded.

## Plugin-vs-project boundary (load-bearing)

**xp-agents ships to projects in any language.** The classifier and its
signals must be **project-agnostic in shape** — describe the risk pattern, not
the language. Anti-patterns to avoid:

- A signal that only makes sense for plugins shipping to many languages (e.g.
  "code claims to work across N stacks") — that's xp-agents-internal review
  judgment, not a generic risk signal. A user's TS-only project doesn't need
  it. Plugin-internal heuristics belong in the plugin's CLAUDE.md or
  system_context principles, NOT in the shared classifier rubric.
- A signal hardcoded to one language's API (e.g. "PurePosixPath.match
  Py 3.11/3.12 issue"). That's an example of a generic shape, not the shape
  itself.
- A signal hardcoded to xp-agents conventions (e.g. "diff pushes file past 500
  lines" — 500 is OUR cap; another project's cap may differ or not exist).

The signals below are project-agnostic shapes; the *examples* in the
classifier prose may be language-flavored, but the rubric is the shape, and
thresholds/triggers should defer to the host project's own conventions where
possible (CLAUDE.md, linter config, etc.).

## Concrete signals to add

Priority-ordered. Each is a candidate value for the classifier's `SIGNALS=`
line; xp-code-reviewer Section 1c gains corresponding enrichment guidance.

| New signal | When to flag (project-agnostic shape) | Maps to reviewer angle |
|---|---|---|
| `path-traversal` | code resolves user/data-driven strings through a path-joining + globbing/IO chain (any language: `glob`, `fs.readFile`, `os.walk`, shell `find`, etc.) | path-escape guards, lexical-vs-real resolution, allowlist patterns |
| `input-validation` | new validator on data crossing a trust boundary (CLI stdin, JSON load, HTTP request, env var) | unknown-key reject, type coercion, error-message helpfulness |
| `combinatorial-data-table` | new enum/dict/map with N+ entries where each entry drives rules or branches | per-entry positive + negative test; cell-by-cell review |
| `cross-runtime-portability` | code depends on API behavior that differs across language/runtime versions the project's CI matrix exercises | version-pinned assertions; runtime probes; fallback paths |
| `file-size-creep` | diff pushes a file past **the project's** coding-standard size cap (read from CLAUDE.md / .editorconfig / linter rule when available; fall back to a generic large-file heuristic) | extract recommendation; debt vs split-now |
| `schema-cross-contract` | new schema field/enum/constraint that ANOTHER concurrently-developed change locks (parallel-frontier stories, sister branches) | integration test pinning both sides of contract |

`schema-cross-contract` has a slight plugin-flavored framing — sister-branch
parallel-frontier is an xp-agents pattern. The *shape* (two changes lock the
same contract simultaneously) is generic; the *trigger* ("sister branches in
the same plan") is plugin-specific. The rubric should describe the shape and
let the classifier infer triggers from whatever parallel-change signal the
host project surfaces (git branches with shared base, open PRs targeting the
same release, etc.).

## Suggested decision matrix

The LOC thresholds are illustrative; per-project tuning is expected since
"large" varies by codebase. The host project's coding standards should drive
the actual numbers where possible.

- `RISK=low` only when: ≤200 LOC AND no signals from the table above AND no state/lifecycle/concurrency surface.
- `RISK=high` when: any path-traversal, cross-runtime-portability, or schema-cross-contract; OR ≥500 LOC; OR combinatorial-data-table with ≥5 entries.
- Use `RISK=high` to drive `## Review Focus` enrichment naming the specific signal(s); the reviewer then elevates those angles in Section 1c.

## Why this matters for cost

Today's pattern lets the reviewer's correctness self-find catch what the
classifier misses (that's how the path-escape bug was found). That works
because xp-code-reviewer is enriched and the angles default to
state/lifecycle/concurrency. But it relies on the reviewer's broad-pattern
intuition rather than directed attention. Broadening the classifier's signals
shifts catch from "reviewer happens to look" to "reviewer is told where to
look" — fewer false negatives at small extra Haiku tokens per classifier
call.

## Out of scope

- Replacing Haiku with a more capable tier. The cost ceiling on the classifier
  is real. The fix is rubric breadth, not model upgrade.
- Auto-promoting RISK=high → multi-agent fan-out. Single-spawn invariant
  stands (sprint-103 lesson). Enrichment is the lever.
- Renaming xp-risk-classifier. The name is fine; the rubric expansion is the
  real change.
- Baking xp-agents-internal heuristics (cross-language-coverage, the 500-line
  cap as a constant) into the classifier rubric. Those belong in
  plugin-internal review prose, not in the shared signal taxonomy.

## Acceptance ideas (for the implementation story)

- Plan-reviewer concern: rubric must explicitly enumerate the new signals,
  with each described in project-agnostic shape (not as a language-specific
  example).
- AC: spawn classifier on the sprint-107 story-001 diff (replayed) and assert
  RISK=high + SIGNALS contains path-traversal AND combinatorial-data-table.
- AC: spawn classifier on the sprint-107 story-003 diff (replayed) and assert
  RISK=low.
- AC: classifier prose contains no plugin-internal vocabulary that wouldn't
  apply to a TS-only or Rust-only project (mirrors the project_specific
  `plugin-project-agnostic` principle).

## See also

- [TEAMMATE_TIER_PICKER.md](TEAMMATE_TIER_PICKER.md) — sibling concern at plan-time (different agent: xp-plan-reviewer; different decision: executor_model selection). Uses no SIGNAL vocabulary — keeps the two classifications cleanly independent. Cousin, not sibling.

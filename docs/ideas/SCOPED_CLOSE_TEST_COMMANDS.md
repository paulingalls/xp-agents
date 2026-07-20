# Scoped test commands: fast story-close, thorough sprint-close

**Status:** idea / not scheduled
**Raised:** 2026-07-20 (sprint-124 discussion)

## Problem

Today a single `system_context.stack.test_command` (e.g. `pytest -n auto`) is
used everywhere: lefthook pre-commit, the story-close auto-merge gate
(condition 3), and sprint-close. Story-close runs **N times per sprint** (once
per story); sprint-close runs **once**. Running the *entire* suite on every
story-close — and every commit — is fine at this repo's ~1min, but does not
scale to a real monorepo where the full matrix is minutes-to-tens-of-minutes.
A story that touched one module still pays for the whole tree, every close.

## Idea

Split the close-gate test command by close mode, and (for monorepos) by
module/surface:

- **Story-close / commit** runs a **fast** command — ideally just the
  module(s)/surface(s) the story touched.
- **Sprint-close** runs the **thorough** command — the full cross-module matrix
  (the union of all surfaces, or an explicit full command).

This mirrors standard CI practice: PR checks run affected-module tests;
main/nightly runs everything.

## Proposed shape (optional, back-compatible)

1. `stack.test_command` stays the default — used by commit + story-close +
   fallback. **Single-module projects change nothing.**
2. Add optional `acceptance_surfaces[].test_command` (per surface). Story-close
   maps the story's `file_domain` -> surface(s) and runs the **union** of their
   commands.
3. Sprint-close runs the full set — all surfaces, or an explicit
   `stack.sprint_test_command`.
4. The auto-merge gate (condition 3) reads the command by close mode.

## Load-bearing design work

- **Deterministic `file_domain -> surface` mapping.** This is the crux. Each
  surface declares the paths it owns; the story's touched paths resolve to
  surface(s).
- **Fail-closed fallback.** If a story touches a path that maps to **no**
  surface, run the full `stack.test_command`, never skip. An unmapped path must
  never cause a story to merge *less*-tested by accident.
- **Language-agnostic** (project-agnostic guardrail): the mapping is
  path-prefix / declared-surface based, never per-language build inference in
  shipped code.

## The honesty tradeoff (must be a conscious decision)

This **changes an invariant**. Today: *the sprint base is green after every
story-close.* With scoped story-close: *the sprint base is green after
sprint-close*, but between story-closes a story could merge having passed its
own module while breaking another (shared lib, cross-module import) — a
red-sprint-base window until the full matrix runs at sprint-close.

That is the standard PR-vs-nightly trade and usually the right one, but it is a
real weakening of the auto-merge honesty guarantee. The scoping should be
**opt-in**, and the doc/decision should state the invariant shift explicitly so
a project chooses it deliberately.

## Scope

Milestone-sized: schema change (`system_context_schema`), close-gate routing
(`close_common.py` condition-3 command selection by mode), the `file_domain ->
surface` mapping + fail-closed fallback, and the honesty-invariant decision.
Not a mid-sprint bolt-on. Plan it as its own milestone/spike.

## Related

- `system_context.acceptance_surfaces` (existing surface model)
- Per-story `acceptance_execution.command` (already lets a *story* scope its
  acceptance test — partial precedent)
- Auto-merge gate condition 3 (`skills/xp-story-close`, `close_common.py`)
